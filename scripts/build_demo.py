"""Build the public demo's data by running RepoPilot on pallets/flask at a pinned tag.

Every file written to web/public/demo/ is real RepoPilot output — nothing is hand-written.

    backend/.venv/bin/python scripts/build_demo.py             # needs a local model runtime
    backend/.venv/bin/python scripts/build_demo.py --offline   # no model: deterministic parts only

--offline uses hash-based embeddings and skips everything a language model produces (findings,
answers, night-shift tests, benchmark). Those files are left untouched so a later full run can add them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from repopilot.engines.ask import ask_stream, calibrate_refusal  # noqa: E402
from repopilot.engines.bench import run_bench  # noqa: E402
from repopilot.engines.blast import blast_radius  # noqa: E402
from repopilot.engines.diffparse import DiffSource, commit_diff  # noqa: E402
from repopilot.engines.nightshift import run_nightshift  # noqa: E402
from repopilot.engines.review import review  # noqa: E402
from repopilot.memory import registry  # noqa: E402
from repopilot.memory.pipeline import index_repo, repo_summary  # noqa: E402
from repopilot.memory.store import MemoryStore  # noqa: E402
from repopilot.runtime import FakeRuntime, get_runtime, scan  # noqa: E402

OUT = ROOT / "web" / "public" / "demo"
REPO_URL = "https://github.com/pallets/flask"
TAG = "3.1.0"
BLAST_FILES = [
    "src/flask/app.py", "src/flask/ctx.py", "src/flask/sansio/app.py", "src/flask/blueprints.py", "src/flask/helpers.py",
    "src/flask/json/provider.py", "src/flask/wrappers.py", "src/flask/testing.py", "src/flask/cli.py", "src/flask/config.py",
    "src/flask/sessions.py", "src/flask/templating.py",
]
QUESTIONS = ["Where is the request context pushed?", "Why does Flask's teardown run even when an exception happened?"]


def write(name: str, data) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=1, default=str))
    print(f"  wrote demo/{name}.json")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


async def pick_hero(record, runtime, use_model: bool):
    """The commit with the most code-level mechanical hunks and at most two behavior hunks."""
    repo = Path(record.path)
    store = MemoryStore.open(record.repo_id)
    best = None
    for row in store.query("SELECT sha, subject FROM commits ORDER BY seq DESC LIMIT 1500"):
        files = [r["path"] for r in store.query("SELECT path FROM commit_files WHERE sha=?", (row["sha"],))]
        src = [f for f in files if f.startswith("src/flask/") and f.endswith(".py")]
        if not (1 <= len(src) <= 6) or len(files) > 10:
            continue
        diff = commit_diff(repo, row["sha"])
        if len(diff) > 40_000:
            continue
        report = await review(record.repo_id, repo, diff, runtime, source=DiffSource("commit", head=row["sha"]),
                              run_checks_enabled=False, use_model=False, persist=False)
        behavior = [h for f in report.files for h in f.hunks if h.label == "behavior"]
        code_mech = [h for f in report.files if f.path.endswith(".py") for h in f.hunks if h.label == "mechanical"]
        if 1 <= len(behavior) <= 2 and all(len(h.text.splitlines()) <= 28 for h in behavior):
            if best is None or len(code_mech) > best[0]:
                best = (len(code_mech), row, diff, report)
    if best is None:
        raise SystemExit("No suitable hero commit found.")
    _, row, diff, report = best
    if use_model:
        report = await review(record.repo_id, repo, diff, runtime, source=DiffSource("commit", head=row["sha"]),
                              run_checks_enabled=False, persist=False)
    return row, report


async def main(offline: bool) -> None:
    record = registry.add_clone(REPO_URL)
    repo = Path(record.path)
    git(repo, "fetch", "--tags", "--quiet")
    git(repo, "checkout", "--quiet", "--detach", TAG)
    runtime = FakeRuntime() if offline else await get_runtime()
    print(f"Indexing {record.name} at {TAG} ({'offline' if offline else 'with ' + runtime.roles['strong'].id})")
    await index_repo(record, runtime)
    store = MemoryStore.open(record.repo_id)
    await calibrate_refusal(store, runtime)

    summary = repo_summary(record)
    summary.update({"path": f"pallets/flask @ {TAG}", "name": "pallets/flask"})
    write("repos", [summary])

    blasts = {p: blast_radius(record.repo_id, [p]).model_dump() for p in BLAST_FILES if (repo / p).exists()}
    write("blast", blasts)
    lines = {r["path"]: r for r in store.query("SELECT path, language, lines FROM files")}
    write("files", [dict(lines[p]) for p in blasts])

    row, report = await pick_hero(record, runtime, use_model=not offline)
    report_data = report.model_dump()
    write("hero", {"repo": "pallets/flask", "commit": row["sha"], "subject": row["subject"], "files": report_data["files"],
                   "mechanical": report.mechanical_count, "behavior": report.behavior_count, "blast": report_data["blast"],
                   "model": None if offline else report.model})
    write("review", {**report_data, "review_id": "flask-demo"})
    write("reviews", [{"review_id": "flask-demo", "created_at": report.created_at, "source": report.source,
                       "summary": report.summary, "behavior": report.behavior_count, "mechanical": report.mechanical_count}])
    if offline:
        print("Offline run: skipped ask, night shift, benchmark and models (they need a language model).")
        return

    transcripts, excerpts = [], {}
    for q in QUESTIONS:
        events = [e async for e in ask_stream(store, runtime, q)]
        transcripts.append({"question": q, "events": events})
        for e in events:
            if e["event"] == "citations":
                for c in e["data"]:
                    text = (repo / c["path"]).read_text().splitlines()
                    start, end = max(1, c["start_line"] - 12), min(len(text), c["end_line"] + 12)
                    excerpts[c["path"]] = {"path": c["path"], "start": start, "end": end, "total_lines": len(text),
                                           "lines": text[start - 1 : end]}
    write("ask", transcripts)
    write("file-excerpts", excerpts)

    head_before = git(repo, "rev-parse", "HEAD")
    night = await run_nightshift(record, runtime, max_commits=5, today="2024-11-13")
    assert git(repo, "rev-parse", "HEAD") == head_before, "night shift must not move HEAD"
    write("nightshift", night.model_dump())
    write("nightshift-list", [{"date": night.date, "commits": len(night.commits_reviewed),
                               "findings": sum(len(c.findings) for c in night.commits_reviewed),
                               "tests_verified": sum(t.status == "verified" for t in night.tests_written),
                               "stale_docs": len(night.stale_docs)}])

    models, statuses, hw = await scan()
    bench = await run_bench(record.repo_id, repo, models, hw, n_tasks=6, embed_model=runtime.roles["embed"])
    write("bench", bench.model_dump())
    write("models", {"runtimes": [s.__dict__ for s in statuses],
                     "models": [{**m.to_dict(), "fits": m.size_bytes is None or m.size_bytes <= hw.model_budget_bytes} for m in models],
                     "roles": {k: v.id for k, v in runtime.roles.items()}, "hardware": hw.to_dict()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="No language model: deterministic outputs only.")
    asyncio.run(main(parser.parse_args().offline))
