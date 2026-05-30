"""Git history analysis using the git CLI.

Finds most active files, key contributors, recent changes,
and detects hotspots.
"""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .config import OnboardConfig


@dataclass
class ContributorStats:
    """Stats for a single contributor."""
    name: str
    commits: int = 0
    files_touched: set[str] = field(default_factory=set)
    insertions: int = 0
    deletions: int = 0


@dataclass
class FileChangeStats:
    """Change statistics for a single file."""
    path: str
    change_count: int = 0
    contributors: list[str] = field(default_factory=list)
    last_changed: str = ""
    insertions: int = 0
    deletions: int = 0


@dataclass
class GitAnalysis:
    """Complete git history analysis result."""
    total_commits: int = 0
    recent_commits: list[dict[str, str]] = field(default_factory=list)
    top_changed_files: list[FileChangeStats] = field(default_factory=list)
    contributors: list[ContributorStats] = field(default_factory=list)
    hotspots: list[str] = field(default_factory=list)
    branch: str = ""
    repo_age: str = ""


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _is_git_repo(path: Path) -> bool:
    return _run_git(["rev-parse", "--is-inside-work-tree"], path) == "true"


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def _get_total_commits(cwd: Path) -> int:
    out = _run_git(["rev-list", "--count", "HEAD"], cwd)
    try:
        return int(out)
    except ValueError:
        return 0


def _get_branch(cwd: Path) -> str:
    return _run_git(["branch", "--show-current"], cwd)


def _get_repo_age(cwd: Path) -> str:
    return _run_git(["log", "--reverse", "--format=%ai", "--max-count=1"], cwd)


def _get_recent_commits(cwd: Path, count: int) -> list[dict[str, str]]:
    """Get recent commit summaries."""
    out = _run_git([
        "log", f"--max-count={count}",
        "--format=%H|%an|%ai|%s",
    ], cwd)
    commits = []
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0][:8],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            })
    return commits


def _get_file_change_counts(cwd: Path, count: int) -> list[FileChangeStats]:
    """Find the most frequently changed files in recent history."""
    out = _run_git([
        "log", f"--max-count={count * 5}",  # look at more commits for better stats
        "--name-only", "--format=",
    ], cwd)
    counter: Counter[str] = Counter()
    for line in out.splitlines():
        line = line.strip()
        if line:
            counter[line] += 1

    stats = []
    for path, changes in counter.most_common(count):
        stats.append(FileChangeStats(path=path, change_count=changes))
    return stats


def _get_contributors(cwd: Path, count: int) -> list[ContributorStats]:
    """Get contributor statistics."""
    out = _run_git([
        "shortlog", "-sne", "HEAD", f"--max-count={count * 3}",
    ], cwd)
    contributors: list[ContributorStats] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # Format: "  N\tName <email>"
        parts = line.split("\t", 1)
        if len(parts) == 2:
            try:
                num = int(parts[0].strip())
            except ValueError:
                continue
            name = parts[1].strip()
            contributors.append(ContributorStats(name=name, commits=num))
    contributors.sort(key=lambda c: -c.commits)
    return contributors[:count]


def _get_hotspots(cwd: Path) -> list[str]:
    """Detect hotspots: files with high churn (frequently changed)."""
    # Get files changed in the last 50 commits with shortstat
    out = _run_git([
        "log", "--max-count=50", "--name-only", "--format=",
    ], cwd)
    counter: Counter[str] = Counter()
    for line in out.splitlines():
        line = line.strip()
        if line:
            counter[line] += 1

    # Files changed more than 5 times in last 50 commits are hotspots
    hotspots = [path for path, count in counter.most_common(20) if count >= 3]
    return hotspots


def _get_file_contributors(cwd: Path, files: list[FileChangeStats]) -> None:
    """Get top contributors for each changed file."""
    for fstats in files:
        out = _run_git([
            "log", "--format=%an", f"--max-count=10", "--", fstats.path,
        ], cwd)
        counter: Counter[str] = Counter()
        for line in out.splitlines():
            line = line.strip()
            if line:
                counter[line] += 1
        fstats.contributors = [name for name, _ in counter.most_common(3)]


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def analyze_git(repo_path: Path, config: OnboardConfig) -> GitAnalysis | None:
    """Run git history analysis on a repository. Returns None if not a git repo."""
    if not _is_git_repo(repo_path):
        return None

    analysis = GitAnalysis(
        total_commits=_get_total_commits(repo_path),
        branch=_get_branch(repo_path),
        repo_age=_get_repo_age(repo_path),
        recent_commits=_get_recent_commits(repo_path, config.recent_commit_count),
        top_changed_files=_get_file_change_counts(repo_path, config.top_changed_files_count),
        contributors=_get_contributors(repo_path, 10),
        hotspots=_get_hotspots(repo_path),
    )

    # Enrich file stats with contributor info
    _get_file_contributors(repo_path, analysis.top_changed_files)

    return analysis
