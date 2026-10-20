import json
import subprocess
import sys

from repopilot.engines.nightshift import list_reports, run_nightshift, schedule
from repopilot.memory.registry import add_local
from repopilot.runtime import FakeRuntime

TOML = f'[checks]\ntest = "{sys.executable} -m pytest -q -x -p no:cacheprovider"\n'
NO_FINDINGS = json.dumps({"summary": "Looks fine.", "findings": []})


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _runtime(*edit_responses):
    def strong(messages):
        if "edits" in json.dumps(messages[0]) or "Write focused unit tests" in messages[-1]["content"]:
            return edit_responses[0] if edit_responses else NO_FINDINGS
        return NO_FINDINGS

    return FakeRuntime({"strong": [strong]})


async def test_first_run_reviews_last_ten_then_only_new(git_repo):
    commits = [("init", {"a.py": "x = 0\n", "repopilot.toml": TOML})]
    commits += [(f"change {i}", {"a.py": f"x = {i}\n"}) for i in range(1, 12)]
    repo = git_repo(commits)
    record = add_local(repo)
    first = await run_nightshift(record, _runtime(), write_tests=False, today="2026-02-01")
    assert len(first.commits_reviewed) == 10
    assert first.commits_reviewed[-1].subject == "change 11"

    (repo / "a.py").write_text("x = 99\n")
    _git(repo, "commit", "-qam", "change 12")
    second = await run_nightshift(record, _runtime(), write_tests=False, today="2026-02-02")
    assert [c.subject for c in second.commits_reviewed] == ["change 12"]
    assert [r["date"] for r in list_reports(record.repo_id)] == ["2026-02-02", "2026-02-01"]


async def test_writes_verified_test_on_branch_without_touching_current_branch(git_repo):
    src = "def slugify(text):\n    return text.lower().replace(' ', '-')\n"
    repo = git_repo(
        [
            (
                "init",
                {
                    "tests/__init__.py": "",
                    "tests/test_other.py": "def test_ok():\n    assert True\n",
                    "repopilot.toml": TOML,
                },
            ),
            ("add slugify", {"text_utils.py": src}),
        ]
    )
    head_before = _git(repo, "rev-parse", "HEAD")
    test_file = "from text_utils import slugify\n\n\ndef test_slugify():\n    assert slugify('Hello World') == 'hello-world'\n"
    proposal = json.dumps(
        {
            "explanation": "Add tests.",
            "edits": [{"path": "tests/test_text_utils.py", "search": "", "replace": test_file}],
        }
    )
    report = await run_nightshift(add_local(repo), _runtime(proposal), today="2026-02-03")
    written = [t for t in report.tests_written if t.symbol == "slugify"][0]
    assert written.status == "verified" and written.branch == "repopilot/nightshift-2026-02-03"
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert _git(repo, "branch", "--show-current") == "main"
    assert "test_slugify" in _git(repo, "show", "repopilot/nightshift-2026-02-03:tests/test_text_utils.py")
    assert not (repo / "tests" / "test_text_utils.py").exists()


async def test_stale_docs_lists_removed_symbol(git_repo):
    repo = git_repo(
        [
            (
                "init",
                {
                    "api.py": "def fetch_user(uid):\n    return uid\n",
                    "README.md": "# API\nCall `fetch_user(id)` to load a user.\n",
                },
            ),
            ("rename fetch_user to load_user", {"api.py": "def load_user(uid):\n    return uid\n"}),
        ]
    )
    report = await run_nightshift(add_local(repo), _runtime(), write_tests=False, today="2026-02-04")
    assert [(d.doc_path, d.line, d.symbol) for d in report.stale_docs] == [("README.md", 2, "fetch_user")]


def test_schedule_macos_plist(tmp_path):
    info = schedule(tmp_path, "02:00", system="Darwin")
    assert info["kind"] == "launchd"
    assert str(tmp_path.resolve()) in info["content"]
    assert "<key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer>" in info["content"]
    assert info["activate"].startswith("launchctl load")
    assert schedule(tmp_path, "03:30", system="Linux")["content"].startswith("30 3 * * *")


async def test_skips_test_writing_when_the_suite_already_fails(git_repo):
    repo = git_repo(
        [
            (
                "init",
                {"tests/test_other.py": "def test_broken():\n    assert False\n", "repopilot.toml": TOML},
            ),
            ("add slugify", {"text_utils.py": "def slugify(text):\n    return text.lower()\n"}),
        ]
    )
    fake = _runtime(
        json.dumps({"explanation": "x", "edits": [{"path": "t.py", "search": "", "replace": "x"}]})
    )
    report = await run_nightshift(add_local(repo), fake, today="2026-02-04")
    assert report.tests_written == []
    assert any("already fail" in n for n in report.notes)
    assert not any("Write focused unit tests" in c["messages"][-1]["content"] for c in fake.calls)


def test_new_tests_go_to_their_own_file_when_the_usual_one_is_long(tmp_path):
    from repopilot.engines.nightshift import _test_path_for

    (tmp_path / "tests").mkdir()
    assert _test_path_for(tmp_path, "src/pkg/helpers.py", "get_root") == "tests/test_helpers.py"
    (tmp_path / "tests" / "test_helpers.py").write_text("def test_x():\n    pass\n" * 200)
    assert _test_path_for(tmp_path, "src/pkg/helpers.py", "get_root") == "tests/test_helpers_get_root.py"
