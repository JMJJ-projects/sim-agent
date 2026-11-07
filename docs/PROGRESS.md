# Progress

Living log of where the project stands. Updated at the end of every session and at checkpoints.

## Status: all phases done, pushed, CI green (2026-11-07)

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

- **Checkpoint A follow-up:** `fix(policy)` rejects dangerous modules reached through allowed
  modules' attributes (`matplotlib.os`, `matplotlib.subprocess`, ...) and exec/spawn/fork.
- **Phase 3, LLM layer:** provider factory (ollama/groq/openai/fake), scripted fake model with a
  built-in buggy-then-fixed demo, per-call metrics (tokens, TTFT, latency, tok/s; null when not
  reported), prompts (system + API + result contract, delimited request, repair), and single
  code-block extraction with refusals. Manual check with `qwen2.5-coder:3b`: code block + metrics
  returned (see NOTES.md).

- **Phase 4, agent:** LangGraph `StateGraph` (generate → check_policy → execute → evaluate_run →
  repair/finalize) with pure, tested routing; error compaction; per-run artifacts in `runs/`;
  PNGs from `/out` returned (≤ 1 MB total, base64; requested at Checkpoint A); `simagent solve`
  with rich/`--json` output and exit codes; pre-flight checks for Docker and Ollama;
  `docs/graph.mmd` with staleness test. `simagent solve "..." --provider fake` shows a full repair
  cycle offline (H2O → water).

### Manual check with the local model (Phase 4 exit criterion)

`qwen2.5-coder:3b` via Ollama, Docker sandbox, `max_attempts=4`, prompts untuned. Six requests
typed by hand (not the eval set), run once each on 2026-11-07:

| # | Request (short) | Status | Attempts | Notes |
|---|---|---|---|---|
| 1 | T, 1 MeV, 5 cm water, 1e5 photons | solved | 2 | 1st: missing `import simagent_io`; answer 0.767 (matches the fake-demo reference run) |
| 2 | compare 3 cm lead vs 3 cm iron, 2 MeV | solved | 2 | same missing import; submitted a single number, not both values |
| 3 | sweep Al 1–10 cm, 0.5 MeV | solved* | 3 | *wrong answer: built one 55 cm slab and ignored the sweep variable (T≈0). Exit 0 but incorrect |
| 4 | lead thickness for T < 1 %, 1 MeV | failed | 4 | `range()` with float steps, same TypeError all 4 times |
| 5 | reflection, 0.662 MeV, 10 cm concrete | solved | 2 | missing import again; R = 0.159 |
| 6 | "read /etc/passwd" | refused | 1 | `REFUSED:` reply, nothing executed |

Takeaways: the repair loop fixes the recurring small-model bug (missing import) reliably; it
does not fix logic errors, and `solved` only means "ran and submitted a result", so correctness
must come from the Phase 5 checkers. Timing: 15–35 s wall per request, 3–7k input tokens.

- **Phase 5, evaluation harness:** deterministic checkers (numeric with MC tolerance, lists,
  equals/in_set, threshold, keys, must_refuse, reports_error, all/any); 36 tasks + reference
  scripts; expected values generated in the sandbox; resumable `scripts/evaluate.py` (JSONL per
  task, per-task artifacts, VRAM sampler, warm-up); `scripts/report.py` → `docs/eval_results.md`
  + chart; CI smoke eval with the fake provider. Exit check: a 3-task real run with
  `qwen2.5-coder:3b` produced a report (baseline 0/3, repair 3/3; details in NOTES.md).

- **Phase 6, MCP:** `MCPServer` (mcp SDK 2.x) with `describe_simulator`,
  `run_simulation_script`, `solve`; limits fixed by the server (override attempts ignored, tested);
  in-process client tests + a real stdio subprocess test; `simagent mcp`; `docs/mcp.md`.
- **State:** 395 tests pass with Docker (all Docker tests included), coverage 96 %, ruff + mypy
  --strict clean. Nothing pushed.

## Checkpoint B decisions (user, 2026-11-07)

- Prompt: run both. Round 1 = prompt v1 on `qwen2.5-coder:3b` (baseline + repair); then prompt v2
  (general import instruction, logged in NOTES.md); round 2 = v2 on every model.
- Hosted: `openai/gpt-oss-120b` on Groq free tier; no price recorded, cost shown as
  "n/a: free tier, official pricing unavailable on 2026-11-07"; per-task tokens reported.
- Local models: `qwen2.5-coder:3b`, `qwen2.5-coder:1.5b`, `qwen2.5:3b`; 7B skipped for now.
- The agent runs the benchmark itself, commits each model's results as it finishes.
- MCP: the user's message left this choice as a placeholder; treated as "test later, don't block".

## Phase 7 / 8 status

- Done: `make bench` (`scripts/bench.py`, `data/bench_plan.json`), prompt versioning, rate-limit
  handling, output-token cap for local models (NOTES.md), round 1 results committed
  (`qwen2.5-coder:3b` v1: baseline 7/36, repair 20/36), report with "not run yet" rows,
  recorded demo (`docs/demo.svg`), recorded MCP session (`docs/mcp_demo.md`), README with a
  generated results block, make targets documented.
- In progress: see "Benchmark run status" below (updated as runs finish).
- To resume any unfinished run: `python scripts/bench.py run --only <model>` (resumes from the
  staging files in `runs/bench/results`), then `python scripts/bench.py promote` and
  `python scripts/report.py`, and commit `results/`, `docs/eval_results.md`,
  `docs/eval_chart.png`, `README.md`. `python scripts/bench.py status` shows progress.

### Benchmark run status

All 10 planned runs complete and committed (36/36 tasks each), no rows "not run yet":

| model | prompt | baseline | repair |
|---|---|---|---|
| `qwen2.5-coder:3b` | v1 | 7/36 | 20/36 |
| `qwen2.5-coder:3b` | v2 | 23/36 | 24/36 |
| `openai/gpt-oss-120b` (Groq) | v2 | 34/36 | 36/36 |
| `qwen2.5-coder:1.5b` | v2 | 4/36 | 8/36 |
| `qwen2.5:3b` | v2 | 17/36 | 19/36 |

Incidents (details in NOTES.md): runaway generation → 2048-token output cap for local models;
Groq baseline stopped once on a console-encoding crash and was resumed; 5 Ollama repeat-limit
aborts on the 1.5B model; one 31 s container start while two runs shared Docker.

## Phase 8 (done)

- Recorded demo `docs/demo.svg` (real round 1 run: NameError → repair → pass), recorded MCP
  session `docs/mcp_demo.md`, README (generated results block, analysis summary, security table,
  make targets), `docs/eval_analysis.md`.
- Final pass: 404 tests pass with Docker required (`SIMAGENT_REQUIRE_DOCKER=1`), coverage 96 %,
  ruff + mypy --strict clean. Fresh clone check: `pip install -e .` → `simagent solve "..."
  --provider fake` shows the full repair cycle (exit 0); without Docker, `doctor` and `solve`
  print one line and exit 2.

## Not verified

- Nothing open from earlier: CI runs and is green, and MCP was tested with a real client (below).
- 7B row skipped by decision.

## Publishing and CI (2026-11-07)

- Repository: https://github.com/JMJJ-projects/sim-agent (public), with a CI badge in the README.
- The first CI run failed in the `sandbox` job: on Linux the bind-mounted script directory was
  0700 for the host user, so the container's uid 10001 could not read it (Docker Desktop on
  Windows hides this). Fixed in `fix(runner)` (dir 0755, script 0644, mount still read-only).
  Since then all jobs pass: lint-test on 3.11 and 3.13, and sandbox with 16 Docker tests and the
  fake-provider smoke eval (3/3).
- **Phase 6 fully done:** a fresh headless Claude Code session used the registered `simagent`
  MCP server (`describe_simulator` → `run_simulation_script` in the Docker sandbox, T = 0.0301 for
  5 cm of lead at 1 MeV); details in `docs/mcp.md`.

## What the user needs to do

- Nothing required. Optional: try Claude Desktop with the config in `docs/mcp.md`.

## Next (optional extensions, PLAN.md section 5)

- Refusal-aware repair (re-ask for a refusal when a request is out of scope) and retrying
  Ollama's repeat-limit abort: both suggested by the analysis.
- A 7B row with partial offload; RAG over the docs; an OpenMC adapter.

## Open questions

- None. Checkpoint B questions were answered (see above).
