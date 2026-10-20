"""Does the model review catch real bugs without crying wolf?

    backend/.venv/bin/python eval/seeded_bugs.py                 # needs a local model runtime
    backend/.venv/bin/python eval/seeded_bugs.py --n 10          # smaller run

Two sets, both on pallets/flask at the pinned ref, reviewed without running tests:
- seeded: single-line mutations planted in library code (flipped comparison, negation removed,
  `is None` inverted, `and`/`or` swapped, boolean return flipped, off-by-one). Presented as an
  uncommitted change with no commit message. Caught = a medium or high finding on the changed line.
- clean: recent merged bug-fix commits, reviewed with their commit messages as intent. They are
  assumed correct, so any medium or high finding counts as a false alarm.

Writes eval/results/seeded-bugs.{json,md}.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import random
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from repopilot.engines.diffparse import DiffSource, commit_diff  # noqa: E402
from repopilot.engines.review import review  # noqa: E402
from repopilot.memory import registry  # noqa: E402
from repopilot.memory.store import MemoryStore  # noqa: E402
from repopilot.runtime import get_runtime  # noqa: E402

REPO = "https://github.com/pallets/flask"
REF = "3.1.0"
MUTATIONS = [
    ("flip ==", r" == ", " != "),
    ("flip !=", r" != ", " == "),
    ("invert is None", r" is None\b", " is not None"),
    ("invert is not None", r" is not None\b", " is None"),
    ("drop not", r"\bif not ", "if "),
    ("and to or", r" and ", " or "),
    ("or to and", r" or ", " and "),
    ("< to <=", r" < ", " <= "),
    ("> to >=", r" > ", " >= "),
    ("flip return True", r"return True\b", "return False"),
    ("flip return False", r"return False\b", "return True"),
    ("off by one", r" \+ 1\b", " - 1"),
]
FLAGGED = {"medium", "high"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def candidate_lines(source: str) -> set[int]:
    """Lines inside function bodies that hold a whole comparison, boolean test or return."""
    lines: set[int] = set()
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            kinds = ast.Compare | ast.BoolOp | ast.Return | ast.BinOp | ast.UnaryOp
            if isinstance(node, kinds) and node.lineno == node.end_lineno:
                lines.add(node.lineno)
    return lines


def plan_mutations(repo: Path, n: int, seed: int) -> list[dict]:
    """Pick up to `n` mutations, at most one per function file line, each changing the syntax tree."""
    rng = random.Random(seed)
    options = []
    for path in sorted((repo / "src" / "flask").rglob("*.py")):
        text = path.read_text()
        lines = text.splitlines(keepends=True)
        for lineno in sorted(candidate_lines(text)):
            line = lines[lineno - 1]
            if line.lstrip().startswith("#"):
                continue
            for name, pattern, repl in MUTATIONS:
                if re.search(pattern, line.split("#")[0]):
                    mutated = re.sub(pattern, repl, line, count=1)
                    new_text = "".join(lines[: lineno - 1] + [mutated] + lines[lineno:])
                    try:
                        if ast.dump(ast.parse(new_text)) == ast.dump(ast.parse(text)):
                            continue
                    except SyntaxError:
                        continue
                    options.append({"path": str(path.relative_to(repo)), "line": lineno, "mutation": name,
                                    "before": line.strip(), "after": mutated.strip(), "_new": new_text})
    rng.shuffle(options)
    chosen, seen_files = [], {}
    for opt in options:  # spread across files and operators
        if seen_files.get(opt["path"], 0) >= 3 or sum(c["mutation"] == opt["mutation"] for c in chosen) >= 3:
            continue
        seen_files[opt["path"]] = seen_files.get(opt["path"], 0) + 1
        chosen.append(opt)
        if len(chosen) == n:
            break
    return chosen


def summarize(rep) -> list[dict]:
    return [{"severity": f.severity, "path": f.path, "line": f.line, "title": f.title,
             "failing_input": f.failing_input, "corroborated": f.corroborated} for f in rep.findings]


async def run_seeded(record, runtime, cases: list[dict]) -> list[dict]:
    repo = Path(record.path)
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt"
        git(repo, "worktree", "add", "--detach", "--quiet", str(wt), REF)
        try:
            for i, case in enumerate(cases, 1):
                (wt / case["path"]).write_text(case.pop("_new"))
                diff = git(wt, "diff")
                t0 = time.perf_counter()
                rep = await review(record.repo_id, wt, diff, runtime, source=DiffSource("working"),
                                   run_checks_enabled=False, persist=False)
                git(wt, "checkout", "--quiet", "--", ".")
                hits = [f for f in rep.findings if f.severity in FLAGGED and f.path == case["path"]
                        and abs(f.line - case["line"]) <= 3]
                row = {**case, "caught": bool(hits), "findings": summarize(rep),
                       "dropped_unconfirmed": rep.dropped_unconfirmed, "model_error": rep.model_error,
                       "seconds": round(time.perf_counter() - t0, 1)}
                out.append(row)
                print(f"seeded {i}/{len(cases)} {case['path']}:{case['line']} {case['mutation']}: "
                      f"{'caught' if row['caught'] else 'missed'} ({row['seconds']}s)", flush=True)
        finally:
            git(repo, "worktree", "remove", "--force", str(wt))
    return out


async def run_clean(record, runtime, n: int) -> list[dict]:
    store = MemoryStore.open(record.repo_id)
    repo = Path(record.path)
    out = []
    for row in store.query("SELECT sha, subject FROM commits WHERE is_fix=1 ORDER BY seq DESC LIMIT 60"):
        diff = commit_diff(repo, row["sha"])
        if not diff.strip() or len(diff) > 60_000:
            continue
        t0 = time.perf_counter()
        rep = await review(record.repo_id, repo, diff, runtime, source=DiffSource("commit", head=row["sha"]),
                           run_checks_enabled=False, persist=False)
        if not rep.behavior_count:
            continue
        flagged = [f for f in rep.findings if f.severity in FLAGGED]
        out.append({"sha": row["sha"][:10], "subject": row["subject"], "false_alarm": bool(flagged),
                    "high": any(f.severity == "high" for f in flagged), "findings": summarize(rep),
                    "dropped_unconfirmed": rep.dropped_unconfirmed, "model_error": rep.model_error,
                    "seconds": round(time.perf_counter() - t0, 1)})
        print(f"clean {len(out)}/{n} {row['sha'][:10]} {row['subject'][:50]}: "
              f"{'FALSE ALARM' if flagged else 'quiet'} ({out[-1]['seconds']}s)", flush=True)
        if len(out) == n:
            break
    return out


def markdown(result: dict) -> str:
    s, c = result["seeded"], result["clean"]
    lines = [
        f"# Seeded bugs vs clean fixes — {result['repo']} @ {result['ref']}",
        "",
        f"Models: {', '.join(result['models'])}. Generated {result['generated_at']}. Tests not run.",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Planted bugs caught (medium/high on the changed line) | **{result['caught_rate']:.0%}** ({sum(r['caught'] for r in s)} of {len(s)}) |",
        f"| Clean merged fixes flagged medium/high (false alarms) | **{result['false_alarm_rate']:.0%}** ({sum(r['false_alarm'] for r in c)} of {len(c)}) |",
        f"| Clean merged fixes flagged high | {result['high_false_alarm_rate']:.0%} |",
        f"| Median seconds per review | {result['median_seconds']} |",
        "",
        "## Planted bugs",
        "",
        "| File:line | Mutation | Change | Caught |",
        "|---|---|---|---|",
    ]
    for r in s:
        lines.append(f"| `{r['path']}:{r['line']}` | {r['mutation']} | `{r['before']}` → `{r['after']}` | {'yes' if r['caught'] else 'no'} |")
    lines += ["", "## Clean fixes", "", "| Commit | Subject | Flagged |", "|---|---|---|"]
    for r in c:
        lines.append(f"| `{r['sha']}` | {r['subject'][:70]} | {'yes' if r['false_alarm'] else 'no'} |")
    return "\n".join(lines) + "\n"


async def main(n: int, seed: int) -> None:
    record = registry.add_clone(REPO)
    repo = Path(record.path)
    git(repo, "checkout", "--quiet", "--detach", REF)
    runtime = await get_runtime()
    cases = plan_mutations(repo, n, seed)
    seeded = await run_seeded(record, runtime, cases)
    clean = await run_clean(record, runtime, n)
    secs = sorted(r["seconds"] for r in seeded + clean)
    result = {
        "repo": REPO.split("github.com/")[1], "ref": REF, "seed": seed,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "models": sorted({m.id for m in runtime.roles.values()}),
        "caught_rate": round(sum(r["caught"] for r in seeded) / len(seeded), 3),
        "false_alarm_rate": round(sum(r["false_alarm"] for r in clean) / len(clean), 3),
        "high_false_alarm_rate": round(sum(r["high"] for r in clean) / len(clean), 3),
        "median_seconds": secs[len(secs) // 2],
        "seeded": seeded, "clean": clean,
    }
    out = ROOT / "eval" / "results"
    (out / "seeded-bugs.json").write_text(json.dumps(result, indent=1))
    (out / "seeded-bugs.md").write_text(markdown(result))
    print(markdown(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=20, help="Cases per set.")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    asyncio.run(main(args.n, args.seed))
