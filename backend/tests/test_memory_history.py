import httpx

from repopilot.memory.codegraph import build_graph, dependents
from repopilot.memory.history import cochange, commits_touching, import_history, pr_for_commit
from repopilot.memory.indexer import index_code
from repopilot.memory.reviews import import_github_reviews, index_precedents
from repopilot.memory.store import MemoryStore
from repopilot.runtime import FakeRuntime


async def test_python_and_js_import_graph(git_repo):
    repo = git_repo(
        [
            (
                "init",
                {
                    "pkg/__init__.py": "",
                    "pkg/core.py": "def run():\n    return 1\n",
                    "pkg/api.py": "from .core import run\n\ndef handler():\n    return run()\n",
                    "pkg/cli.py": "from pkg.api import handler\n\ndef main():\n    handler()\n",
                    "app.py": "import pkg.cli\n",
                    "web/util.ts": "export function u() { return 1 }\n",
                    "web/main.ts": "import { u } from './util';\nexport const go = () => u();\n",
                },
            )
        ]
    )
    store = MemoryStore("g1")
    await index_code(store, repo, FakeRuntime())
    graph = build_graph(store)
    edges = {(e["source"], e["target"]) for e in graph.edges}
    assert ("pkg/api.py", "pkg/core.py") in edges
    assert ("pkg/cli.py", "pkg/api.py") in edges
    assert ("app.py", "pkg/cli.py") in edges
    assert ("web/main.ts", "web/util.ts") in edges
    assert dependents(graph, "pkg/core.py", depth=2) == [("pkg/api.py", 1), ("pkg/cli.py", 2)]


def _cochange_repo(git_repo):
    commits = [("init", {"a.py": "a0\n", "b.py": "b0\n", "c.py": "c0\n"})]
    for i in range(4):
        commits.append((f"change a and b {i}", {"a.py": f"a{i + 1}\n", "b.py": f"b{i + 1}\n"}))
    commits.append(("fix: crash on empty input", {"a.py": "a-fixed\n"}))
    commits.append(("touch c alone", {"c.py": "c1\n"}))
    bulk = {f"gen/f{i}.py": f"x{i}\n" for i in range(60)}
    bulk["a.py"] = "a-bulk\n"
    bulk["c.py"] = "c-bulk\n"
    commits.append(("regenerate files", bulk))
    return git_repo(commits)


def test_history_import_detects_fixes_and_counts(git_repo):
    repo = _cochange_repo(git_repo)
    store = MemoryStore("h1")
    assert import_history(store, repo, max_commits=5000) == 8
    fixes = commits_touching(store, ["a.py"], fixes_only=True)
    assert [f["subject"] for f in fixes] == ["fix: crash on empty input"]
    assert import_history(store, repo, max_commits=5000) == 0  # incremental: nothing new


def test_cochange_confidence_excludes_bulk_commits(git_repo):
    repo = _cochange_repo(git_repo)
    store = MemoryStore("h2")
    import_history(store, repo, max_commits=5000)
    # a.py touched in: init, 4x with b, fix  -> 6 non-bulk commits; b.py with a in init + 4 = 5
    result = {r["path"]: r for r in cochange(store, "a.py", min_support=3)}
    assert result["b.py"]["support"] == 5
    assert result["b.py"]["confidence"] == round(5 / 6, 3)
    assert "gen/f1.py" not in result  # bulk commit ignored


def test_history_cap_marks_truncated(git_repo):
    repo = _cochange_repo(git_repo)
    store = MemoryStore("h3")
    assert import_history(store, repo, max_commits=3) == 3
    assert store.get_meta("history_truncated") == "1"


def test_squash_merge_pr_number_recorded(git_repo):
    repo = git_repo([("init", {"a.py": "1\n"}), ("Add login flow (#412)", {"a.py": "2\n"})])
    store = MemoryStore("h4")
    import_history(store, repo, max_commits=100)
    sha = store.one("SELECT sha FROM commits WHERE subject LIKE 'Add login%'")["sha"]
    assert pr_for_commit(store, sha) == 412


async def test_github_import_stops_on_rate_limit_and_marks_partial():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.url.path.endswith("/pulls"):
            page = request.url.params.get("page")
            if page == "1":
                return httpx.Response(200, json=[{"number": 7, "merged_at": "2026-01-01T00:00:00Z"}])
            return httpx.Response(200, json=[])
        if request.url.path.endswith("/7/comments"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "path": "a.py",
                        "line": 3,
                        "body": "Missing idempotency check",
                        "user": {"login": "rev"},
                        "created_at": "2026-01-02T00:00:00Z",
                    }
                ],
            )
        return httpx.Response(403, json={"message": "API rate limit exceeded"})

    store = MemoryStore("h5")
    http = httpx.AsyncClient(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
    count = await import_github_reviews(store, "o", "r", http=http)
    assert count == 1
    assert store.get_meta("reviews_partial") == "1"
    row = store.one("SELECT pr_number, path, body FROM review_comments")
    assert (row["pr_number"], row["path"]) == (7, "a.py")


async def test_precedents_indexed_from_fix_commits(git_repo):
    repo = _cochange_repo(git_repo)
    store = MemoryStore("h6")
    import_history(store, repo, max_commits=100)
    assert await index_precedents(store, FakeRuntime()) == 1
    assert await index_precedents(store, FakeRuntime()) == 0  # incremental


def test_tooling_chores_are_not_bug_fixes():
    from repopilot.memory.history import is_fix

    assert is_fix("fix: crash on empty input")
    assert is_fix("Fix teardown when an exception is raised")
    assert not is_fix("fix pyright type errors")
    assert not is_fix("fix typo in docs")
    assert not is_fix("Fix mypy findings")
