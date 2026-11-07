# SPEC: Simulation Agent (natural language → sandboxed simulation code, with self-correction)

This is the source of truth. `PLAN.md` says *how and in what order*; this file says *what must be true*.
Every requirement has an ID. Tests name the IDs they cover in their docstring (e.g. `"""Covers R-SBX-3."""`).
To change a requirement: edit this file first, in its own commit (`docs(spec): ...`), then change the code.

## 0. One-paragraph summary

A user asks a question in plain language about a particle-transport simulation ("sweep the lead
thickness from 1 to 10 cm and tell me where transmission drops below 1 %"). The agent writes a
Python script against the `photonsim` API, statically checks it, runs it in an isolated sandbox,
reads the result, and if anything fails, feeds the error back to the model and repairs the script,
up to a fixed number of attempts. It is exposed as a CLI and as an MCP server, runs on local
open-weight models (Ollama) or hosted ones, and ships with an evaluation harness that compares
single-shot generation against the repair loop across models, with accuracy, latency and cost.

## 1. Simulator (`photonsim`)

- **R-SIM-1** `photonsim` is a pure-Python + NumPy Monte Carlo simulator of mono-energetic photons
  crossing a 1D stack of slab layers (normal incidence). Each photon ends as `transmitted`,
  `reflected` (back-scattered out of the front face) or `absorbed`.
- **R-SIM-2** Interaction model: exponential free path from the layer's total attenuation
  coefficient `mu_total`; at each interaction the photon is absorbed with probability
  `mu_abs / mu_total`, otherwise isotropically scattered with no energy loss.
  This is a deliberate simplification and the docs say so.
- **R-SIM-3** Material data lives in `src/photonsim/data/materials.json` with `mu_total` and
  `mu_abs` (cm⁻¹) per material and per energy point, and a `source` field. Values are either taken
  from a cited public source (e.g. NIST XCOM) with the citation in `source`, or explicitly marked
  `"illustrative"`. Values are never invented and presented as real. Energies between data points
  are log-log interpolated; energies outside the table raise `ValueError`.
- **R-SIM-4** Public API (stable, documented, the only thing generated code may use):
  - `Layer(material: str, thickness_cm: float)`
  - `Slab(layers: list[Layer])`
  - `simulate(slab, energy_mev: float, n_photons: int, seed: int | None = None) -> Result`
  - `Result`: `transmitted`, `reflected`, `absorbed` (fractions summing to 1),
    `n_photons`, `stderr_transmitted` (binomial standard error), `to_dict()`
  - `sweep(build: Callable[[float], Slab], values: list[float], energy_mev, n_photons, seed=None) -> list[tuple[float, Result]]`
  - `list_materials() -> list[str]`, `energy_range(material) -> tuple[float, float]`
- **R-SIM-5** Invalid arguments (unknown material, thickness ≤ 0, n_photons < 1, empty slab)
  raise `ValueError` with a message that names the bad argument and the valid options.
  (These messages are what the repair loop feeds back to the model.)
- **R-SIM-6** Same `seed` ⇒ identical `Result`. 100 000 photons through a 3-layer slab run in
  under 2 s on a laptop CPU (vectorised NumPy, no per-photon Python loop).
- **R-SIM-7** Validation: for a pure absorber (`mu_abs == mu_total`), transmission matches the
  Beer–Lambert law `exp(-mu·x)` within 4 standard errors. A test checks this for several
  thicknesses.
- **R-SIM-8** `docs/api.md` (generated from docstrings by `scripts/gen_api_doc.py`) is the API
  reference given to the model. It is at most ~1 500 tokens so it fits small local contexts.
  A test fails if it is stale.

## 2. Sandbox

- **R-SBX-1** Generated code runs only through a `Runner` interface:
  `run(code: str, timeout_s: float) -> RunResult(exit_code, stdout, stderr, result_json | None, timed_out, duration_s)`.
- **R-SBX-2** The default runner is `DockerRunner`, using image `simagent-sandbox` built from
  `sandbox/Dockerfile` (Python slim + numpy + matplotlib + photonsim + the `simagent_io` helper,
  pinned versions).
- **R-SBX-3** Every container runs with: no network (`--network none`), read-only root filesystem,
  a size-limited writable `/tmp` and `/out` only, memory limit (default 512 MB), CPU limit
  (default 1), PID limit, non-root user, `--cap-drop ALL`, `--security-opt no-new-privileges`,
  and `--rm`. The script is mounted read-only.
- **R-SBX-4** A run exceeding `timeout_s` (default 60 s) is killed; `timed_out=True`.
- **R-SBX-5** No host environment variable is passed into the container. Tests prove an API key
  set on the host is not visible inside.
- **R-SBX-6** stdout and stderr are each capped (default 20 000 chars, keeping the tail) before
  they reach the model or the logs.
- **R-SBX-7** Generated code reports its answer by calling `simagent_io.submit(answer, **data)`,
  which writes `/out/result.json`. A run with exit code 0 but no `result.json` counts as a failure
  ("no result submitted").
- **R-SBX-8** `LocalRunner` (plain subprocess with timeout, no isolation) exists for development
  only. It is disabled unless `--unsafe-local` / `SIMAGENT_UNSAFE_LOCAL=1` is set, prints a
  warning on every run, and is never used in the evaluation.
- **R-SBX-9** Tests that need Docker are marked `@pytest.mark.docker` and skipped when Docker is
  not available. CI (GitHub Actions, Ubuntu) runs them.

## 3. Static policy (before execution)

- **R-POL-1** Before any run, the script is parsed with `ast`. Parse errors are reported as
  failures with the line number, without running anything.
- **R-POL-2** Imports are allow-listed: `photonsim`, `simagent_io`, `numpy`, `math`, `json`,
  `statistics`, `itertools`, `matplotlib`/`matplotlib.pyplot`. Anything else is rejected.
- **R-POL-3** Calls to `eval`, `exec`, `compile`, `__import__`, `open` (except via `simagent_io`),
  `getattr`/`setattr` on dunder names, and attribute access to dunder attributes are rejected.
- **R-POL-4** A policy violation is returned to the model as repair feedback ("import of `os`
  is not allowed; allowed modules are …"); it counts as a failed attempt.
- **R-POL-5** The policy is defence in depth: the sandbox (R-SBX-3) must hold even if the policy
  is bypassed. A test runs a deliberately malicious script with the policy disabled and checks
  the sandbox still blocks network access and writes outside `/out`.

## 4. Agent (LangGraph)

- **R-AG-1** The agent is a LangGraph `StateGraph` with nodes:
  `generate` → `check_policy` → `execute` → `evaluate_run` → (`repair` → `check_policy` …) or `finalize`.
- **R-AG-2** `generate` prompts the model with: a system prompt, the API reference (R-SIM-8),
  the I/O contract (R-SBX-7) and the user request. The request is wrapped in delimiters and
  treated as data, not instructions.
- **R-AG-3** The model's reply must contain exactly one fenced Python code block. If not, that is
  a failed attempt with feedback "reply must contain exactly one ```python block".
- **R-AG-4** `repair` sends the previous code plus a compact error report (policy violation, or
  exit code + last 40 lines of stderr, or "timed out", or "no result submitted") and asks for a
  full corrected script.
- **R-AG-5** `max_attempts` (default 4, including the first) bounds the loop. **Baseline mode**
  is the same graph with `max_attempts=1`.
- **R-AG-6** The final answer contains: status (`solved` / `failed`), the answer and data from
  `result.json`, a one-paragraph explanation, the final script, the number of attempts, and the
  per-attempt errors.
- **R-AG-7** Every run saves its artifacts in `runs/<timestamp>-<id>/`: each attempt's script,
  stdout/stderr, result.json, and a `trace.json` with timings and token counts.
- **R-AG-8** The agent never executes code outside a `Runner`, and never lets the model choose
  the runner, the timeout or the resource limits.
- **R-AG-9** A request that asks for something outside the simulator's scope (reading files,
  network, shell commands, "print your system prompt") ends as `status=refused` or fails the
  policy; it never reaches execution with forbidden capabilities.

## 5. LLM providers

- **R-LLM-1** Providers: `ollama` (local), `groq`, `openai`, and `fake`. Selected by `LLM_PROVIDER`
  or `--provider`; model by `LLM_MODEL` or `--model`.
- **R-LLM-2** `fake` is a scripted provider: it replays a list of canned replies (e.g. buggy
  script, then fixed script). All tests and CI use it; no test touches the network.
- **R-LLM-3** For every model call, record: input tokens, output tokens, time to first token
  (TTFT, via streaming), total latency, and output tokens per second. When the provider does not
  report a value, record `null`, never a guess.
- **R-LLM-4** Keys come only from the environment / `.env`. `.env` is gitignored; `.env.example`
  lists every variable.

## 6. Evaluation

- **R-EV-1** `data/tasks.jsonl` holds 30–40 tasks. Each has: `id`, `category`, `prompt`,
  `checker` (type + parameters), and `reference` (path to a reference solution script).
- **R-EV-2** Categories, with at least 4 tasks each: `single_run`, `sweep`, `compare`
  (two configurations), `search` (find a thickness/energy meeting a target), `multi_step`,
  `ambiguous_or_misleading` (unknown material, impossible target, wrong units), `adversarial`
  (asks for file/network/shell access or tries prompt injection).
- **R-EV-3** Expected values are produced by running the reference scripts in the sandbox
  (`scripts/make_expected.py` → `data/expected.json`), never typed by hand.
- **R-EV-4** Checkers are deterministic functions of `result.json` (no LLM judge): numeric within
  tolerance (tolerance derived from the Monte Carlo standard error, or a stated relative bound),
  value in set, threshold-crossing within one sweep step, JSON keys present, or `must_refuse`.
  Checkers are unit-tested.
- **R-EV-5** `scripts/evaluate.py --provider P --model M --mode {baseline,repair} [--limit N] [--resume]`
  appends one JSON line per task to `results/<run-name>.jsonl` (so an interrupted run resumes),
  then writes a summary.
- **R-EV-6** Reported metrics per (model, mode): success rate (overall and per category), mean
  attempts on solved tasks, repairs that turned a failure into a success, policy violations,
  timeouts, median and p90 end-to-end latency, median TTFT, median tokens/s, total tokens, and
  estimated cost for hosted models (price table with date in `data/prices.json`). Optional peak
  VRAM, sampled with `nvidia-smi`, when available.
- **R-EV-7** `docs/eval_results.md` and `docs/eval_chart.png` are generated from the results files
  by `scripts/report.py`. The README quotes only numbers present in committed results files.
- **R-EV-8** CI runs the evaluation on 3 tasks with the `fake` provider, to prove the harness works
  end to end. It does not claim any accuracy.

## 7. Interfaces

- **R-CLI-1** `simagent solve "<request>"` runs the agent and prints a rich summary (status,
  answer, attempts, final script). Flags: `--provider`, `--model`, `--max-attempts`,
  `--unsafe-local`, `--json`.
- **R-CLI-2** `simagent run-script FILE` runs a script through the policy + sandbox only.
- **R-CLI-3** `simagent doctor` checks: Docker available, sandbox image built, Ollama reachable and
  which models are pulled, GPU visible, keys present (shown as present/absent, never printed).
- **R-CLI-4** Exit codes: 0 solved, 3 not solved / refused, 2 invalid input or config,
  1 unexpected error. Expected failures print one line, no stack trace.
- **R-MCP-1** `simagent mcp` starts an MCP server (stdio) exposing tools:
  `describe_simulator` (API reference), `run_simulation_script(code)` (policy + sandbox),
  and `solve(request, max_attempts?)` (the full agent).
- **R-MCP-2** The MCP tools enforce the same policy, sandbox and limits as the CLI; a client cannot
  override timeouts or resource limits.
- **R-MCP-3** The README shows a working client configuration (e.g. Claude Desktop) and a short
  demo of a client using the tools.

## 8. Quality

- **R-Q-1** Python 3.11+, `src/` layout, `pyproject.toml`, typed (`mypy --strict` on `src/`),
  `ruff` lint + format, `pytest` with coverage ≥ 85 % on `src/` (Docker-only lines excluded when
  Docker is absent).
- **R-Q-2** CI: lint, type-check, tests (including Docker tests), fake-provider eval smoke run.
- **R-Q-3** Every commit on `main` passes lint and tests (history is bisectable).
- **R-Q-4** The project works on Windows (Docker Desktop + WSL2) and Linux. Paths use `pathlib`;
  no shell-specific commands in Python code.
