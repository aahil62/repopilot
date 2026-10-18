"""Evaluate RepoPilot on a pinned open-source repository.

    backend/.venv/bin/python eval/run_eval.py                      # real local models (Ollama/LM Studio)
    backend/.venv/bin/python eval/run_eval.py --offline            # no model: keyword retrieval only

Measures
- retrieval Recall@5 of gold files: vector-only, keyword-only and hybrid (RRF)
- refusal accuracy on questions the repository cannot answer
- share of hunks set aside as mechanical across recent commits (descriptive)
- review citation validity: share of model findings that survive line verification (needs a model)
- model benchmark on replayed commits (needs a model)

Writes eval/results/<dataset>-latest.{json,md}; with real models also web/public/demo/eval.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from repopilot.engines.ask import calibrate_refusal, lexical_search, retrieve, rrf  # noqa: E402
from repopilot.engines.bench import run_bench  # noqa: E402
from repopilot.engines.diffparse import DiffSource, commit_diff  # noqa: E402
from repopilot.engines.review import review  # noqa: E402
from repopilot.memory import registry  # noqa: E402
from repopilot.memory.indexer import CODE_COLLECTION  # noqa: E402
from repopilot.memory.pipeline import index_repo  # noqa: E402
from repopilot.memory.store import MemoryStore  # noqa: E402
from repopilot.runtime import FakeRuntime, get_runtime, scan  # noqa: E402

K = 5


def top_files(store: MemoryStore, chunk_ids: list[str], k: int = K) -> list[str]:
    files: list[str] = []
    for cid in chunk_ids:
        row = store.one("SELECT path FROM chunks WHERE chunk_id=?", (cid,))
        if row and row["path"] not in files:
            files.append(row["path"])
        if len(files) == k:
            break
    return files


async def retrieval(store, runtime, questions, use_vectors: bool) -> dict:
    hits = {"vector": 0, "keyword": 0, "hybrid": 0}
    per_question = []
    for item in questions:
        lexical = lexical_search(store, item["q"], k=30)
        vector = []
        if use_vectors:
            [vec] = await runtime.embed([item["q"]])
            vector = [key for key, _ in store.search(CODE_COLLECTION, vec, k=30)]
        hybrid = [key for key, _ in rrf([vector, lexical])] if use_vectors else lexical
        row = {"q": item["q"], "gold": item["gold"]}
        for mode, ranking in (("vector", vector), ("keyword", lexical), ("hybrid", hybrid)):
            found = top_files(store, ranking)
            ok = any(g in found for g in item["gold"])
            hits[mode] += ok
            row[mode] = {"top": found, "hit": ok}
        per_question.append(row)
    n = len(questions)
    return {"recall_at_5": {m: round(v / n, 3) for m, v in hits.items()}, "n": n, "questions": per_question}


async def refusals(store, runtime, answerable, unanswerable) -> dict:
    correct, rows = 0, []
    for q, should_refuse in [(a["q"], False) for a in answerable] + [(u, True) for u in unanswerable]:
        _, refused = await retrieve(store, runtime, q)
        correct += refused == should_refuse
        rows.append({"q": q, "should_refuse": should_refuse, "refused": refused})
    return {"accuracy": round(correct / len(rows), 3), "n": len(rows), "rows": rows}


async def mechanical_share(record, runtime, n_commits: int = 40) -> dict:
    store = MemoryStore.open(record.repo_id)
    repo = Path(record.path)
    mech = beh = 0
    for row in store.query("SELECT sha FROM commits ORDER BY seq DESC LIMIT ?", (n_commits,)):
        diff = commit_diff(repo, row["sha"])
        if not diff.strip() or len(diff) > 200_000:
            continue
        rep = await review(record.repo_id, repo, diff, runtime, source=DiffSource("commit", head=row["sha"]),
                           run_checks_enabled=False, use_model=False, persist=False)
        mech += rep.mechanical_count
        beh += rep.behavior_count
    total = mech + beh
    return {"commits": n_commits, "hunks": total, "mechanical": mech, "share": round(mech / total, 3) if total else 0.0}


async def citation_validity(record, runtime, n_commits: int = 20) -> dict:
    store = MemoryStore.open(record.repo_id)
    repo = Path(record.path)
    kept = dropped = 0
    for row in store.query("SELECT sha FROM commits WHERE is_fix=1 ORDER BY seq DESC LIMIT ?", (n_commits,)):
        diff = commit_diff(repo, row["sha"])
        if not diff.strip() or len(diff) > 60_000:
            continue
        rep = await review(record.repo_id, repo, diff, runtime, source=DiffSource("commit", head=row["sha"]),
                           run_checks_enabled=False, persist=False)
        kept += len(rep.findings)
        dropped += rep.dropped_unverifiable
    total = kept + dropped
    return {"findings": total, "kept": kept, "dropped": dropped, "validity": round(kept / total, 3) if total else None}


async def classifier_accuracy(name: str) -> dict:
    """Precision/recall of the mechanical label against hand labels in eval/datasets/<name>.jsonl."""
    path = ROOT / "eval" / "datasets" / f"{name}.jsonl"
    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    cache: dict[tuple[str, str], dict] = {}
    tp = fp = fn = tn = 0
    errors = []
    for item in items:
        record = next(r for r in registry.list_repos() if r.name == item["repo"])
        key = (record.repo_id, item["sha"])
        if key not in cache:
            diff = commit_diff(Path(record.path), item["sha"])
            rep = await review(record.repo_id, Path(record.path), diff, None,
                               source=DiffSource("commit", head=item["sha"]), run_checks_enabled=False, persist=False)
            cache[key] = {(f.path, h.new_start): h.label for f in rep.files for h in f.hunks}
        pred = cache[key].get((item["path"], item["new_start"]))
        truth_mech = item["label"] == "mechanical"
        pred_mech = pred == "mechanical"
        tp += truth_mech and pred_mech
        fp += pred_mech and not truth_mech
        fn += truth_mech and not pred_mech
        tn += not truth_mech and not pred_mech
        if truth_mech != pred_mech:
            errors.append({"sha": item["sha"][:8], "path": item["path"], "label": item["label"], "pred": pred, "why": item["why"]})
    return {"n": len(items), "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "errors": errors}


def markdown(result: dict) -> str:
    r = result["retrieval"]["recall_at_5"]
    lines = [
        f"# RepoPilot evaluation — {result['dataset']} @ {result['ref']}",
        "",
        f"Mode: **{result['mode']}** · models: {', '.join(result['models']) or 'none'} · {result['generated_at']}",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Retrieval Recall@5, keyword only | {r['keyword']:.0%} ({result['retrieval']['n']} questions) |",
    ]
    if result["mode"] == "models":
        lines += [f"| Retrieval Recall@5, vector only | {r['vector']:.0%} |", f"| Retrieval Recall@5, hybrid (RRF) | {r['hybrid']:.0%} |",
                  f"| Refusal accuracy | {result['refusal']['accuracy']:.0%} ({result['refusal']['n']} questions) |"]
    m = result["mechanical"]
    lines.append(f"| Hunks set aside as mechanical (formatting, comments, docs, import order, renames) | {m['share']:.0%} of {m['hunks']} hunks in the last {m['commits']} commits |")
    if result.get("classifier"):
        c = result["classifier"]
        lines.append(f"| Mechanical label vs hand labels, held-out set | precision {c['precision']:.0%}, recall {c['recall']:.0%} ({c['n']} hunks) |")
        t = result["classifier_tuning"]
        lines.append(f"| Mechanical label vs hand labels, tuning set | precision {t['precision']:.0%}, recall {t['recall']:.0%} ({t['n']} hunks; rules were adjusted on this set) |")
    if result.get("citations") and result["citations"]["validity"] is not None:
        c = result["citations"]
        lines.append(f"| Model findings that cited real changed lines | {c['validity']:.0%} ({c['kept']} of {c['findings']}) |")
    if result.get("bench"):
        lines.append(f"| Benchmark recommendation | {result['bench']['recommendation']} |")
    return "\n".join(lines) + "\n"


async def main(dataset_path: Path, offline: bool, bench_tasks: int) -> None:
    data = json.loads(dataset_path.read_text())
    record = registry.add_clone(data["repo"])
    repo = Path(record.path)
    subprocess.run(["git", "fetch", "--tags", "--quiet"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "--quiet", "--detach", data["ref"]], cwd=repo, check=True)
    runtime = FakeRuntime() if offline else await get_runtime()
    await index_repo(record, runtime)
    store = MemoryStore.open(record.repo_id)
    await calibrate_refusal(store, runtime)

    result = {
        "dataset": dataset_path.stem, "ref": data["ref"], "mode": "offline" if offline else "models",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "models": [] if offline else sorted({m.id for m in runtime.roles.values()}),
        "retrieval": await retrieval(store, runtime, data["questions"], use_vectors=not offline),
        "mechanical": await mechanical_share(record, runtime),
    }
    for other in ("https://github.com/pallets/flask", "https://github.com/psf/requests"):
        registry.add_clone(other)
    result["classifier"] = await classifier_accuracy("mechanical_hunks_holdout")
    result["classifier_tuning"] = await classifier_accuracy("mechanical_hunks")
    if not offline:
        result["refusal"] = await refusals(store, runtime, data["questions"], data["unanswerable"])
        result["citations"] = await citation_validity(record, runtime)
        if bench_tasks:
            models, _, hw = await scan()
            bench = await run_bench(record.repo_id, repo, models, hw, n_tasks=bench_tasks, embed_model=runtime.roles["embed"])
            result["bench"] = {"recommendation": bench.recommendation, "models": [m.model_dump() for m in bench.models]}

    out = ROOT / "eval" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{dataset_path.stem}-latest.json").write_text(json.dumps(result, indent=1))
    (out / f"{dataset_path.stem}-latest.md").write_text(markdown(result))
    print(markdown(result))
    if not offline:
        r = result["retrieval"]["recall_at_5"]
        rows = [
            {"name": "Finds the right file in the top 5 (hybrid search)", "value": f"{r['hybrid']:.0%}",
             "detail": f"{result['retrieval']['n']} questions about {data['repo'].split('github.com/')[1]}; keyword-only {r['keyword']:.0%}, vector-only {r['vector']:.0%}"},
            {"name": "Says “not in this repository” correctly", "value": f"{result['refusal']['accuracy']:.0%}",
             "detail": f"{result['refusal']['n']} questions, including {len(data['unanswerable'])} the code cannot answer"},
            {"name": "Mechanical label agrees with a human", "value": f"{result['classifier']['precision']:.0%} precision",
             "detail": f"recall {result['classifier']['recall']:.0%} on {result['classifier']['n']} held-out hand-labelled hunks from Flask and Requests"},
            {"name": "Hunks set aside as mechanical", "value": f"{result['mechanical']['share']:.0%}",
             "detail": f"formatting, comments, docs, import order and renames; {result['mechanical']['hunks']} hunks across the last {result['mechanical']['commits']} commits"},
        ]
        if result["citations"]["validity"] is not None:
            rows.append({"name": "Model findings citing real changed lines", "value": f"{result['citations']['validity']:.0%}",
                         "detail": f"{result['citations']['findings']} findings on {data['repo'].split('github.com/')[1]} bug-fix commits; the rest were discarded"})
        (ROOT / "web" / "public" / "demo" / "eval.json").write_text(
            json.dumps({"generated_at": result["generated_at"], "models": result["models"], "rows": rows}, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "datasets" / "flask.json")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--bench", type=int, default=6, help="Commits to replay per model (0 to skip).")
    args = parser.parse_args()
    asyncio.run(main(args.dataset, args.offline, args.bench))
