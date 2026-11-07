# CLAUDE.md

Project: Simulation Agent: natural language → sandboxed Python simulation code, with a
self-correction loop, an MCP server and an evaluation harness (Python, LangGraph, Docker, Ollama).
`SPEC.md` is the source of truth (what must be true). `PLAN.md` is the order of work.
Progress lives in `docs/PROGRESS.md`; deviations and library quirks in `docs/NOTES.md`.

## Autonomy
- Work through `PLAN.md` phase by phase **without asking for confirmation**, unless you are
  blocked or hit a checkpoint.
- **Stop only at:** CHECKPOINT A (end of Phase 2), CHECKPOINT B (before Phase 7), when a
  requirement in `SPEC.md` cannot be met as written, or when you would need a secret, a paid
  service, or to install something system-wide (Docker, Ollama, GPU drivers).
- When you stop: update `docs/PROGRESS.md` (done / next / open questions) and say exactly what the
  user needs to do.
- Start every session by reading `docs/PROGRESS.md` and `git log --oneline -20`.

## Git: clean, reviewable history
- One logical change per commit. Code and its tests go in the **same** commit.
- Conventional Commits with a scope: `feat(runner): …`, `fix(policy): …`, `test(agent): …`,
  `docs: …`, `chore: …`, `ci: …`, `build: …`, `refactor: …`, `data(eval): …`.
- Subject ≤ 72 chars, imperative mood, no trailing period. Add a body when the *why* isn't obvious
  (what changed and why, which SPEC IDs it covers).
- **Every commit must pass** `ruff check . && ruff format --check . && mypy src && pytest -q`.
  Run them before committing. Never commit a failing state, never `--no-verify`, no "WIP" or
  "fix typo in previous commit" chains: amend the last commit if it hasn't been pushed.
- Use the commit messages suggested in `PLAN.md` when they fit.
- Work on `main`. Do not push; the user pushes after reviewing.
- Never commit: `.env`, `runs/`, model files, caches, large binaries (> 1 MB) other than the
  committed docs images.

## Before writing code against a library
- LangGraph, LangChain integrations, the `mcp` SDK and Ollama change often. Check the installed
  version (`pip show`) and its real API (`help()`, official docs) first. Don't code from memory.
- If the installed API conflicts with the plan, follow the API and note it in `docs/NOTES.md`.

## Hard rules
- **Generated code only ever runs through a `Runner`** (Docker by default). Never `exec`/`eval`
  model output in the host process. The model never chooses limits or the runner.
- Sandbox flags in `SPEC.md` R-SBX-3 are mandatory; don't weaken them to make a test pass.
- **Never invent data:** no made-up material coefficients presented as real (cite or mark
  `"illustrative"`), no hand-typed expected values (generate them), no invented eval numbers,
  no `null` metrics replaced with guesses. README numbers come only from committed result files.
- Don't tune prompts against individual eval tasks (that's overfitting the benchmark). General
  prompt improvements are fine; log them in `docs/NOTES.md` with before/after numbers.
- Tests run offline with the `fake` provider; no network in tests. Docker tests are marked
  `@pytest.mark.docker`.
- Secrets only via `.env` (gitignored); keep `.env.example` complete. Never print key values.
- Windows + Linux: use `pathlib`, no shell-specific syntax in Python.

## Hardware facts (user's machine)
- Windows laptop, NVIDIA RTX 3050 Mobile, **4 GB VRAM**. Prefer ~1.5B–3B quantised models; ~7B
  only as an optional slow row. Keep context windows modest. Long eval runs need the user's go-ahead.

## Commands
- Install: `pip install -e ".[dev,ollama]"`
- Lint: `ruff check . && ruff format --check . && mypy src`
- Test: `pytest -q` (Docker tests: `pytest -q -m docker`)
- Sandbox image: `make sandbox-image`
- Health check: `simagent doctor`
- Offline demo: `simagent solve "transmission of 1 MeV photons through 5 cm of water" --provider fake`
- Eval: `python scripts/evaluate.py --provider ollama --model <tag> --mode repair --resume`
