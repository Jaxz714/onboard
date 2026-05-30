"""AI summarization engine using the Anthropic Claude API.

Reads key files and generates human-readable explanations
of the codebase, modules, and architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from .config import OnboardConfig
from .scanner import ScanResult, read_file_contents
from .analyzer import ArchitectureMap
from .git_analyzer import GitAnalysis


@dataclass
class AISummary:
    """AI-generated summaries of the codebase."""
    overview: str = ""
    module_summaries: dict[str, str] = field(default_factory=dict)
    getting_started: str = ""
    architecture_notes: str = ""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_context(scan: ScanResult, arch: ArchitectureMap, git: GitAnalysis | None) -> str:
    """Build a text context block from scan + architecture data."""
    lines: list[str] = []

    lines.append("## Repository Overview")
    lines.append(arch.overview)
    lines.append("")

    lines.append("## Directory Structure (top-level)")
    for d in arch.top_level_dirs:
        lines.append(f"  - {d}/")
    lines.append("")

    lines.append("## Entry Points")
    for ep in arch.entry_points[:10]:
        lines.append(f"  - {ep}")
    lines.append("")

    lines.append("## Architecture Patterns")
    for p in arch.patterns:
        lines.append(f"  - {p}")
    lines.append("")

    lines.append("## Language Breakdown")
    for lang, count in sorted(arch.language_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"  - {lang}: {count} files")
    lines.append("")

    if arch.dependency_summary:
        lines.append("## Dependencies")
        for manager, deps in arch.dependency_summary.items():
            lines.append(f"  {manager}:")
            for d in deps[:10]:
                lines.append(f"    - {d}")
        lines.append("")

    lines.append("## Modules")
    for mod in arch.modules:
        marker = " [ENTRY]" if mod.is_entry_point else ""
        marker += " [TEST]" if mod.is_test else ""
        lines.append(f"  - {mod.name} ({mod.file_count} files){marker}")
        if mod.purpose:
            lines.append(f"    Purpose: {mod.purpose}")
    lines.append("")

    if git:
        lines.append("## Git Info")
        lines.append(f"  Branch: {git.branch}")
        lines.append(f"  Total commits: {git.total_commits}")
        if git.top_changed_files:
            lines.append("  Most changed files:")
            for fs in git.top_changed_files[:5]:
                lines.append(f"    - {fs.path} ({fs.change_count} changes)")
        if git.hotspots:
            lines.append(f"  Hotspots: {', '.join(git.hotspots[:5])}")

    return "\n".join(lines)


def _read_key_files(scan: ScanResult, config: OnboardConfig) -> str:
    """Read contents of key files (entry points, configs, init files)."""
    key_names = {
        "README.md", "README.rst", "README",
        "__init__.py", "index.ts", "index.js", "main.py", "main.go",
        "app.py", "server.py", "manage.py", "mod.rs", "lib.rs",
        "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
        "Dockerfile", "docker-compose.yml",
    }

    read_count = 0
    blocks: list[str] = []

    # Prioritize entry points and config files
    priority_files = [f for f in scan.files if f.path.name in key_names or f.relative in scan.entry_points]
    priority_files.sort(key=lambda f: (
        0 if f.relative in scan.entry_points else
        1 if f.category == "config" else
        2 if f.path.name.startswith("README") else
        3
    ))

    for fi in priority_files:
        if read_count >= config.max_files_to_read:
            break
        content = read_file_contents(fi.path, config.max_file_read_size)
        if content:
            blocks.append(f"--- File: {fi.relative} ---\n{content}\n")
            read_count += 1

    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Claude API calls
# ---------------------------------------------------------------------------

def _call_claude(client: anthropic.Anthropic, config: OnboardConfig,
                 system: str, user_message: str) -> str:
    """Make a single Claude API call."""
    response = client.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    # Extract text from response
    text_parts = []
    for block in response.content:
        if hasattr(block, "text"):
            text_parts.append(block.text)
    return "\n".join(text_parts)


# ---------------------------------------------------------------------------
# Main summarization
# ---------------------------------------------------------------------------

def generate_summary(
    scan: ScanResult,
    arch: ArchitectureMap,
    git: GitAnalysis | None,
    config: OnboardConfig,
) -> AISummary:
    """Generate AI summaries of the codebase."""
    if not config.anthropic_api_key:
        return AISummary(
            overview="[AI summary unavailable — set ANTHROPIC_API_KEY to enable]",
            getting_started="[Set ANTHROPIC_API_KEY to get AI-generated onboarding guidance]",
        )

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    context = _build_context(scan, arch, git)
    file_contents = _read_key_files(scan, config)

    summary = AISummary()

    # 1. Project overview
    system_prompt = (
        "You are a senior software engineer writing onboarding documentation. "
        "Given a codebase's structure and key file contents, write a concise overview "
        "explaining what this project is, what it does, and what technologies it uses. "
        "Be specific and practical. Write in plain English. 2-4 paragraphs."
    )
    user_msg = f"Here is the repository structure and metadata:\n\n{context}\n\nKey file contents:\n{file_contents}"
    summary.overview = _call_claude(client, config, system_prompt, user_msg)

    # 2. Architecture notes
    system_prompt = (
        "You are a senior software engineer. Based on the codebase structure, explain "
        "the architecture: how the code is organized, what patterns are used, how data flows, "
        "and what the key design decisions are. Be practical and specific. 2-4 paragraphs."
    )
    summary.architecture_notes = _call_claude(client, config, system_prompt, user_msg)

    # 3. Getting started guide
    system_prompt = (
        "You are a senior software engineer writing a 'Getting Started' guide for new developers. "
        "Based on the codebase structure, suggest:\n"
        "1. What to read first\n"
        "2. Where to start making changes\n"
        "3. How to run the project\n"
        "4. Key concepts to understand\n"
        "Be specific to this codebase. 2-4 paragraphs."
    )
    summary.getting_started = _call_claude(client, config, system_prompt, user_msg)

    # 4. Module summaries (for the top modules by file count)
    top_modules = sorted(arch.modules, key=lambda m: -m.file_count)[:8]
    for mod in top_modules:
        if mod.name in ("(root)",):
            continue
        mod_files = [f for f in scan.files if f.relative.startswith(mod.path) and mod.path != "."]
        mod_context = f"Module: {mod.name} ({mod.file_count} files, languages: {mod.languages})\n"
        if mod.purpose:
            mod_context += f"Likely purpose: {mod.purpose}\n"
        mod_context += "Files:\n"
        for f in mod_files[:20]:
            mod_context += f"  - {f.relative} ({f.size} bytes)\n"

        # Try to read a few key files from this module
        mod_contents = ""
        for f in mod_files[:5]:
            content = read_file_contents(f.path, 10_000)
            if content:
                mod_contents += f"\n--- {f.relative} ---\n{content[:3000]}\n"

        system_prompt = (
            "You are a senior software engineer. Write a brief explanation of this code module: "
            "what it does, its key components, and how it connects to the rest of the project. "
            "Be specific and practical. 1-2 paragraphs."
        )
        summary.module_summaries[mod.name] = _call_claude(
            client, config, system_prompt,
            f"{mod_context}\n{mod_contents}",
        )

    return summary


def answer_question(
    question: str,
    context: str,
    file_contents: str,
    config: OnboardConfig,
) -> str:
    """Answer a question about the codebase using Claude."""
    if not config.anthropic_api_key:
        return "[Set ANTHROPIC_API_KEY to enable AI-powered Q&A]"

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    system_prompt = (
        "You are a senior software engineer helping someone understand a codebase. "
        "Answer their question based on the repository structure and file contents provided. "
        "Be specific, practical, and cite specific files or modules when possible. "
        "If you're not sure, say so."
    )
    user_msg = (
        f"Repository context:\n{context}\n\n"
        f"Relevant file contents:\n{file_contents}\n\n"
        f"Question: {question}"
    )
    return _call_claude(client, config, system_prompt, user_msg)
