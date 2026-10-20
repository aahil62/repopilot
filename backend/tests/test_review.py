import json
import sys

import pytest

from repopilot.config import get_settings
from repopilot.engines.checks import detect_test_command, run_checks
from repopilot.engines.classify import classify_hunk, identifiers, python_same_tree
from repopilot.engines.diffparse import diff_for, parse
from repopilot.engines.review import load_review, review
from repopilot.memory.codegraph import build_graph
from repopilot.memory.history import import_history
from repopilot.memory.indexer import index_code
from repopilot.memory.store import MemoryStore
from repopilot.runtime import FakeRuntime
from repopilot.worktree import temp_worktree


def _hunk(diff: str, old: str | None = None, new: str | None = None):
    fd = parse(diff)[0]
    if old is None:  # the old file is exactly the removed lines
        old = "\n".join(fd.hunks[0].removed) + "\n"
    return classify_hunk(
        fd, fd.hunks[0], old_idents=identifiers(old), new_idents=identifiers(new), old_text=old
    )[0]


def _diff(path: str, removed: list[str], added: list[str]) -> str:
    body = "".join(f"-{r}\n" for r in removed) + "".join(f"+{a}\n" for a in added)
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,{len(removed)} +1,{len(added)} @@\n{body}"


def test_classify_mechanical_cases():
    assert _hunk(_diff("a.py", ["x = f(a,b)"], ["x = f(a, b)"])) == "mechanical"
    assert _hunk(_diff("a.py", ["# old note"], ["# new note"])) == "mechanical"
    assert _hunk(_diff("a.py", ["import os", "import sys"], ["import sys", "import os"])) == "mechanical"
    old = "def load(path):\n    return open(path)\n"
    new = "def load(filename):\n    return open(filename)\n"
    assert (
        _hunk(
            _diff(
                "a.py",
                ["def load(path):", "    return open(path)"],
                ["def load(filename):", "    return open(filename)"],
            ),
            old,
            new,
        )
        == "mechanical"
    )


def test_classify_python_semantics():
    # annotations and docstrings only
    assert (
        _hunk(_diff("a.py", ["def f(x):", "    return x"], ["def f(x: int) -> int:", "    return x"]))
        == "mechanical"
    )
    # dedenting an assert out of a with-block changes behavior
    old = "with ctx:\n    run()\n    assert ok\n"
    assert (
        _hunk(
            _diff("a.py", ["    assert ok"], ["assert ok"]).replace("@@ -1,1 +1,1 @@", "@@ -3,1 +3,1 @@"), old
        )
        == "behavior"
    )
    # swapping an imported decorator is not a rename
    old = "from h import locked_cached_property\n\n@locked_cached_property\ndef v(self):\n    return 1\n"
    diff = "--- a/a.py\n+++ b/a.py\n@@ -3,1 +3,1 @@\n-@locked_cached_property\n+@cached_property\n"
    assert _hunk(diff, old, old.replace("@locked_cached_property", "@cached_property")) == "behavior"


def test_classify_behavior_cases():
    assert _hunk(_diff("a.py", ["if x > 0:"], ["if x >= 0:"])) == "behavior"
    old = "total = 1\nsubtotal = 2\nreturn total\n"
    new = "total = 1\nsubtotal = 2\nreturn subtotal\n"
    assert _hunk(_diff("a.py", ["return total"], ["return subtotal"]), old, new) == "behavior"


def test_black_style_reformat_has_same_tree():
    assert python_same_tree("x = {'a':1,\n'b':2}\n", 'x = {"a": 1, "b": 2}\n')
    assert not python_same_tree("x = 1\n", "x = 2\n")


SRC = "def discount(price, rate):\n    if rate > 1:\n        raise ValueError('rate')\n    return price * (1 - rate)\n"
TEST = "from shop import discount\n\n\ndef test_discount():\n    assert discount(100, 0.25) == 75\n"


def _repo_with_tests(git_repo):
    toml = f'[checks]\ntest = "{sys.executable} -m pytest -q -x -p no:cacheprovider"\n'
    return git_repo(
        [
            ("add shop", {"shop.py": SRC, "test_shop.py": TEST, "repopilot.toml": toml}),
            (
                "fix: reject negative rates",
                {"shop.py": SRC.replace("if rate > 1:", "if rate > 1 or rate < 0:")},
            ),
        ]
    )


async def _prepare(repo, rid):
    store = MemoryStore.open(rid)
    fake = FakeRuntime()
    await index_code(store, repo, fake)
    build_graph(store)
    import_history(store, repo, 100)
    return store


async def test_review_keeps_verified_finding_and_drops_hallucinated(git_repo):
    repo = _repo_with_tests(git_repo)
    await _prepare(repo, "r1")
    (repo / "shop.py").write_text(SRC.replace("1 - rate", "1 + rate"))
    diff, source = diff_for(repo)
    model_out = json.dumps(
        {
            "summary": "Discount now increases the price.",
            "findings": [
                {
                    "severity": "high",
                    "path": "shop.py",
                    "line": 4,
                    "title": "Discount adds instead of subtracting",
                    "explanation": "price * (1 + rate) raises the price.",
                    "evidence": ["deadbeef"],
                },
                {
                    "severity": "medium",
                    "path": "billing/invoice.py",
                    "line": 88,
                    "title": "Invented file",
                    "explanation": "Not in the diff.",
                    "evidence": [],
                },
            ],
        }
    )
    fake = FakeRuntime({"strong": [model_out]})
    report = await review("r1", repo, diff, fake, source=source)
    assert report.behavior_count == 1 and report.mechanical_count == 0
    assert [f.title for f in report.findings] == ["Discount adds instead of subtracting"]
    assert report.findings[0].evidence == []  # invented ref removed
    assert report.dropped_unverifiable == 1
    assert report.checks.status == "failed" and "assert" in report.checks.output_tail
    assert report.blast and report.blast.past_fixes[0].subject == "fix: reject negative rates"
    assert "HISTORY" in fake.calls[0]["messages"][1]["content"]
    assert load_review("r1", report.review_id).summary == report.summary
    assert (repo / "shop.py").read_text().count("1 + rate") == 1  # user's working tree untouched


async def test_review_of_mechanical_only_change_skips_model_and_checks(git_repo):
    repo = _repo_with_tests(git_repo)
    await _prepare(repo, "r2")
    (repo / "shop.py").write_text(
        SRC.replace("(price, rate)", "(price,rate)").replace("if rate > 1:", "if rate > 1 or rate < 0:")
    )
    diff, source = diff_for(repo)
    fake = FakeRuntime()
    report = await review("r2", repo, diff, fake, source=source)
    assert report.behavior_count == 0 and report.findings == []
    assert report.checks.status == "skipped" and fake.calls == []


async def test_repo_without_tests_reports_skipped_checks(git_repo):
    repo = git_repo([("init", {"app.py": "def f(x):\n    return x\n"})])
    await _prepare(repo, "r3")
    (repo / "app.py").write_text("def f(x):\n    return x * 2\n")
    diff, source = diff_for(repo)
    report = await review(
        "r3",
        repo,
        diff,
        FakeRuntime({"strong": ['{"summary": "Doubles x.", "findings": []}']}),
        source=source,
    )
    assert report.checks.status == "skipped"
    assert report.checks.message.startswith("No test command detected")


async def test_invalid_model_output_reported_not_raised(git_repo):
    repo = git_repo([("init", {"app.py": "def f(x):\n    return x\n"})])
    await _prepare(repo, "r4")
    (repo / "app.py").write_text("def f(x):\n    return -x\n")
    diff, source = diff_for(repo)
    report = await review(
        "r4", repo, diff, FakeRuntime({"strong": ["nonsense"]}), source=source, run_checks_enabled=False
    )
    assert report.model_error and report.findings == []


def test_untracked_files_included_in_working_diff(git_repo):
    repo = git_repo([("init", {"a.py": "x = 1\n"})])
    (repo / "new.py").write_text("y = 2\n")
    diff, _ = diff_for(repo)
    assert {f.path for f in parse(diff)} == {"new.py"}


def test_detect_test_command_variants(git_repo):
    repo = git_repo([("init", {"package.json": json.dumps({"scripts": {"test": "vitest run"}})})], name="js")
    assert detect_test_command(repo) == "npm test --silent"
    bare = git_repo([("init", {"README.md": "hi\n"})], name="bare")
    assert detect_test_command(bare) is None


def test_worktree_removed_after_exception(git_repo):
    repo = git_repo([("init", {"a.py": "x = 1\n"})])
    with pytest.raises(RuntimeError), temp_worktree(repo) as tree:
        assert (tree / "a.py").exists()
        raise RuntimeError("boom")
    assert not any(get_settings().worktrees_dir.iterdir())


def test_run_checks_passes_on_clean_head(git_repo):
    repo = _repo_with_tests(git_repo)
    assert run_checks(repo).status == "passed"


async def test_markdown_report_and_fail_gate(git_repo):
    from repopilot.engines.review import report_markdown, should_fail

    repo = _repo_with_tests(git_repo)
    await _prepare(repo, "r5")
    (repo / "shop.py").write_text(SRC.replace("1 - rate", "1 + rate"))
    diff, source = diff_for(repo)
    finding = json.dumps(
        {
            "summary": "Discount raises prices.",
            "findings": [
                {
                    "severity": "medium",
                    "path": "shop.py",
                    "line": 4,
                    "title": "Sign flipped",
                    "explanation": "Adds the rate.",
                }
            ],
        }
    )
    report = await review("r5", repo, diff, FakeRuntime({"strong": [finding]}), source=source)
    md = report_markdown(report)
    assert md.startswith("## RepoPilot review") and "**1 of 1 hunks change behavior.**" in md
    assert "`shop.py:4` Sign flipped" in md and "### Checks: failed" in md
    assert should_fail(report, "high")  # failing tests fail any gate
    assert not should_fail(report, "never")


def test_hook_install_and_uninstall(git_repo):
    from typer.testing import CliRunner

    from repopilot.cli import app

    repo = git_repo([("init", {"a.py": "x = 1\n"})])
    runner = CliRunner()
    assert runner.invoke(app, ["hook", "install", "--repo", str(repo)]).exit_code == 0
    hook = repo / ".git" / "hooks" / "pre-push"
    assert "repopilot review --base" in hook.read_text() and hook.stat().st_mode & 0o100
    assert runner.invoke(app, ["hook", "uninstall", "--repo", str(repo)]).exit_code == 0
    assert not hook.exists()
    hook.write_text("#!/bin/sh\necho mine\n")
    assert (
        runner.invoke(app, ["hook", "install", "--repo", str(repo)]).exit_code == 2
    )  # never overwrite a user's hook
