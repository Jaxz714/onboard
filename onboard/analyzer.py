"""Architecture and dependency analysis.

Identifies modules, entry points, data flow patterns,
and builds a structural map of the codebase.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .scanner import ScanResult, FileInfo


@dataclass
class ModuleInfo:
    """A logical module / package in the codebase."""
    name: str
    path: str
    file_count: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    purpose: str = ""
    key_files: list[str] = field(default_factory=list)
    is_entry_point: bool = False
    is_test: bool = False


@dataclass
class ArchitectureMap:
    """High-level structural map of the codebase."""
    modules: list[ModuleInfo] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    dependency_summary: dict[str, list[str]] = field(default_factory=dict)
    language_breakdown: dict[str, int] = field(default_factory=dict)
    category_breakdown: dict[str, int] = field(default_factory=dict)
    top_level_dirs: list[str] = field(default_factory=list)
    overview: str = ""


# ---------------------------------------------------------------------------
# Module extraction
# ---------------------------------------------------------------------------

def _extract_modules(scan: ScanResult) -> list[ModuleInfo]:
    """Group files into logical modules based on directory structure."""
    module_files: dict[str, list[FileInfo]] = defaultdict(list)

    for fi in scan.files:
        if fi.category in ("build", "other"):
            continue
        parts = fi.relative.split("/")
        # Use first directory as module, or root for flat files
        module_name = parts[0] if len(parts) > 1 else "(root)"
        module_files[module_name].append(fi)

    modules: list[ModuleInfo] = []
    entry_set = set(scan.entry_points)

    for name, files in sorted(module_files.items()):
        langs: dict[str, int] = defaultdict(int)
        key_files: list[str] = []
        is_entry = False

        for fi in files:
            if fi.language:
                langs[fi.language] += 1
            if fi.relative in entry_set:
                is_entry = True
                key_files.append(fi.relative)
            # Heuristic: key files are configs, entry points, or init files
            if fi.path.name in ("__init__.py", "index.ts", "index.js", "mod.rs",
                                "lib.rs", "go.mod", "Cargo.toml", "package.json"):
                key_files.append(fi.relative)

        mi = ModuleInfo(
            name=name,
            path=name if name != "(root)" else ".",
            file_count=len(files),
            languages=dict(langs),
            key_files=list(set(key_files))[:10],
            is_entry_point=is_entry,
            is_test=any(f.category == "test" for f in files),
        )

        # Guess purpose from name and contents
        mi.purpose = _guess_purpose(name, files)

        modules.append(mi)

    return modules


_PURPOSE_HINTS: dict[str, str] = {
    "src": "Main source code",
    "lib": "Library / shared code",
    "app": "Application code",
    "cmd": "CLI entry points / commands",
    "internal": "Internal packages (not exported)",
    "pkg": "Reusable packages",
    "api": "API layer",
    "routes": "HTTP route definitions",
    "controllers": "Request handlers / controllers",
    "models": "Data models / ORM definitions",
    "views": "View templates / UI components",
    "services": "Business logic services",
    "middleware": "HTTP middleware",
    "utils": "Utility functions",
    "helpers": "Helper functions",
    "config": "Configuration files",
    "test": "Test files",
    "tests": "Test files",
    "__tests__": "Test files",
    "spec": "Test specs",
    "docs": "Documentation",
    "scripts": "Build / utility scripts",
    "migrations": "Database migrations",
    "db": "Database layer",
    "store": "State management",
    "hooks": "React hooks / lifecycle hooks",
    "components": "UI components",
    "pages": "Page components / routes",
    "public": "Static assets",
    "static": "Static assets",
    "assets": "Assets (images, fonts, etc.)",
    "tools": "Developer tooling",
    "deploy": "Deployment configuration",
    "ci": "CI/CD configuration",
    "github": "GitHub configuration",
    "bin": "Executable scripts",
    "cmd": "CLI command definitions",
    "proto": "Protocol buffer definitions",
    "types": "TypeScript type definitions",
    "schemas": "Data schemas",
    "workers": "Background workers",
    "jobs": "Background jobs",
    "tasks": "Task definitions",
    "plugins": "Plugin system",
    "extensions": "Extensions / plugins",
    "providers": "External service providers",
    "adapters": "Adapter pattern implementations",
    "repositories": "Data access layer",
    "dto": "Data transfer objects",
    "entities": "Domain entities",
    "factories": "Factory pattern implementations",
}


def _guess_purpose(name: str, files: list[FileInfo]) -> str:
    """Guess the purpose of a module from its name and files."""
    lower = name.lower()
    if lower in _PURPOSE_HINTS:
        return _PURPOSE_HINTS[lower]

    # Check file extensions for hints
    exts = {f.extension for f in files}
    if ".sql" in exts:
        return "Database / SQL"
    if ".proto" in exts:
        return "Protocol buffer definitions"
    if ".graphql" in exts:
        return "GraphQL schema"

    return ""


# ---------------------------------------------------------------------------
# Dependency summary
# ---------------------------------------------------------------------------

def _build_dependency_summary(scan: ScanResult) -> dict[str, list[str]]:
    """Build a summary of dependencies grouped by manager."""
    summary: dict[str, list[str]] = {}
    for dep in scan.dependencies:
        names = list(dep.dependencies.keys())[:20]
        extra = f" (+{len(dep.dependencies) - 20} more)" if len(dep.dependencies) > 20 else ""
        summary[f"{dep.manager} ({dep.file})"] = [f"{n} {dep.dependencies[n]}" for n in names]
        if extra:
            summary[f"{dep.manager} ({dep.file})"].append(extra)
    return summary


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze_architecture(scan: ScanResult) -> ArchitectureMap:
    """Produce an ArchitectureMap from a ScanResult."""
    modules = _extract_modules(scan)

    arch = ArchitectureMap(
        modules=modules,
        entry_points=scan.entry_points,
        patterns=scan.detected_patterns,
        dependency_summary=_build_dependency_summary(scan),
        language_breakdown=dict(scan.by_language),
        category_breakdown=dict(scan.by_category),
        top_level_dirs=[d for d in scan.directories if "/" not in d and d != ""],
    )

    # Build a text overview
    langs = sorted(scan.by_language.items(), key=lambda x: -x[1])
    lang_str = ", ".join(f"{l} ({c} files)" for l, c in langs[:5]) if langs else "N/A"
    arch.overview = (
        f"This repository contains {scan.total_files} files "
        f"({scan.total_size / 1024:.0f} KB). "
        f"Primary languages: {lang_str}. "
        f"Architecture patterns: {', '.join(scan.detected_patterns) or 'none detected'}. "
        f"Entry points: {', '.join(scan.entry_points[:5]) or 'none detected'}."
    )

    return arch
