"""CLI entry point for Onboard using Click."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .config import OnboardConfig

console = Console()


def _resolve_path(p: str) -> Path:
    """Resolve a path string to an absolute Path."""
    return Path(p).resolve()


def _load_config() -> OnboardConfig:
    """Load configuration with env overrides."""
    return OnboardConfig.load()


@click.group()
@click.version_option(package_name="onboard")
def cli() -> None:
    """Onboard — Codebase onboarding agent.

    Point it at any git repo and get a comprehensive guide
    to understanding and working with the codebase.
    """


@cli.command()
@click.argument("repo", type=click.Path(exists=True))
@click.option("--deep", is_flag=True, help="Deep analysis: read file contents and generate AI summaries.")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path (default: ONBOARDING.md in repo).")
@click.option("--config", "config_path", type=click.Path(), default=None, help="Path to config YAML file.")
def scan(repo: str, deep: bool, output: str | None, config_path: str | None) -> None:
    """Scan a repository and generate an onboarding guide.

    REPO is the path to the repository to analyze.
    """
    from .pipeline import run_scan

    repo_path = _resolve_path(repo)
    config = OnboardConfig.load(config_path)
    output_path = Path(output).resolve() if output else None

    if deep and not config.anthropic_api_key:
        console.print("[yellow]Warning:[/yellow] ANTHROPIC_API_KEY not set. AI summaries will be skipped.")
        console.print("Set it with: export ANTHROPIC_API_KEY=sk-ant-...\n")
        deep = False

    result = run_scan(repo_path, config, deep=deep, output_path=output_path)

    # Print summary
    _print_scan_summary(result)


@cli.command()
@click.argument("repo", type=click.Path(exists=True))
@click.argument("question", required=False, default=None)
@click.option("--config", "config_path", type=click.Path(), default=None, help="Path to config YAML file.")
def qa(repo: str, question: str | None, config_path: str | None) -> None:
    """Ask questions about a codebase.

    REPO is the path to the repository. If QUESTION is provided, answers it
    directly. Otherwise enters interactive mode.
    """
    from .qa import run_qa_interactive, run_qa_single

    repo_path = _resolve_path(repo)
    config = OnboardConfig.load(config_path)

    if not config.anthropic_api_key:
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY not set.")
        console.print("Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    if question:
        answer = run_qa_single(repo_path, question, config)
        console.print(answer)
    else:
        run_qa_interactive(repo_path, config)


@cli.command()
@click.argument("repo", type=click.Path(exists=True))
@click.option("--config", "config_path", type=click.Path(), default=None, help="Path to config YAML file.")
def diff(repo: str, config_path: str | None) -> None:
    """Show recent changes — quick onboarding for returning developers.

    REPO is the path to the repository.
    """
    from .pipeline import run_diff

    repo_path = _resolve_path(repo)
    config = OnboardConfig.load(config_path)

    git = run_diff(repo_path, config)
    if not git:
        console.print("[red]Not a git repository.[/red]")
        sys.exit(1)

    _print_git_summary(git)


@cli.command()
@click.argument("repo", type=click.Path(exists=True))
@click.option("--config", "config_path", type=click.Path(), default=None, help="Path to config YAML file.")
def stats(repo: str, config_path: str | None) -> None:
    """Show codebase statistics — languages, LOC, complexity.

    REPO is the path to the repository.
    """
    from .pipeline import run_stats

    repo_path = _resolve_path(repo)
    config = OnboardConfig.load(config_path)

    result = run_stats(repo_path, config)
    _print_stats(result)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_scan_summary(result) -> None:  # noqa: ANN001
    """Print a rich summary of a scan result."""
    scan = result.scan
    arch = result.architecture

    console.print()
    console.print(f"[bold green]Onboarding guide generated![/bold green]")

    table = Table(title="Repository Summary", show_header=False, border_style="cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Total files", str(scan.total_files))
    table.add_row("Total size", f"{scan.total_size / 1024:.1f} KB")
    table.add_row("Languages", ", ".join(f"{l} ({c})" for l, c in sorted(scan.by_language.items(), key=lambda x: -x[1])[:5]))
    table.add_row("Modules", str(len(arch.modules)))
    table.add_row("Entry points", str(len(scan.entry_points)))
    table.add_row("Dependencies", str(len(scan.dependencies)))
    table.add_row("Patterns", ", ".join(scan.detected_patterns) or "none")
    console.print(table)

    if result.git:
        console.print(f"\n[bold]Git:[/bold] {result.git.total_commits} commits on [cyan]{result.git.branch}[/cyan]")


def _print_git_summary(git) -> None:  # noqa: ANN001
    """Print a rich summary of git analysis."""
    console.print()
    console.print(f"[bold cyan]Recent Changes[/bold cyan] — branch: {git.branch}, {git.total_commits} total commits")

    if git.recent_commits:
        table = Table(title="Recent Commits", border_style="cyan")
        table.add_column("Hash", style="dim")
        table.add_column("Author")
        table.add_column("Date", style="dim")
        table.add_column("Message")
        for commit in git.recent_commits[:15]:
            table.add_row(commit["hash"], commit["author"], commit["date"][:10], commit["message"][:60])
        console.print(table)

    if git.top_changed_files:
        console.print("\n[bold]Most frequently changed files:[/bold]")
        table = Table(border_style="yellow")
        table.add_column("File")
        table.add_column("Changes", justify="right")
        table.add_column("Top contributors")
        for fs in git.top_changed_files:
            table.add_row(fs.path, str(fs.change_count), ", ".join(fs.contributors[:2]))
        console.print(table)

    if git.hotspots:
        console.print(f"\n[bold red]Hotspots:[/bold red] {', '.join(git.hotspots[:10])}")


def _print_stats(result) -> None:  # noqa: ANN001
    """Print codebase statistics."""
    scan = result.scan
    arch = result.architecture

    console.print()

    # Language breakdown
    table = Table(title="Language Breakdown", border_style="cyan")
    table.add_column("Language", style="bold")
    table.add_column("Files", justify="right")
    table.add_column("Percentage", justify="right")
    for lang, count in sorted(scan.by_language.items(), key=lambda x: -x[1]):
        pct = count / scan.total_files * 100 if scan.total_files else 0
        table.add_row(lang, str(count), f"{pct:.1f}%")
    console.print(table)

    # Category breakdown
    table = Table(title="File Categories", border_style="green")
    table.add_column("Category", style="bold")
    table.add_column("Count", justify="right")
    for cat, count in sorted(scan.by_category.items(), key=lambda x: -x[1]):
        table.add_row(cat, str(count))
    console.print(table)

    # Extension breakdown (top 15)
    table = Table(title="Top File Extensions", border_style="yellow")
    table.add_column("Extension", style="bold")
    table.add_column("Count", justify="right")
    for ext, count in sorted(scan.by_extension.items(), key=lambda x: -x[1])[:15]:
        table.add_row(ext or "(none)", str(count))
    console.print(table)

    # Module summary
    table = Table(title="Modules", border_style="magenta")
    table.add_column("Module", style="bold")
    table.add_column("Files", justify="right")
    table.add_column("Purpose")
    for mod in sorted(arch.modules, key=lambda m: -m.file_count):
        table.add_row(mod.name, str(mod.file_count), mod.purpose or "-")
    console.print(table)
