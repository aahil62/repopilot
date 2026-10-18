from repopilot.engines.blast import blast_radius, is_test_file
from repopilot.memory.codegraph import build_graph
from repopilot.memory.history import import_history
from repopilot.memory.indexer import index_code
from repopilot.memory.store import MemoryStore
from repopilot.runtime import FakeRuntime


async def _prepare(repo, rid):
    store = MemoryStore.open(rid)
    await index_code(store, repo, FakeRuntime())
    build_graph(store)
    import_history(store, repo, 1000)
    return store


async def test_low_risk_for_isolated_file(git_repo):
    repo = git_repo([("init", {"lonely.py": "def x():\n    return 1\n", "other.py": "y = 1\n"})])
    await _prepare(repo, "b1")
    report = blast_radius("b1", ["lonely.py"])
    assert report.risk == "low" and report.dependents == [] and report.past_fixes == []


async def test_medium_risk_from_coupled_file_missing_from_change(git_repo):
    commits = [("init", {"auth.py": "a0\n", "session.py": "s0\n"})]
    commits += [(f"update auth {i}", {"auth.py": f"a{i}\n", "session.py": f"s{i}\n"}) for i in range(1, 5)]
    commits += [("tweak auth", {"auth.py": "a5\n"})]
    repo = git_repo(commits)
    await _prepare(repo, "b2")
    report = blast_radius("b2", ["auth.py"])
    assert report.cochanged[0].path == "session.py"
    assert report.cochanged[0].confidence == round(5 / 6, 3)
    assert report.risk == "medium"
    assert any(
        "usually changes together with `session.py` (83% of the time)" in r for r in report.risk_reasons
    )
    assert report.owners[0].author == "Dev One"


async def test_repeated_fixes_alone_are_medium(git_repo):
    commits = [("init", {"pay.py": "p0\n"})]
    commits += [(f"fix: payment rounding bug {i}", {"pay.py": f"p{i}\n"}) for i in range(1, 4)]
    repo = git_repo(commits)
    await _prepare(repo, "b3")
    report = blast_radius("b3", ["pay.py"])
    assert report.risk == "medium"
    assert len(report.past_fixes) == 3
    assert report.risk_reasons[0].startswith("3 bug fixes")


async def test_central_file_with_recent_fixes_is_high_and_tests_found(git_repo):
    files = {"core.py": "def base():\n    return 1\n"}
    for i in range(10):
        files[f"m{i}.py"] = "from core import base\n"
    files["tests/test_core.py"] = "from core import base\n\ndef test_base():\n    assert base() == 1\n"
    commits = [("init", files)]
    commits += [
        (f"fix: base off by one {i}", {"core.py": f"def base():\n    return {i}\n"}) for i in range(2, 5)
    ]
    repo = git_repo(commits)
    await _prepare(repo, "b4")
    report = blast_radius("b4", ["core.py"])
    assert report.risk == "high"
    assert len(report.dependents) == 11
    assert report.tests == ["tests/test_core.py"]
    assert any(r.startswith("Among the most imported files") for r in report.risk_reasons)


async def test_central_file_without_fixes_is_medium(git_repo):
    files = {"core.py": "def base():\n    return 1\n", "other.py": "x = 1\n"}
    for i in range(10):
        files[f"m{i}.py"] = "from core import base\n"
    repo = git_repo([("init", files)])
    await _prepare(repo, "b5")
    assert blast_radius("b5", ["core.py"]).risk == "medium"


def test_is_test_file_patterns():
    assert (
        is_test_file("tests/test_app.py") and is_test_file("src/a.test.ts") and is_test_file("pkg/x_test.go")
    )
    assert not is_test_file("src/contest.py")


async def test_owners_grouped_by_email(git_repo, git):
    repo = git_repo([("init", {"a.py": "1\n"})], author="Dana Lee")
    for i, name in enumerate(["Dana Lee", "Dana", "Dana Lee"]):
        (repo / "a.py").write_text(f"{i + 2}\n")
        git(
            repo,
            "-c",
            f"user.name={name}",
            "-c",
            "user.email=dana@example.com",
            "commit",
            "-qam",
            f"change {i}",
        )
    await _prepare(repo, "b6")
    owners = blast_radius("b6", ["a.py"]).owners
    assert [(o.author, o.commits) for o in owners] == [("Dana Lee", 4)]
