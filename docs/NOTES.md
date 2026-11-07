# Notes

Deviations from `PLAN.md`, library quirks and environment facts.

## Environment (user's machine, 2026-11-07)

- Windows 11, Python 3.13.1 (project supports 3.11+), git 2.56.
- `uv` is not installed, so the project uses `python -m venv .venv` + `pip` (PLAN.md §1 fallback).
- GNU `make` is not installed on Windows. The `Makefile` targets are used in CI (Ubuntu); on
  Windows, run the commands from `CLAUDE.md` directly (or install make via `winget install GnuWin32.Make`).
- Docker and Ollama are not installed yet (needed from Phase 2 / Phase 3).
- `nvidia-smi` is available.

## Library versions at scaffold time

| Package | Version |
|---|---|
| langgraph | 1.2.20 |
| langchain-core | 1.7.6 |
| langchain-ollama | 1.1.0 |
| mcp | 2.3.0 |

## Quirks

- `typer`: an app with a single command collapses into that command; `simagent` defines an
  `@app.callback()` so subcommands always work.
- On Windows, `Path.write_text` writes CRLF. Scripts that generate committed files write with
  `newline="\n"` so `ruff format --check` and staleness tests behave the same on Linux and Windows.
