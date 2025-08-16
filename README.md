vibe-analyze — High-recall Codebase Answering (CLI)

This CLI scans a repo, builds a compact project overview, enforces token budgets with headroom, performs hierarchical LLM-based selection (Gemini Flash 1M), and analyzes with Gemini 2.5 Pro 1M. Stdout prints the answer only; stderr emits diagnostics.

Quick start (uv):
- Install uv: see https://github.com/astral-sh/uv
- Create venv and install deps: `uv sync --extra test --extra lint`
- Env: set `GOOGLE_API_KEY` for Gemini (or use a dummy for tests).
- Run CLI: `uv run vibe-analyze --request "How does auth flow work?" --verbose`
- Run lints: `uv run ruff check && uv run ruff format --check`
- Run tests: `uv run -m pytest -q`

Pre-commit:
- Install hooks: `uv run pre-commit install`
- Run all hooks: `uv run pre-commit run -a`

Determinism:
- CI uses `uv run` for tools (Ruff, mypy, pytest) so versions come from `uv.lock`.
- `pyproject.toml` pins `[tool.uv] required-version` to ensure a compatible uv.

See `src/vibe_analyze/cli.py` for available flags.

CI: GitHub Actions uses `astral-sh/setup-uv@v6` to run tests across Python 3.9–3.12.
