"""`repopilot` command-line interface."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from repopilot.config import get_settings
from repopilot.runtime import NoRuntimeError

app = typer.Typer(
    name="repopilot",
    help="Private, history-aware code review on open models you run yourself.",
    no_args_is_help=True,
    add_completion=False,
)
nightshift_app = typer.Typer(
    help="Overnight review, test writing and stale-doc checks.", no_args_is_help=True
)
app.add_typer(nightshift_app, name="nightshift")
console = Console()
SEVERITY_STYLE = {"high": "bold red", "medium": "yellow", "low": "cyan"}
RISK_STYLE = {"high": "bold red", "medium": "yellow", "low": "green"}


def _run(coro):
    try:
        return asyncio.run(coro)
    except NoRuntimeError:
        console.print(
            "[bold red]No local model runtime found.[/] Start Ollama or LM Studio, then pull models:"
        )
        console.print(
            "  ollama pull qwen2.5-coder:7b\n  ollama pull qwen2.5-coder:1.5b\n  ollama pull nomic-embed-text"
        )
        raise typer.Exit(3) from None


def _record(repo: Path):
    from repopilot.memory import registry

    try:
        return registry.find_by_path(repo) or registry.add_local(repo)
    except registry.RepoError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from None


async def _ensure_indexed(record, runtime) -> None:
    from repopilot.engines.ask import calibrate_refusal
    from repopilot.memory.pipeline import index_repo
    from repopilot.memory.store import MemoryStore

    with console.status("Updating repository memory…") as status:
        stats = await index_repo(
            record, runtime, lambda p: status.update(f"{p.stage}: {p.done}/{p.total} {p.message}")
        )
        if runtime is not None:
            await calibrate_refusal(MemoryStore.open(record.repo_id), runtime)
    for note in stats.notes:
        console.print(f"[dim]{note}[/]")


@app.command()
def serve(
    host: str = typer.Option(None, help="Bind address (default 127.0.0.1)."),
    port: int = typer.Option(None, help="Port (default 7341)."),
) -> None:
    """Start the local API and web UI."""
    import uvicorn

    from repopilot.api.main import create_app

    settings = get_settings()
    host, port = host or settings.host, port or settings.port
    console.print(f"RepoPilot running at [bold]http://{host}:{port}[/] (data in {settings.home})")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


@app.command()
def index(
    path: Path = typer.Argument(Path("."), help="Repository to index."),
    with_reviews: bool = typer.Option(
        False, help="Also import GitHub PR review comments (needs REPOPILOT_ALLOW_GITHUB_IMPORT=1)."
    ),
) -> None:
    """Index a repository: code, symbols, imports and git history."""
    from repopilot.engines.ask import calibrate_refusal
    from repopilot.memory.pipeline import index_repo, repo_summary
    from repopilot.memory.store import MemoryStore
    from repopilot.runtime import get_runtime_optional

    record = _record(path)

    async def go():
        runtime = await get_runtime_optional()
        with console.status("Indexing…") as status:
            stats = await index_repo(
                record,
                runtime,
                lambda p: status.update(f"{p.stage}: {p.done}/{p.total}"),
                with_reviews=with_reviews,
            )
            if runtime is not None:
                await calibrate_refusal(MemoryStore.open(record.repo_id), runtime)
        return stats

    stats = _run(go())
    summary = repo_summary(record)
    console.print(
        f"[green]Indexed {record.name}[/]: {summary['files']} files, {summary['chunks']} chunks, "
        f"{summary['commits']} commits ({stats.files_changed} files changed since last run)."
    )
    for note in stats.notes:
        console.print(f"[dim]{note}[/]")


@app.command()
def review(
    repo: Path = typer.Option(Path("."), help="Repository path."),
    base: str | None = typer.Option(None, help="Base ref."),
    head: str | None = typer.Option(None, help="Head ref."),
    staged: bool = typer.Option(False, help="Review staged changes."),
    no_checks: bool = typer.Option(False, help="Skip running the project's tests."),
    as_json: bool = typer.Option(False, "--json", help="Print the full report as JSON."),
) -> None:
    """Review changes with history-aware checks."""
    from repopilot.engines.diffparse import diff_for
    from repopilot.engines.review import review as run_review
    from repopilot.runtime import get_runtime_optional

    record = _record(repo)
    diff, source = diff_for(Path(record.path), base=base, head=head, staged=staged)
    if not diff.strip():
        console.print("Nothing to review.")
        raise typer.Exit(0)

    async def go():
        runtime = await get_runtime_optional()
        await _ensure_indexed(record, runtime)
        with console.status("Reviewing…"):
            return await run_review(
                record.repo_id,
                Path(record.path),
                diff,
                runtime,
                source=source,
                run_checks_enabled=not no_checks,
            )

    report = _run(go())
    if as_json:
        console.print_json(report.model_dump_json())
        return
    console.print(f"\n[bold]{report.summary}[/]")
    console.print(
        f"[dim]{report.mechanical_count} mechanical hunks collapsed · {report.behavior_count} behavior hunks[/]"
    )
    for f in report.findings:
        console.print(f"[{SEVERITY_STYLE[f.severity]}]{f.severity.upper():6}[/] {f.path}:{f.line}  {f.title}")
        console.print(f"        {f.explanation}")
        for ev in f.evidence_detail:
            console.print(f"        [dim]↳ {ev.ref}: {ev.excerpt[:100]}[/]")
    if report.dropped_unverifiable:
        console.print(
            f"[dim]{report.dropped_unverifiable} model finding(s) dropped: they cited lines outside this change.[/]"
        )
    if report.blast:
        console.print(f"\nBlast radius: [{RISK_STYLE[report.blast.risk]}]{report.blast.risk}[/]")
        for reason in report.blast.risk_reasons:
            console.print(f"  · {reason}")
        if report.blast.owners:
            console.print("  Suggested reviewers: " + ", ".join(o.author for o in report.blast.owners))
    c = report.checks
    console.print(
        f"\nChecks: {c.status}"
        + (f" ({c.command})" if c.command else "")
        + (f" — {c.message}" if c.message else "")
    )
    if c.status == "failed":
        console.print(f"[dim]{c.output_tail[-1200:]}[/]")
    if report.model_error:
        console.print(f"[yellow]{report.model_error}[/]")


@app.command()
def blast(
    path: str = typer.Argument(..., help="File path inside the repository."),
    repo: Path = typer.Option(Path("."), help="Repository path."),
) -> None:
    """Show what usually breaks or changes together with a file."""
    from repopilot.engines.blast import blast_radius
    from repopilot.runtime import get_runtime_optional

    record = _record(repo)

    async def go():
        await _ensure_indexed(record, await get_runtime_optional())

    _run(go())
    report = blast_radius(record.repo_id, [path])
    console.print(f"Blast radius for [bold]{path}[/]: [{RISK_STYLE[report.risk]}]{report.risk}[/]")
    for reason in report.risk_reasons:
        console.print(f"  · {reason}")
    table = Table("Changes together with", "Confidence", "Support")
    for c in report.cochanged[:10]:
        table.add_row(c.path, f"{round(c.confidence * 100)}%", str(c.support))
    console.print(table)
    if report.dependents:
        console.print("Depends on it: " + ", ".join(f"{d.path}" for d in report.dependents[:12]))
    for f in report.past_fixes[:5]:
        console.print(f"  [red]fix[/] {f.sha[:8]} {f.date[:10]} {f.subject}")


@app.command()
def bench(
    repo: Path = typer.Option(Path("."), help="Repository path."),
    tasks: int = typer.Option(10, help="Number of past commits to replay."),
) -> None:
    """Score installed models on your own repository: which model should we run?"""
    from repopilot.engines.bench import run_bench
    from repopilot.runtime import get_runtime, scan

    record = _record(repo)

    async def go():
        runtime = await get_runtime()
        await _ensure_indexed(record, runtime)
        models, _, hw = await scan()
        with console.status(f"Replaying up to {tasks} commits on {len(models)} model(s)…"):
            return await run_bench(
                record.repo_id,
                Path(record.path),
                models,
                hw,
                n_tasks=tasks,
                embed_model=runtime.roles.get("embed"),
            )

    result = _run(go())
    table = Table("Model", "Score", "Applies", "Tests pass", "Similarity", "Median latency", "tok/s")
    for m in result.models:
        table.add_row(
            m.model,
            f"{m.score:.2f}",
            f"{m.applies_rate:.0%}",
            "–" if m.tests_pass_rate is None else f"{m.tests_pass_rate:.0%}",
            f"{m.similarity:.2f}",
            f"{m.median_latency_s:.0f}s",
            "–" if m.tokens_per_second is None else f"{m.tokens_per_second:.0f}",
        )
    console.print(table)
    for s in result.skipped:
        console.print(f"[dim]skipped {s.model}: {s.reason}[/]")
    console.print(f"[bold]{result.recommendation}[/]")


@app.command()
def models() -> None:
    """List local model runtimes, installed models and role assignments."""
    from repopilot.config import get_settings as settings
    from repopilot.runtime import fits, scan
    from repopilot.runtime.roles import assign_roles, load_overrides

    found, statuses, hw = asyncio.run(scan())
    for s in statuses:
        console.print(f"{'[green]●[/]' if s.reachable else '[red]○[/]'} {s.base_url} ({s.kind})")
    table = Table("Model", "Size", "Context", "Fits")
    for m in found:
        size = f"{m.size_bytes / 1024**3:.1f} GB" if m.size_bytes else "?"
        table.add_row(
            m.id + (" (embed)" if m.is_embedding else ""),
            size,
            str(m.context_length or "?"),
            "yes" if fits(m, hw) else "no",
        )
    console.print(table)
    try:
        roles = assign_roles(found, hw, load_overrides(settings().home / "models.json"))
        console.print("Roles: " + ", ".join(f"{k} → {v.id}" for k, v in roles.items()))
    except NoRuntimeError:
        console.print("[yellow]No usable chat model. Try: ollama pull qwen2.5-coder:7b[/]")


@nightshift_app.command("run")
def nightshift_run(repo: Path = typer.Option(Path("."), help="Repository path.")) -> None:
    """Run the night shift now."""
    from repopilot.engines.nightshift import run_nightshift
    from repopilot.runtime import get_runtime

    record = _record(repo)

    async def go():
        runtime = await get_runtime()
        with console.status("Night shift running…"):
            return await run_nightshift(record, runtime)

    report = _run(go())
    console.print(
        f"Reviewed {len(report.commits_reviewed)} commit(s), "
        f"{sum(len(c.findings) for c in report.commits_reviewed)} finding(s); "
        f"{sum(t.status == 'verified' for t in report.tests_written)} verified test(s); "
        f"{len(report.stale_docs)} stale doc reference(s)."
    )
    console.print(f"Report: {get_settings().repo_dir(record.repo_id) / 'reports' / (report.date + '.md')}")


@nightshift_app.command("install")
def nightshift_install(
    repo: Path = typer.Option(Path("."), help="Repository path."),
    at: str = typer.Option("02:00", help="Local time HH:MM."),
) -> None:
    """Write (macOS) or print the scheduler entry that runs the night shift daily. Never activates it for you."""
    from repopilot.engines.nightshift import schedule

    info = schedule(repo, at)
    if info["kind"] == "launchd":
        path = Path(info["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(info["content"])
        console.print(f"Wrote {path}\nActivate it with:\n  {info['activate']}")
    elif info["kind"] == "cron":
        console.print(f"Add this line with `crontab -e`:\n  {info['content']}")
    else:
        console.print(f"Run:\n  {info['activate']}")


@nightshift_app.command("report")
def nightshift_report(repo: Path = typer.Option(Path("."), help="Repository path.")) -> None:
    """Show the latest night-shift report."""
    from repopilot.engines.nightshift import _markdown, list_reports, load_report

    record = _record(repo)
    reports = list_reports(record.repo_id)
    if not reports:
        console.print("No night-shift reports yet. Run `repopilot nightshift run`.")
        return
    report = load_report(record.repo_id, reports[0]["date"])
    console.print(_markdown(report))


@app.command("ask")
def ask_cmd(question: str, repo: Path = typer.Option(Path("."), help="Repository path.")) -> None:
    """Ask a question about the repository; answers cite exact lines."""
    from repopilot.engines.ask import ask
    from repopilot.memory.store import MemoryStore
    from repopilot.runtime import get_runtime

    record = _record(repo)

    async def go():
        runtime = await get_runtime()
        await _ensure_indexed(record, runtime)
        return await ask(MemoryStore.open(record.repo_id), runtime, question)

    result = _run(go())
    console.print(result.answer)
    for c in result.citations:
        console.print(f"  [{c.n}] {c.path}:{c.start_line}-{c.end_line}")
    for c in result.commits:
        console.print(f"  [dim]{c.sha[:8]} {c.date[:10]} {c.subject}[/]")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
