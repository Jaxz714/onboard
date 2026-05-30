"""Main orchestration pipeline for Onboard.

Coordinates the scanner, analyzer, git analyzer, AI engine,
and output generator into a coherent workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .config import OnboardConfig
from .scanner import ScanResult, scan_repository
from .analyzer import ArchitectureMap, analyze_architecture
from .git_analyzer import GitAnalysis, analyze_git
from .engine import AISummary, generate_summary
from .outputs.guide import generate_guide_markdown

console = Console()


@dataclass
class PipelineResult:
    """Complete result of an onboard pipeline run."""
    scan: ScanResult
    architecture: ArchitectureMap
    git: GitAnalysis | None
    ai_summary: AISummary | None
    guide_markdown: str = ""


def run_scan(
    repo_path: Path,
    config: OnboardConfig,
    deep: bool = False,
    output_path: Path | None = None,
) -> PipelineResult:
    """Run the full scan pipeline.

    Args:
        repo_path: Path to the repository to analyze.
        config: Runtime configuration.
        deep: If True, read file contents for AI analysis.
        output_path: Where to write the output guide.
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:

        # Step 1: Scan
        task = progress.add_task("Scanning repository...", total=None)
        scan_result = scan_repository(repo_path, config)
        progress.update(task, description=f"Scanned {scan_result.total_files} files")

        # Step 2: Architecture analysis
        task = progress.add_task("Analyzing architecture...", total=None)
        arch = analyze_architecture(scan_result)
        progress.update(task, description=f"Found {len(arch.modules)} modules")

        # Step 3: Git analysis
        task = progress.add_task("Analyzing git history...", total=None)
        git = analyze_git(repo_path, config)
        if git:
            progress.update(task, description=f"Analyzed {git.total_commits} commits")
        else:
            progress.update(task, description="No git repository found")

        # Step 4: AI summary (only if deep mode and API key available)
        ai_summary = None
        if deep:
            task = progress.add_task("Generating AI summaries...", total=None)
            ai_summary = generate_summary(scan_result, arch, git, config)
            progress.update(task, description="AI summaries generated")

        # Step 5: Generate guide
        task = progress.add_task("Generating onboarding guide...", total=None)
        guide = generate_guide_markdown(scan_result, arch, git, ai_summary)
        progress.update(task, description="Guide generated")

    # Step 6: Write output
    out = output_path or Path(config.output_file)
    out.write_text(guide, encoding="utf-8")
    console.print(f"\n[green]Onboarding guide written to:[/green] {out}")

    return PipelineResult(
        scan=scan_result,
        architecture=arch,
        git=git,
        ai_summary=ai_summary,
        guide_markdown=guide,
    )


def run_stats(repo_path: Path, config: OnboardConfig) -> PipelineResult:
    """Run a stats-only scan (no AI, no guide output)."""
    scan_result = scan_repository(repo_path, config)
    arch = analyze_architecture(scan_result)
    git = analyze_git(repo_path, config)
    return PipelineResult(
        scan=scan_result,
        architecture=arch,
        git=git,
        ai_summary=None,
    )


def run_diff(repo_path: Path, config: OnboardConfig) -> GitAnalysis | None:
    """Run a diff/recent-changes analysis."""
    return analyze_git(repo_path, config)
