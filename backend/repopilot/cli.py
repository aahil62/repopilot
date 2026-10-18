"""`repopilot` command-line interface."""

from __future__ import annotations

from pathlib import Path

import typer

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


@app.command()
def serve() -> None:
    """Start the local API and web UI."""
    raise typer.Exit(_todo("serve"))


@app.command()
def index(path: Path = typer.Argument(Path("."), help="Repository to index.")) -> None:
    """Index a repository: code, symbols, imports and git history."""
    raise typer.Exit(_todo("index"))


@app.command()
def review(
    repo: Path = typer.Option(Path("."), help="Repository path."),
    base: str | None = typer.Option(None, help="Base ref."),
    head: str | None = typer.Option(None, help="Head ref."),
    staged: bool = typer.Option(False, help="Review staged changes."),
) -> None:
    """Review changes with history-aware checks."""
    raise typer.Exit(_todo("review"))


@app.command()
def blast(
    path: str = typer.Argument(..., help="File path inside the repository."),
    repo: Path = typer.Option(Path("."), help="Repository path."),
) -> None:
    """Show what usually breaks or changes together with a file."""
    raise typer.Exit(_todo("blast"))


@app.command()
def bench(
    repo: Path = typer.Option(Path("."), help="Repository path."),
    tasks: int = typer.Option(10, help="Number of past commits to replay."),
) -> None:
    """Score installed models on your own repository: which model should we run?"""
    raise typer.Exit(_todo("bench"))


@app.command()
def models() -> None:
    """List local model runtimes, installed models and role assignments."""
    raise typer.Exit(_todo("models"))


@nightshift_app.command("run")
def nightshift_run(repo: Path = typer.Option(Path("."), help="Repository path.")) -> None:
    """Run the night shift now."""
    raise typer.Exit(_todo("nightshift run"))


@nightshift_app.command("install")
def nightshift_install(
    repo: Path = typer.Option(Path("."), help="Repository path."),
    at: str = typer.Option("02:00", help="Local time HH:MM."),
) -> None:
    """Print/write the scheduler entry that runs the night shift daily."""
    raise typer.Exit(_todo("nightshift install"))


@nightshift_app.command("report")
def nightshift_report(repo: Path = typer.Option(Path("."), help="Repository path.")) -> None:
    """Show the latest night-shift report."""
    raise typer.Exit(_todo("nightshift report"))


def _todo(name: str) -> int:
    typer.echo(f"`repopilot {name}` is not implemented yet.", err=True)
    return 2
