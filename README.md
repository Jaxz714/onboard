# Onboard

Codebase onboarding agent -- point at any repo, get a comprehensive guide in 5 minutes.

Architecture maps, module explanations, dependency analysis, git history, and interactive Q&A powered by Claude.

## Installation

```bash
pip install .
```

Or install in development mode:

```bash
pip install -e .
```

Set your Anthropic API key for AI-powered features:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

### Generate an onboarding guide

```bash
# Quick scan (structure, dependencies, git history)
onboard scan ./my-project

# Deep analysis (reads files, generates AI summaries)
onboard scan ./my-project --deep

# Custom output path
onboard scan ./my-project --output docs/onboarding.md
```

### Interactive Q&A

```bash
# Interactive mode
onboard qa ./my-project

# Single question
onboard qa ./my-project "What does the router module do?"
```

### Recent changes (for returning developers)

```bash
onboard diff ./my-project
```

### Codebase statistics

```bash
onboard stats ./my-project
```

## What it does

1. **Repo Scanner** -- Walks the directory tree, categorizes files by type and purpose, parses common dependency files (package.json, requirements.txt, pyproject.toml, go.mod, Cargo.toml, pom.xml), identifies entry points, and detects architectural patterns (MVC, microservices, monorepo, etc.)

2. **Architecture Mapper** -- Groups files into logical modules, identifies entry points and key files, maps the dependency graph

3. **Dependency Analyzer** -- Parses npm, pip, Go, Cargo, and Maven dependency files with version info

4. **Git History Analysis** -- Finds most frequently changed files, key contributors per file, recent commit history, and detects hotspots (files with high churn)

5. **AI Summarizer** -- Claude reads key files and generates human-readable explanations of the project, each module, and suggests where to start

6. **Interactive Q&A** -- Ask natural language questions about the codebase and get answers grounded in the actual code

7. **Output** -- Comprehensive onboarding guide in Markdown

## Supported languages and frameworks

Works with any language. Special parsing for:
- Python (pyproject.toml, requirements.txt, Pipfile)
- JavaScript/TypeScript (package.json)
- Go (go.mod)
- Rust (Cargo.toml)
- Java (pom.xml)
- And any git repository

## Configuration

Create a `config/default.yaml` or use environment variables:

```yaml
model: "claude-sonnet-4-6"
max_tokens: 4096
temperature: 0.3
max_file_size: 100000
max_files_to_read: 50
```

## License

MIT
