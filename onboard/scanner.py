"""Directory and file scanner for codebase analysis.

Walks the directory tree, categorizes files by type and purpose,
parses dependency files, and identifies entry points.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None  # type: ignore[assignment]

from .config import OnboardConfig

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    """Metadata about a single file."""
    path: Path
    relative: str
    extension: str
    size: int
    category: str  # source, config, test, doc, build, data, other
    language: str | None = None


@dataclass
class DependencyInfo:
    """Parsed dependency information from a manifest file."""
    manager: str  # npm, pip, go, cargo, maven, etc.
    file: str
    dependencies: dict[str, str] = field(default_factory=dict)
    dev_dependencies: dict[str, str] = field(default_factory=dict)


@dataclass
class ScanResult:
    """Complete result of scanning a repository."""
    root: Path
    total_files: int = 0
    total_size: int = 0
    files: list[FileInfo] = field(default_factory=list)
    by_extension: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_language: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_category: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    directories: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    dependencies: list[DependencyInfo] = field(default_factory=list)
    test_dirs: list[str] = field(default_factory=list)
    detected_patterns: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_EXT_TO_LANG: dict[str, str] = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".c": "C", ".h": "C",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".scala": "Scala",
    ".r": "R", ".R": "R",
    ".lua": "Lua",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".dart": "Dart",
    ".vue": "Vue", ".svelte": "Svelte",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
    ".sql": "SQL",
    ".proto": "Protobuf",
    ".graphql": "GraphQL", ".gql": "GraphQL",
    ".md": "Markdown", ".rst": "reStructuredText",
    ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML", ".json": "JSON",
}

# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

_CONFIG_NAMES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "Pipfile", "Pipfile.lock", "pyproject.toml",
    "setup.py", "setup.cfg", "poetry.lock", "uv.lock",
    "go.mod", "go.sum", "Cargo.toml", "Cargo.lock",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "Gemfile.lock", "composer.json",
    "Makefile", "CMakeLists.txt",
    ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
    ".prettierrc", ".prettierrc.json", ".prettierrc.yml",
    "tsconfig.json", "tsconfig*.json",
    "babel.config.js", "babel.config.json", ".babelrc",
    "webpack.config.js", "vite.config.ts", "vite.config.js",
    "rollup.config.js", "esbuild.config.js",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".env.example", ".env.sample",
    "Procfile", "fly.toml", "render.yaml",
    "vercel.json", "netlify.toml",
}

_DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
_TEST_DIR_PATTERNS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "testing"}
_BUILD_DIRS = {"dist", "build", "out", "target", ".next", ".nuxt", "public", "static"}


def _classify_file(path: Path, rel: str) -> tuple[str, str | None]:
    """Return (category, language) for a file."""
    ext = path.suffix.lower()
    name = path.name.lower()
    parts = set(rel.lower().split("/"))

    # Language
    lang = _EXT_TO_LANG.get(ext) or _EXT_TO_LANG.get(path.suffix)

    # Test files
    if any(p in _TEST_DIR_PATTERNS for p in parts) or "test" in name or "spec" in name:
        return "test", lang

    # Config / manifest
    if name in {n.lower() for n in _CONFIG_NAMES}:
        return "config", lang
    if name.startswith(".") and ext in {".json", ".yml", ".yaml", ".js", ".ts", ".toml"}:
        return "config", lang

    # Documentation
    if ext in _DOC_EXTENSIONS:
        return "doc", lang

    # Build artifacts
    if any(p in _BUILD_DIRS for p in parts):
        return "build", lang

    # Source code
    if lang and ext in {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
                        ".kt", ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php",
                        ".swift", ".scala", ".dart", ".lua", ".r", ".vue", ".svelte"}:
        return "source", lang

    # Data
    if ext in {".json", ".yaml", ".yml", ".toml", ".xml", ".csv", ".sql", ".graphql", ".proto"}:
        return "data", lang

    # Web
    if ext in {".html", ".htm", ".css", ".scss", ".sass", ".less"}:
        return "source", lang

    return "other", lang


# ---------------------------------------------------------------------------
# Entry point detection
# ---------------------------------------------------------------------------

_ENTRY_POINT_PATTERNS = [
    (re.compile(r"^main\.(py|js|ts|go|rs|java|kt)$"), True),
    (re.compile(r"^app\.(py|js|ts)$"), True),
    (re.compile(r"^index\.(js|ts|jsx|tsx|mjs|cjs)$"), True),
    (re.compile(r"^manage\.py$"), True),
    (re.compile(r"^server\.(js|ts|py)$"), True),
    (re.compile(r"^Program\.cs$"), True),
    (re.compile(r"^cmd/.+\.go$"), True),
    (re.compile(r"^src/main\.(java|kt)$"), True),
    (re.compile(r"^lib/.+\.(py|rb|js|ts)$"), False),  # library entry
]


# ---------------------------------------------------------------------------
# Dependency parsers
# ---------------------------------------------------------------------------

def _parse_package_json(path: Path) -> DependencyInfo:
    with open(path) as f:
        data = json.load(f)
    return DependencyInfo(
        manager="npm",
        file=str(path),
        dependencies=data.get("dependencies", {}),
        dev_dependencies=data.get("devDependencies", {}),
    )


def _parse_requirements_txt(path: Path) -> DependencyInfo:
    deps: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            match = re.match(r"^([a-zA-Z0-9_.-]+)\s*(.*)", line)
            if match:
                name = match.group(1)
                version = match.group(2).strip().lstrip("=<>!~") or "*"
                deps[name] = version
    return DependencyInfo(manager="pip", file=str(path), dependencies=deps)


def _parse_pyproject_toml(path: Path) -> DependencyInfo:
    if tomllib is None:
        return DependencyInfo(manager="pip (pyproject)", file=str(path))
    with open(path, "rb") as f:
        data = tomllib.load(f)
    project = data.get("project", {})
    deps_list = project.get("dependencies", [])
    deps: dict[str, str] = {}
    for d in deps_list:
        match = re.match(r"^([a-zA-Z0-9_.-]+)\s*(.*)", d)
        if match:
            deps[match.group(1)] = match.group(2).strip() or "*"
    optional = data.get("project", {}).get("optional-dependencies", {})
    dev_deps: dict[str, str] = {}
    for group_deps in optional.values():
        if isinstance(group_deps, list):
            for d in group_deps:
                match = re.match(r"^([a-zA-Z0-9_.-]+)\s*(.*)", d)
                if match:
                    dev_deps[match.group(1)] = match.group(2).strip() or "*"
    return DependencyInfo(manager="pip (pyproject)", file=str(path), dependencies=deps, dev_dependencies=dev_deps)


def _parse_go_mod(path: Path) -> DependencyInfo:
    deps: dict[str, str] = {}
    with open(path) as f:
        in_require = False
        for line in f:
            line = line.strip()
            if line.startswith("require ("):
                in_require = True
                continue
            if line == ")":
                in_require = False
                continue
            if in_require or line.startswith("require "):
                parts = line.replace("require ", "").strip().split()
                if len(parts) >= 2:
                    deps[parts[0]] = parts[1]
    return DependencyInfo(manager="go", file=str(path), dependencies=deps)


def _parse_cargo_toml(path: Path) -> DependencyInfo:
    if tomllib is None:
        return DependencyInfo(manager="cargo", file=str(path))
    with open(path, "rb") as f:
        data = tomllib.load(f)
    deps = {k: (v if isinstance(v, str) else v.get("version", "*"))
            for k, v in data.get("dependencies", {}).items()}
    dev_deps = {k: (v if isinstance(v, str) else v.get("version", "*"))
                for k, v in data.get("dev-dependencies", {}).items()}
    return DependencyInfo(manager="cargo", file=str(path), dependencies=deps, dev_dependencies=dev_deps)


def _parse_pom_xml(path: Path) -> DependencyInfo:
    """Best-effort pom.xml dependency extraction without lxml."""
    deps: dict[str, str] = {}
    try:
        text = path.read_text()
        for match in re.finditer(
            r"<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>"
            r"(?:\s*<version>([^<]+)</version>)?",
            text,
        ):
            artifact = match.group(2)
            version = match.group(3) or "*"
            deps[artifact] = version
    except Exception:
        pass
    return DependencyInfo(manager="maven", file=str(path), dependencies=deps)


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------

def _detect_patterns(dirs: set[str], files: list[FileInfo]) -> list[str]:
    patterns: list[str] = []

    # Monorepo
    pkg_jsons = [f for f in files if f.path.name == "package.json"]
    if len(pkg_jsons) > 2:
        patterns.append("monorepo")

    # MVC
    lower_dirs = {d.lower() for d in dirs}
    if {"models", "views", "controllers"} & lower_dirs:
        patterns.append("MVC")

    # Microservices
    if "services" in lower_dirs or "microservices" in lower_dirs:
        patterns.append("microservices")

    # Monolith / framework patterns
    if "src" in lower_dirs:
        patterns.append("src-based layout")
    if "app" in lower_dirs:
        patterns.append("app directory")
    if "lib" in lower_dirs:
        patterns.append("lib directory")
    if "cmd" in lower_dirs and "internal" in lower_dirs:
        patterns.append("Go standard layout")
    if "packages" in lower_dirs or "apps" in lower_dirs:
        patterns.append("workspace / monorepo")

    # Testing
    test_files = [f for f in files if f.category == "test"]
    if test_files:
        patterns.append(f"testing ({len(test_files)} test files)")

    # CI/CD
    ci_files = [f for f in files if ".github" in f.relative or ".gitlab-ci" in f.relative or "Jenkinsfile" in f.relative]
    if ci_files:
        patterns.append("CI/CD configured")

    # Docker
    docker_files = [f for f in files if "Dockerfile" in f.path.name or "docker-compose" in f.path.name.lower()]
    if docker_files:
        patterns.append("Docker")

    return patterns


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def scan_repository(root: Path, config: OnboardConfig) -> ScanResult:
    """Walk the repository and produce a ScanResult."""
    root = root.resolve()
    result = ScanResult(root=root)

    ignored_dirs = set(config.ignored_dirs)
    all_dirs: set[str] = set()

    for dirpath, dirnames, filenames in _walk(root, ignored_dirs):
        rel_dir = str(dirpath.relative_to(root))
        if rel_dir == ".":
            rel_dir = ""
        all_dirs.add(rel_dir)

        for fname in filenames:
            fpath = dirpath / fname
            rel = str(fpath.relative_to(root))

            # Size filter
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size > config.max_file_size:
                continue

            ext = fpath.suffix.lower()
            category, language = _classify_file(fpath, rel)

            fi = FileInfo(
                path=fpath,
                relative=rel,
                extension=ext,
                size=size,
                category=category,
                language=language,
            )
            result.files.append(fi)
            result.total_files += 1
            result.total_size += size
            result.by_extension[ext] = result.by_extension.get(ext, 0) + 1
            if language:
                result.by_language[language] += 1
            result.by_category[category] += 1

            # Entry points
            for pattern, _ in _ENTRY_POINT_PATTERNS:
                if pattern.search(rel.lower().replace("\\", "/")):
                    result.entry_points.append(rel)
                    break

            # Test directories
            if category == "test":
                test_dir = str(fpath.parent.relative_to(root))
                if test_dir not in result.test_dirs:
                    result.test_dirs.append(test_dir)

            # Config files
            if category == "config":
                result.config_files.append(rel)

    # Sort directories
    result.directories = sorted(all_dirs)

    # Parse dependency files
    dep_parsers = {
        "package.json": _parse_package_json,
        "requirements.txt": _parse_requirements_txt,
        "pyproject.toml": _parse_pyproject_toml,
        "go.mod": _parse_go_mod,
        "Cargo.toml": _parse_cargo_toml,
        "pom.xml": _parse_pom_xml,
    }
    for fi in result.files:
        fname = fi.path.name
        if fname in dep_parsers:
            try:
                result.dependencies.append(dep_parsers[fname](fi.path))
            except Exception:
                pass

    # Detect architectural patterns
    result.detected_patterns = _detect_patterns(all_dirs, result.files)

    return result


def _walk(root: Path, ignored_dirs: set[str]):
    """os.walk wrapper that prunes ignored directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignored_dirs]
        yield Path(dirpath), dirnames, filenames


def read_file_contents(path: Path, max_size: int = 50_000) -> str | None:
    """Read a file's text contents, returning None on failure."""
    try:
        if path.stat().st_size > max_size:
            return None
        return path.read_text(errors="replace")
    except Exception:
        return None
