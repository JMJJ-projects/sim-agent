# CLAUDE.md

Project: Simulation Agent: natural language → sandboxed Python simulation code, with a
self-correction loop, a verification step, an MCP server and an evaluation harness (Python,
LangGraph, Docker, Ollama; OpenMC in Part B).
`SPEC.md` is the source of truth (what must be true). The current work is **v2**, described in
`PLAN-v2.md` (order of work). v1's `PLAN.md` is history: don't redo it.
Progress lives in `docs/PROGRESS.md`; deviations and library quirks in `docs/NOTES.md`.

## Autonomy
- Work through `PLAN-v2.md` phase by phase **without asking for confirmation**, unless you are
  blocked or reach a checkpoint.
- **Stop only at:** CHECKPOINTS A–G in `PLAN-v2.md`, when a requirement in `SPEC.md` can't be met
  as written, or when you'd need a secret, a paid service, a large download, or a system-wide
  install.
- **Part B (Phases 8–10) starts only after the user explicitly says go at CHECKPOINT D.**
- When you stop: update `docs/PROGRESS.md` (done / next / open questions) and say exactly what the
  user needs to do, step by step, with commands they can copy.
- Start every session by reading `docs/PROGRESS.md` and `git log --oneline -20`.

## Git: clean, reviewable history
- One logical change per commit; code and its tests in the **same** commit.
- Conventional Commits with a scope: `feat(verify): …`, `feat(eval): …`, `fix(policy): …`,
  `test(sandbox): …`, `data(eval): …`, `docs: …`, `docs(spec): …`, `build(sandbox): …`, `ci: …`,
  `chore: …`, `refactor: …`. Subject ≤ 72 chars, imperative, no trailing period; add a body when
  the *why* isn't obvious and name the SPEC IDs covered.
- **Every commit passes** `ruff check . && ruff format --check . && mypy src && pytest -q`. Never
  commit a failing state, never `--no-verify`, no "WIP" commits. Amend the last commit only if it
  hasn't been pushed.
- Use the commit messages suggested in `PLAN-v2.md` when they fit.
- Work on `main`. **Do not push and do not push tags**; the user pushes after reviewing.
- **Push points:** at every checkpoint, ask the user to push (give the exact command, including
  tags when one was created) and wait until CI is green on GitHub before continuing. If CI fails,
  fix it with a normal `fix:`/`ci:` commit; never rewrite pushed history (no force-push, no amending
  or rebasing pushed commits).
- Results files: one commit per model (or per block), never mixed with code changes. Regenerated
  reports and charts go in their own `docs:` commit after the code that generates them.
- Never commit: `.env`, `runs/`, model files, nuclear data, caches, files > 1 MB other than
  committed docs images and results files.

## Before writing code against a library
- LangGraph, LangChain integrations, Ollama (including `/api/ps`), the `mcp` SDK, Groq limits and
  OpenMC change. Check the installed version and its real API (`pip show`, `help()`, official
  docs) first. Never code from memory.
- If the real API conflicts with the plan, follow the API and note it in `docs/NOTES.md`.

## Hard rules (v1 rules still apply)
- **Generated code only ever runs through a `Runner`** (Docker by default). Never `exec`/`eval`
  model output in the host process. The model never chooses the runner, backend, policy profile,
  timeout or limits. Sandbox flags (R-SBX-3) are mandatory for every image, OpenMC included.
- **Never invent data:** no made-up coefficients, no hand-typed expected values, no invented eval
  numbers, no guessed metrics. README numbers come only from committed results files.
- **Benchmark integrity:**
  - The held-out set is frozen at tag `heldout-frozen` (after CHECKPOINT A). Never edit it; a
    broken task is excluded with the reason, never fixed.
  - Never change a check, prompt or threshold because of a held-out result. If it happens anyway,
    say so in the report: the set is no longer held out.
  - Don't tune prompts or checks against individual tasks. Verifier checks must be general
    (physics, units, consistency with the request and the trace), never task-specific.
  - `verify` and `repair` modes get the **same attempt budget**.
  - Never call a difference an improvement when its 95 % CI includes 0.
  - Report the true headline even if it is "verification didn't help measurably".
- **The trace is the simulator's record, not the model's claim.** Never let generated code write
  or alter it.
- Tests run offline with the `fake` provider; no network in `pytest`. Docker tests are marked
  `@pytest.mark.docker`; OpenMC tests also need a marker and skip cleanly without image or data.
- Secrets only via `.env` (gitignored); keep `.env.example` complete. Never print key values.
- Windows + Linux: `pathlib`, no shell-specific syntax in Python.

## Hardware facts (user's machine)
- Windows laptop, Docker Desktop (WSL2), Ollama, NVIDIA RTX 3050 Mobile with **4 GB VRAM**.
  1.5B–3B Q4 models fit; 3B Q8 is tight; 7B means partial offload (slow). Keep `num_ctx` modest.
- Long runs and downloads need the user's go-ahead (checkpoints C, E, F). Give ETAs from a timing
  probe, not guesses. Commit results per model as each finishes.
- `make` may not be installed on Windows: document plain commands next to make targets.

## Commands
- Install: `pip install -e ".[dev,ollama]"`
- Lint: `ruff check . && ruff format --check . && mypy src`
- Test: `pytest -q` (Docker tests: `pytest -q -m docker`)
- Sandbox image: `make sandbox-image` (OpenMC: `make sandbox-openmc-image`, Part B)
- Health check: `simagent doctor`
- Offline demo: `simagent solve "transmission of 1 MeV photons through 5 cm of water" --provider fake --mode verify`
- Eval: `python scripts/evaluate.py --provider ollama --model <tag> --mode verify --task-set all --seeds 0,1,2,3,4 --resume`
- Benchmark plan: `python scripts/bench.py --plan data/bench_plan_v2.json`
