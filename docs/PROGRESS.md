# Progress

Living log of where the project stands. Updated at the end of every session and at checkpoints.

## Status: Phase 4 (agent graph) in progress (2026-11-07)

Checkpoint A reviewed by the user: Docker image built, 14/14 Docker tests pass locally.

## Done

- **Phase 0, scaffold:** git repo, `src/` layout (`photonsim`, `simagent`), `pyproject.toml`
  (hatchling, extras `ollama`/`groq`/`openai`/`dev`), ruff + mypy --strict + pytest, Makefile,
  `.gitignore` (keeps `.env` out), `.env.example`, MIT licence, CI workflow.
- **Phase 1, `photonsim`:**
  - Material data for water, polyethylene, concrete, aluminium, iron and lead (0.1–10 MeV),
    generated from NIST SRD 126 by `scripts/build_materials.py`, with citations (R-SIM-3).
  - `Layer`/`Slab` with validated inputs (R-SIM-5), vectorised transport (R-SIM-1/2),
    `simulate`/`sweep`/`Result` API (R-SIM-4).
  - Physics tests: Beer–Lambert within 4σ for pure absorbers (R-SIM-7), determinism, monotonic
    transmission, build-up, 1e5 photons × 3 layers in ≈0.05 s (limit 2 s, R-SIM-6).
  - `docs/api.md` generated from docstrings (~850 tokens) + staleness test (R-SIM-8).
- **Phase 2, policy and sandbox:**
  - `simagent_io.submit()` (R-SBX-7).
  - AST allow-list policy with repair-ready messages (R-POL-1..4).
  - `sandbox/Dockerfile` (pinned base image and wheels, non-root uid 10001) and in-image
    launcher (R-SBX-2).
  - `Runner`/`RunResult` + `DockerRunner` with every R-SBX-3 flag, timeout kill, output caps
    (R-SBX-1, 3, 4, 6). Command-line flags are unit-tested without Docker.
  - 14 Docker isolation tests (network, env, read-only FS, tmpfs size, non-root/caps, timeout,
    memory, fork bomb, output cap, malicious script with policy disabled) (R-SBX-3..7, R-POL-5).
  - `LocalRunner` behind `--unsafe-local` / `SIMAGENT_UNSAFE_LOCAL=1` (R-SBX-8).
  - `simagent run-script` and `simagent doctor` (R-CLI-2, R-CLI-3, R-CLI-4).
  - CI `sandbox` job builds the image and runs the Docker tests; it fails instead of skipping
    when Docker is not ready (R-SBX-9).
- Local state: 179 tests pass, 14 Docker tests skipped (no Docker here), coverage 97 %.

- **Checkpoint A follow-up:** `fix(policy)` rejects dangerous modules reached through allowed
  modules' attributes (`matplotlib.os`, `matplotlib.subprocess`, ...) and exec/spawn/fork.
- **Phase 3, LLM layer:** provider factory (ollama/groq/openai/fake), scripted fake model with a
  built-in buggy-then-fixed demo, per-call metrics (tokens, TTFT, latency, tok/s; null when not
  reported), prompts (system + API + result contract, delimited request, repair), and single
  code-block extraction with refusals. Manual check with `qwen2.5-coder:3b`: code block + metrics
  returned (see NOTES.md).

## Next

- Phase 4: agent state, nodes, graph, artifacts (incl. small PNGs from /out, requested at
  Checkpoint A), `simagent solve`, graph diagram.

## Open questions

- None.
