# Progress

Living log of where the project stands. Updated at the end of every session and at checkpoints.

## Status: CHECKPOINT B (before Phase 7, benchmark runs), waiting for the user (2026-11-07)

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

## What the user needs to do (Checkpoint B)

1. **Optional MCP check (Phase 6 exit criterion):** connect Claude Desktop or Claude Code as in
   `docs/mcp.md` and run one request.
2. **Decide the open questions below** (prompt change; hosted model and prices).
3. **Pull the local models** for the benchmark rows (tags to confirm with `ollama list`):
   - `qwen2.5-coder:3b` (already pulled), primary
   - `qwen2.5-coder:1.5b`, small
   - `llama3.2:3b` (or `qwen2.5:3b`), 3B general-purpose
   - optional slow row: `qwen2.5-coder:7b` (does not fit fully in 4 GB VRAM: partial offload)
4. **Plug the laptop in** and either start the runs yourself or tell me to run them. Per model,
   both modes, resumable (re-run the same command to continue after an interruption):

   ```
   python scripts/evaluate.py --provider ollama --model qwen2.5-coder:3b --mode baseline --vram --resume
   python scripts/evaluate.py --provider ollama --model qwen2.5-coder:3b --mode repair --vram --resume
   ```

   (the same for each model tag; hosted: `--provider groq --model <tag>` without `--vram`).
   Rough time from the runs so far: 3–35 s per task, so about 10–30 min per model and mode for
   36 tasks on the 3B model; the 7B row will be much slower.
5. Say "continue" to start Phase 7 (make bench target, runs, report and analysis).

## Next

- Phase 7 (after Checkpoint B): `make bench`, benchmark runs per model and mode, committed
  results, generated report and an honest analysis.
- Phase 8: recorded demo of a real self-correcting run, README, final quality pass.

## Open questions

- **Prompt change before the benchmark?** In every local run so far, `qwen2.5-coder:3b` forgets
  `import simagent_io` on the first attempt (baseline 0/3 on the 3-task check). A general change,
  e.g. telling the model to start every script with `import photonsim as ps` and
  `import simagent_io` (not task-specific), would likely raise baseline scores a lot and shrink
  the repair loop's apparent benefit. Options: (a) benchmark the current prompt as is, (b) make
  the change first and log before/after numbers in NOTES.md, (c) run both as two prompt versions.
  Decide at Checkpoint B.
- **Hosted model:** which Groq model (and optionally OpenAI) to benchmark? A `GROQ_API_KEY` is
  set. For a cost column, `data/prices.json` needs that model's price from the provider's
  official pricing page with the date; I won't fill prices from memory. Without it, cost is
  reported as n/a.
- **May I run the long benchmark runs myself** once the models are pulled, or do you start them?
