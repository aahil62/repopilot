import json
import time

from fastapi.testclient import TestClient

from repopilot.api.jobs import reset_jobs
from repopilot.api.main import create_app
from repopilot.runtime import FakeRuntime, set_runtime

FILES = {
    "auth.py": "def login_user(username, password):\n    return create_session(username)\n\n\ndef create_session(name):\n    return {'user': name}\n",
    "views.py": "from auth import login_user\n\n\ndef login_view(request):\n    return login_user(request.user, request.password)\n",
}
REVIEW = json.dumps(
    {
        "summary": "Session payload changed.",
        "findings": [
            {
                "severity": "medium",
                "path": "auth.py",
                "line": 6,
                "title": "Session drops the user key",
                "explanation": "Callers read 'user'.",
            }
        ],
    }
)


def _wait(client, job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _sse(text):
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_end_to_end_with_fake_runtime(git_repo, tmp_path):
    reset_jobs()
    repo = git_repo(
        [("init", FILES), ("fix: login crash when password empty", {"auth.py": FILES["auth.py"] + "\n"})]
    )
    set_runtime(
        FakeRuntime(
            {
                "strong": [
                    lambda m: (
                        REVIEW
                        if "BEHAVIOR HUNKS" in m[-1]["content"]
                        else "Login is handled by `login_user` [1]."
                    )
                ]
            }
        )
    )
    with TestClient(create_app(static_dir=None)) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        repo_id = client.post("/api/repos", json={"path": str(repo)}).json()["repo_id"]

        job = _wait(client, client.post(f"/api/repos/{repo_id}/index", json={}).json()["job_id"])
        assert job["status"] == "done", job
        summary = client.get(f"/api/repos/{repo_id}").json()
        assert summary["files"] == 2 and summary["commits"] == 2

        files = client.get(f"/api/repos/{repo_id}/files", params={"q": "auth"}).json()
        assert files[0]["path"] == "auth.py"
        assert client.get(f"/api/repos/{repo_id}/file", params={"path": "../etc/passwd"}).status_code == 404

        events = _sse(
            client.post(f"/api/repos/{repo_id}/ask", json={"question": "Where is login_user handled?"}).text
        )
        kinds = [e for e, _ in events]
        assert kinds[0] == "retrieval" and kinds[-1] == "done" and "citations" in kinds
        assert dict(events)["citations"][0]["path"] in {"auth.py", "views.py"}

        blast = client.get(f"/api/repos/{repo_id}/blast", params={"path": "auth.py"}).json()
        assert blast["dependents"][0]["path"] == "views.py"

        (repo / "auth.py").write_text(FILES["auth.py"].replace("{'user': name}", "{'name': name}"))
        job = _wait(
            client, client.post(f"/api/repos/{repo_id}/review", json={"run_checks": False}).json()["job_id"]
        )
        assert job["status"] == "done", job
        report = job["result"]
        assert report["findings"][0]["title"] == "Session drops the user key"
        assert client.get(f"/api/repos/{repo_id}/reviews/{report['review_id']}").status_code == 200
        assert client.get(f"/api/repos/{repo_id}/reviews").json()[0]["review_id"] == report["review_id"]

        assert client.post("/api/repos", json={"path": str(tmp_path)}).status_code == 400
        assert client.get("/api/privacy").json()["telemetry"] is False


def test_static_web_ui_served_with_fallback(tmp_path):
    static = tmp_path / "static"
    (static / "review").mkdir(parents=True)
    (static / "index.html").write_text("<h1>home</h1>")
    (static / "review" / "index.html").write_text("<h1>review</h1>")
    with TestClient(create_app(static_dir=static)) as client:
        assert "review" in client.get("/review").text
        assert "home" in client.get("/unknown/page").text
        assert client.get("/api/nope").status_code == 404


def test_index_and_review_work_without_a_model_runtime(git_repo, monkeypatch):
    from repopilot.config import reset_settings

    monkeypatch.setenv("REPOPILOT_RUNTIME_URLS", '["http://127.0.0.1:9"]')
    reset_settings()
    reset_jobs()
    repo = git_repo(
        [("init", FILES), ("fix: login crash when password empty", {"auth.py": FILES["auth.py"] + "\n"})]
    )
    with TestClient(create_app(static_dir=None)) as client:
        repo_id = client.post("/api/repos", json={"path": str(repo)}).json()["repo_id"]
        job = _wait(client, client.post(f"/api/repos/{repo_id}/index", json={}).json()["job_id"])
        assert job["status"] == "done", job
        assert any("semantic search is off" in n for n in job["result"]["notes"])
        assert client.get(f"/api/repos/{repo_id}/blast", params={"path": "auth.py"}).json()["dependents"]

        (repo / "auth.py").write_text(FILES["auth.py"].replace("{'user': name}", "{'name': name}"))
        job = _wait(
            client, client.post(f"/api/repos/{repo_id}/review", json={"run_checks": False}).json()["job_id"]
        )
        report = job["result"]
        assert job["status"] == "done" and report["behavior_count"] == 1
        assert report["model_error"].startswith("No local model runtime")
        assert client.post(f"/api/repos/{repo_id}/ask", json={"question": "x"}).status_code == 503
