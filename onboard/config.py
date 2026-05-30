"""Configuration loading and defaults for Onboard."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "default.yaml"


@dataclass
class OnboardConfig:
    """Runtime configuration for an Onboard run."""

    # --- AI settings -----------------------------------------------------------
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.3

    # --- Scanner settings ------------------------------------------------------
    max_file_size: int = 100_000  # bytes – skip files larger than this
    ignored_dirs: list[str] = field(default_factory=lambda: [
        ".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
        "build", ".tox", ".mypy_cache", ".pytest_cache", "target",
        ".next", ".nuxt", "coverage", ".idea", ".vscode",
    ])
    ignored_files: list[str] = field(default_factory=lambda: [
        ".DS_Store", "Thumbs.db", "*.pyc", "*.pyo", "*.class", "*.o",
        "*.so", "*.dylib",
    ])
    # Patterns for entry point detection
    entry_point_patterns: list[str] = field(default_factory=lambda: [
        "main.py", "app.py", "manage.py", "index.js", "index.ts",
        "main.go", "main.rs", "cmd/", "src/main.java",
    ])

    # --- Deep analysis settings ------------------------------------------------
    max_files_to_read: int = 50  # max files to read contents of in deep mode
    max_file_read_size: int = 50_000  # bytes per file when reading

    # --- Git analysis settings -------------------------------------------------
    recent_commit_count: int = 30
    top_changed_files_count: int = 10

    # --- Output settings -------------------------------------------------------
    output_file: str = "ONBOARDING.md"

    # --- API key ---------------------------------------------------------------
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))

    @classmethod
    def load(cls, config_path: Path | str | None = None) -> "OnboardConfig":
        """Load configuration from YAML file, falling back to defaults."""
        cfg = cls()
        path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH

        if path.exists():
            with open(path) as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
            for key, value in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)

        # Environment variable overrides
        if api_key := os.environ.get("ANTHROPIC_API_KEY"):
            cfg.anthropic_api_key = api_key
        if model := os.environ.get("ONBOARD_MODEL"):
            cfg.model = model

        return cfg
