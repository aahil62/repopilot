import json
import sys

from repopilot.engines.bench import ModelScore, recommend, run_bench, select_tasks, similarity, task_score
from repopilot.memory.history import import_history
from repopilot.memory.store import MemoryStore
from repopilot.runtime import FakeRuntime
from repopilot.runtime.detect import ModelInfo
from repopilot.runtime.hardware import Hardware

GB = 1024**3
HW = Hardware(16 * GB, "Apple M4", 12 * GB, True)
TOML = f'[checks]\ntest = "{sys.executable} -m pytest -q -x -p no:cacheprovider"\n'
V1 = "def area(w, h):\n    return w * h\n"
V2 = "def area(w, h):\n    if w < 0 or h < 0:\n        raise ValueError('negative')\n    # dimensions are validated above\n    return w * h\n"
TEST = "import pytest\nfrom geo import area\n\n\ndef test_area():\n    assert area(2, 3) == 6\n"


def _history_repo(git_repo):
    return git_repo(
        [
            ("init", {"geo.py": V1, "test_geo.py": TEST, "repopilot.toml": TOML}),
            ("Reject negative dimensions in area", {"geo.py": V2}),
            ("docs only change here", {"README.md": "hello\n"}),
            ("Merge branch feature", {"geo.py": V2 + "\n"}),
            ("big rewrite of geometry", {"geo.py": V2 + "".join(f"\nX{i} = {i}" for i in range(80)) + "\n"}),
            ("short", {"geo.py": V2}),
        ]
    )


def test_select_tasks_filters_and_is_deterministic(git_repo):
    repo = _history_repo(git_repo)
    store = MemoryStore.open("bt1")
    import_history(store, repo, 100)
    tasks = select_tasks(store, repo, n=10, seed=7)
    assert [t.subject for t in tasks] == ["Reject negative dimensions in area"]
    assert tasks == select_tasks(store, repo, n=10, seed=7)
    assert "+    if w < 0 or h < 0:" in tasks[0].real_diff


def test_scoring_formula():
    assert task_score(True, True, 0.5) == 0.9
    assert task_score(True, False, 1.0) == 0.4
    assert task_score(True, None, 0.4) == 0.7
    assert similarity("+a\n-b\n", "+a\n-b\n") == 1.0


def test_recommendation_respects_latency_cap():
    slow = ModelScore(
        model="big:32b",
        size_bytes=20 * GB,
        score=0.9,
        applies_rate=1,
        tests_pass_rate=1,
        similarity=0.9,
        median_latency_s=95,
        tokens_per_second=4,
        tasks=[],
    )
    ok = ModelScore(
        model="mid:7b",
        size_bytes=5 * GB,
        score=0.7,
        applies_rate=1,
        tests_pass_rate=1,
        similarity=0.7,
        median_latency_s=18,
        tokens_per_second=34,
        tasks=[],
    )
    small = ModelScore(
        model="tiny:1.5b",
        size_bytes=1 * GB,
        score=0.3,
        applies_rate=1,
        tests_pass_rate=0,
        similarity=0.3,
        median_latency_s=4,
        tokens_per_second=120,
        tasks=[],
    )
    text, strong, fast = recommend([slow, ok, small])
    assert strong == "mid:7b" and fast == "tiny:1.5b"
    assert text.startswith("Use mid:7b for review and code (score 0.70, median 18 s")


def _server_error(messages):
    import httpx

    request = httpx.Request("POST", "http://x/api/chat")
    raise httpx.HTTPStatusError(
        "500", request=request, response=httpx.Response(500, request=request, text="boom")
    )


async def test_run_bench_scores_models_and_skips_oversized(git_repo):
    repo = _history_repo(git_repo)
    store = MemoryStore.open("bt2")
    import_history(store, repo, 100)
    good = json.dumps(
        {
            "explanation": "Validate.",
            "edits": [
                {
                    "path": "geo.py",
                    "search": "    return w * h",
                    "replace": "    if w < 0 or h < 0:\n        raise ValueError('negative')\n    # dimensions are validated above\n    return w * h",
                }
            ],
        }
    )
    bad = json.dumps(
        {"explanation": "Oops.", "edits": [{"path": "geo.py", "search": "not in file", "replace": "x"}]}
    )
    models = [
        ModelInfo("good:7b", "ollama", "http://x", 5 * GB),
        ModelInfo("bad:1b", "ollama", "http://x", 1 * GB),
        ModelInfo("broken:3b", "ollama", "http://x", 2 * GB),
        ModelInfo("huge:70b", "ollama", "http://x", 40 * GB),
    ]
    result = await run_bench(
        "bt2",
        repo,
        models,
        HW,
        runtimes={
            "good:7b": FakeRuntime({"strong": [good]}),
            "bad:1b": FakeRuntime({"strong": [bad]}),
            "broken:3b": FakeRuntime({"strong": [_server_error]}),
        },
    )
    by = {m.model: m for m in result.models}
    assert by["good:7b"].score == 1.0 and by["good:7b"].tasks[0].tests_pass is True
    assert by["bad:1b"].score == 0.0 and by["bad:1b"].applies_rate == 0.0
    assert by["broken:3b"].score == 0.0 and "runtime error" in by["broken:3b"].tasks[0].error
    assert result.skipped[0].model == "huge:70b" and result.skipped[0].reason == "needs ~40.0 GB"
    assert result.recommended_strong == "good:7b"


def test_slow_model_still_recommended_when_fast_ones_are_much_worse():
    def score(model, gb, value, latency):
        return ModelScore(
            model=model, size_bytes=gb * GB, score=value, applies_rate=1, tests_pass_rate=None,
            similarity=value, median_latency_s=latency, tokens_per_second=10, tasks=[],
        )  # fmt: skip

    text, strong, _ = recommend([score("qwen:7b", 5, 0.40, 93), score("qwen:1.5b", 1, 0.18, 13)])
    assert strong == "qwen:7b"
    assert "slow" in text and "93 s" in text
