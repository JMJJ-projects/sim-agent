# Progress

Living log of where the project stands. Updated at the end of every session and at checkpoints.

## Status: CHECKPOINT A (end of Phase 2), waiting for user review (2026-11-07)

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

## Not yet verified (needs Docker)

The Phase 2 exit criterion "all sandbox tests pass locally and in CI" is **not met yet**: Docker
is not installed on this machine, so the image has never been built and the 14 isolation tests
have never run. The Dockerfile pins were checked against Docker Hub and PyPI (tags and cp312
manylinux wheels exist), but a real build may still need fixes.

## What the user needs to do (Checkpoint A)

1. **Install Docker Desktop** (WSL2 backend) and start it. Check: `docker version`.
2. Build the image (no `make` on Windows, so run the command directly):
   `docker build -f sandbox/Dockerfile -t simagent-sandbox .`
3. Run the isolation tests: `.venv\Scripts\python -m pytest -q -m docker -rs`
   and `simagent doctor` (should show docker + sandbox image as ok).
4. **Review the sandbox before any model-generated code runs:**
   - flags: `src/simagent/runners/docker.py` → `DockerRunner.command`
   - image: `sandbox/Dockerfile`, `sandbox/launch.py`
   - policy: `src/simagent/policy.py`
   - tests: `tests/test_sandbox.py`, `tests/test_runner_unit.py`, `tests/test_policy.py`
5. Optionally push to GitHub so CI runs the `sandbox` job on Ubuntu.
6. Pull the Ollama models for Phase 3/4 (an Ollama server is already running here with no models
   pulled), e.g. `ollama pull qwen2.5-coder:3b` (exact tags are chosen and logged in Phase 3).
7. Say "continue" to start Phase 3 (LLM layer).

## Next

- Phase 3: provider factory, scripted `fake` provider + offline demo script, metrics (TTFT,
  tokens, throughput), prompts and code-block extraction.

## Open questions

- `/out` is a size-limited tmpfs removed with the container (`--rm`), so the launcher prints
  `result.json` to stdout after a per-run nonce marker (see `docs/NOTES.md`). Other files a
  script writes to `/out` (e.g. plots) are not returned yet. Is that OK for now, or should plots
  be returned (e.g. base64 in the result, size-capped)?
