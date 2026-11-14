# Lean Agent Browser: notes for Claude sessions

Read `docs/PROJECT_MEMORY.md` first. It covers what this is, the key results, the decisions, what is
installed where on this Mac, the Obscura quirks, and what's next.

- **Commits:** no Claude co-author trailers or attribution lines. The repo-local git email is the user's
  GitHub noreply address.
- **Autonomy:** commit and push to origin/main after each logical step, and make the small choices yourself.
- **Platform:** macOS (Apple Silicon) only.
- **Tests:** `.venv/bin/python -m pytest -q` (both engines, local fixture site).
- **Evals:** `python -m evals.claude_driver` (uses `claude -p`, no API key).
- **Secrets:** never print or commit `.env`.
