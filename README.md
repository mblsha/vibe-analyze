vibe-analyze — High-recall Codebase Answering (CLI)

This CLI scans a repo, builds a compact project overview, enforces token budgets with headroom, performs hierarchical LLM-based selection (Gemini Flash 1M), and analyzes with Gemini 2.5 Pro 1M. Stdout prints the answer only; stderr emits diagnostics.

Quick start:
- Install: `pip install -e .`
- Env: set `GOOGLE_API_KEY` for Gemini.
- Run: `vibe-analyze --request "How does auth flow work?" --verbose`

See `vibe_analyze/cli.py` for available flags.

