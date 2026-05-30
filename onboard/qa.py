"""Interactive Q&A mode for asking questions about a codebase.

Uses the scanner and AI engine to build context, then answers
natural language questions about the repository.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from .config import OnboardConfig
from .scanner import ScanResult, scan_repository, read_file_contents
from .analyzer import ArchitectureMap, analyze_architecture
from .git_analyzer import GitAnalysis, analyze_git
from .engine import answer_question

console = Console()


def _build_context(scan: ScanResult, arch: ArchitectureMap, git: GitAnalysis | None) -> str:
    """Build a compact context string for Q&A."""
    lines: list[str] = []
    lines.append(f"Project root: {scan.root}")
    lines.append(f"Files: {scan.total_files}, Size: {scan.total_size / 1024:.0f} KB")
    lines.append(f"Languages: {', '.join(f'{l} ({c})' for l, c in sorted(scan.by_language.items(), key=lambda x: -x[1])[:5])}")
    lines.append(f"Entry points: {', '.join(scan.entry_points[:5])}")
    lines.append(f"Patterns: {', '.join(scan.detected_patterns)}")

    lines.append("\nTop-level directories:")
    for d in arch.top_level_dirs:
        lines.append(f"  {d}/")

    lines.append("\nModules:")
    for mod in arch.modules:
        lines.append(f"  {mod.name}: {mod.file_count} files ({mod.purpose or 'unknown purpose'})")

    if git:
        lines.append(f"\nGit: {git.total_commits} commits on branch '{git.branch}'")
        if git.hotspots:
            lines.append(f"Hotspots: {', '.join(git.hotspots[:5])}")

    # Add file tree (compact)
    lines.append("\nFile tree (first 100):")
    for fi in scan.files[:100]:
        lines.append(f"  {fi.relative} ({fi.size}B)")

    return "\n".join(lines)


def _read_relevant_files(scan: ScanResult, question: str, config: OnboardConfig) -> str:
    """Read files that might be relevant to the question."""
    question_lower = question.lower()
    keywords = set(question_lower.split())

    # Score files by relevance to question
    scored: list[tuple[float, Path, str]] = []
    for fi in scan.files:
        score = 0.0
        rel_lower = fi.relative.lower()
        name_lower = fi.path.name.lower()

        # Boost if filename or path matches question keywords
        for kw in keywords:
            if len(kw) > 2 and kw in rel_lower:
                score += 2.0
            if len(kw) > 2 and kw in name_lower:
                score += 3.0

        # Boost entry points and configs
        if fi.relative in scan.entry_points:
            score += 1.0
        if fi.category == "config":
            score += 0.5

        if score > 0:
            scored.append((score, fi.path, fi.relative))

    scored.sort(key=lambda x: -x[0])

    blocks: list[str] = []
    read_count = 0
    for _, path, rel in scored[:15]:
        if read_count >= config.max_files_to_read:
            break
        content = read_file_contents(path, config.max_file_read_size)
        if content:
            blocks.append(f"--- {rel} ---\n{content[:5000]}\n")
            read_count += 1

    return "\n".join(blocks)


def run_qa_interactive(repo_path: Path, config: OnboardConfig) -> None:
    """Run interactive Q&A session."""
    console.print(Panel(
        "[bold cyan]Onboard Q&A Mode[/bold cyan]\n"
        "Ask questions about the codebase. Type 'quit' or 'exit' to leave.",
        border_style="cyan",
    ))

    console.print("\n[dim]Scanning repository...[/dim]")
    scan = scan_repository(repo_path, config)
    arch = analyze_architecture(scan)
    git = analyze_git(repo_path, config)
    context = _build_context(scan, arch, git)

    console.print(f"[green]Ready.[/green] Analyzed {scan.total_files} files.\n")

    while True:
        try:
            question = Prompt.ask("[bold cyan]Question[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not question.strip():
            continue
        if question.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break

        console.print("[dim]Thinking...[/dim]")
        file_contents = _read_relevant_files(scan, question, config)
        answer = answer_question(question, context, file_contents, config)

        console.print()
        console.print(Panel(Markdown(answer), border_style="green", title="Answer"))
        console.print()


def run_qa_single(repo_path: Path, question: str, config: OnboardConfig) -> str:
    """Answer a single question and return the answer."""
    scan = scan_repository(repo_path, config)
    arch = analyze_architecture(scan)
    git = analyze_git(repo_path, config)
    context = _build_context(scan, arch, git)
    file_contents = _read_relevant_files(scan, question, config)
    return answer_question(question, context, file_contents, config)
