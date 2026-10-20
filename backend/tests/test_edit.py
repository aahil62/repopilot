import json
import sys

import pytest

from repopilot.engines.edit import ApplyConflict, apply_edits, apply_to_working_tree, verified_edit
from repopilot.memory.indexer import index_code
from repopilot.memory.store import MemoryStore
from repopilot.runtime import FakeRuntime

SRC = "def discount(price, rate):\n    return price * (1 - rate)\n"
TEST = (
    "import pytest\nfrom shop import discount\n\n\ndef test_discount():\n    assert discount(100, 0.25) == 75\n\n\n"
    "def test_rejects_negative_rate():\n    with pytest.raises(ValueError):\n        discount(100, -0.5)\n"
)


def _proposal(search: str, replace: str, path: str = "shop.py") -> str:
    return json.dumps(
        {"explanation": "Validate the rate.", "edits": [{"path": path, "search": search, "replace": replace}]}
    )


BAD_SEARCH = _proposal("def discount(price, percent):", "x")
WRONG_FIX = _proposal(
    "    return price * (1 - rate)",
    "    if rate > 1:\n        raise ValueError('rate')\n    return price * (1 - rate)",
)
GOOD_FIX = _proposal(
    "    return price * (1 - rate)",
    "    if not 0 <= rate <= 1:\n        raise ValueError('rate')\n    return price * (1 - rate)",
)


async def _repo(git_repo, rid):
    toml = f'[checks]\ntest = "{sys.executable} -m pytest -q -x -p no:cacheprovider"\n'
    repo = git_repo([("init", {"shop.py": SRC, "test_shop.py": TEST, "repopilot.toml": toml})])
    await index_code(MemoryStore.open(rid), repo, FakeRuntime())
    return repo


async def test_retries_until_checks_pass(git_repo):
    repo = await _repo(git_repo, "e1")
    fake = FakeRuntime({"strong": [BAD_SEARCH, WRONG_FIX, GOOD_FIX]})
    result = await verified_edit("e1", repo, fake, "Reject negative discount rates", ["shop.py"])
    assert result.status == "verified"
    assert [a.applied for a in result.attempts] == [False, True, True]
    assert "not found" in result.attempts[0].apply_error
    assert result.attempts[1].checks.status == "failed"
    assert "+    if not 0 <= rate <= 1:" in result.diff
    assert "checks failed" in fake.calls[2]["messages"][-1]["content"]
    assert (repo / "shop.py").read_text() == SRC  # working tree untouched until apply

    apply_to_working_tree(repo, result)
    assert "if not 0 <= rate <= 1" in (repo / "shop.py").read_text()


async def test_all_attempts_fail_leaves_tree_untouched(git_repo):
    repo = await _repo(git_repo, "e2")
    fake = FakeRuntime({"strong": [WRONG_FIX]})
    result = await verified_edit("e2", repo, fake, "Reject negative discount rates", ["shop.py"])
    assert result.status == "failed" and len(result.attempts) == 3
    assert (repo / "shop.py").read_text() == SRC
    with pytest.raises(ValueError):
        apply_to_working_tree(repo, result)


async def test_apply_conflict_when_file_changed_meanwhile(git_repo):
    repo = await _repo(git_repo, "e3")
    result = await verified_edit(
        "e3", repo, FakeRuntime({"strong": [GOOD_FIX]}), "Reject negative rates", ["shop.py"]
    )
    (repo / "shop.py").write_text(SRC + "\n# edited by hand\n")
    with pytest.raises(ApplyConflict):
        apply_to_working_tree(repo, result)


def test_apply_edits_tolerates_indentation_drift_and_creates_files(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    assert apply_edits(tmp_path, [_block("a.py", "def f():\n  return 1", "def f():\n    return 2")]) is None
    assert (tmp_path / "a.py").read_text() == "def f():\n    return 2\n"
    assert apply_edits(tmp_path, [_block("new/b.py", "", "x = 1")]) is None
    assert (tmp_path / "new" / "b.py").read_text() == "x = 1\n"
    assert "outside" in apply_edits(tmp_path, [_block("../evil.py", "", "x")])


def _block(path, search, replace):
    from repopilot.engines.edit import EditBlock

    return EditBlock(path=path, search=search, replace=replace)


def test_no_op_edits_are_rejected_with_feedback(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    error = apply_edits(tmp_path, [_block("a.py", "x = 1", "x = 1")])
    assert error and "identical code" in error
