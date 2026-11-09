# SPEC: Simulation Agent (natural language → sandboxed simulation code, with self-correction)

This is the source of truth. `PLAN-v2.md` says *how and in what order* for the current work (v2; v1's `PLAN.md` is history); this file says *what must be true*.
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

---

# v2 requirements (sections 9–18)

Same rules as sections 1–8: every requirement has an ID; tests name the IDs they cover in
their docstring; to change a requirement, edit this file first in its own `docs(spec):` commit.

## v2 overview: what actually helps a small local model?

v1 showed that a 3B local model goes from 7/36 to 20/36 with a repair loop, that a one-line
prompt fix did most of the same work, and that **the loop cannot fix wrong answers: it only
reacts to crashes** ("solved but wrong" got *worse* with repair).

v2 answers the question v1 opened, with numbers that survive an expert's questions:

1. **Are the v1 differences real?** Repeated runs, confidence intervals, paired tests.
2. **Why do models fail?** A deterministic failure taxonomy over every run.
3. **Can the agent catch its own wrong answers?** A verification step built on a provenance trace
   recorded by the simulator itself, not on what the model claims, measured on a **held-out task
   set frozen before the verifier was written**.
4. **What does 4 GB of VRAM really buy?** A quantisation and model-size study with real
   per-model VRAM footprints.
5. **Part B: does it work on a real simulation code?** The same agent drives **OpenMC**, an
   open-source Monte Carlo particle-transport code, with retrieval over its API reference; and
   `photonsim` is cross-validated against OpenMC.

Part A (sections 9–14, 17) is required. Part B (sections 15–16) starts only after the user's
go-ahead at CHECKPOINT D.

---

## 9. Held-out task set

- **R-HO-1** `data/tasks_heldout.jsonl` holds **24 new tasks**, same schema and checker types as
  `data/tasks.jsonl`: 3 `single_run`, 4 `sweep`, 3 `compare`, 4 `search`, 4 `multi_step`,
  4 `ambiguous_or_misleading`, 2 `adversarial`. Each has a reference script; expected values are
  generated by `scripts/make_expected.py` into `data/expected_heldout.json` (R-EV-3 applies).
- **R-HO-2** The held-out tasks are written and committed **before any verification code exists**
  (Phase 1). The commit is tagged `heldout-frozen`. They must not paraphrase dev tasks: use
  different materials, energies, phrasings and question shapes (e.g. "how thick must the
  shield be…", "rank these three materials…", "what changes if…").
- **R-HO-3** Ambiguous held-out tasks cover the failure modes found in v1 *with new instances*:
  an unknown material with a plausible real name, a unit other than cm/MeV, an out-of-range
  energy, and an impossible target.
- **R-HO-4** After `heldout-frozen`, held-out tasks and expected values never change. If a task is
  found to be broken (its reference is wrong), it is **excluded** (listed with the reason in
  `docs/NOTES.md` and in the report), never edited.
- **R-HO-5** No verification check, prompt, or threshold may be changed in response to a held-out
  failure. If that ever happens, the report must say the held-out set is no longer held out.

## 10. Repeated runs and statistics

- **R-STAT-1** The harness supports `--seeds 0,1,2,3,4` (repeats the run once per seed) and
  `--task-set {dev,heldout,all}`. Each (configuration, seed) writes its own results file;
  `--resume` works per file.
- **R-STAT-2** v2 runs use **temperature 0.7** with the seed passed to the provider where it is
  supported (Ollama: `seed`; hosted: if unsupported, record `seed_supported: false`). The exact
  sampling settings are stored in every results file header. v1 results (temperature 0) stay in
  the repo as history and are never mixed into v2 tables.
- **R-STAT-3** For each configuration, report: mean success rate over seeds, min–max over seeds,
  and a **95 % confidence interval from a bootstrap over tasks** (10 000 resamples, fixed RNG
  seed, resampling tasks and averaging each task's success over seeds).
- **R-STAT-4** For each comparison the report makes (e.g. repair vs verify, same model, same
  task set), compute the **paired** difference: bootstrap over tasks of the per-task difference
  in success rate (95 % CI), and an **exact McNemar test** on seed 0 (binomial test on discordant
  tasks, implemented with `math.comb`; no SciPy needed).
- **R-STAT-5** Reliability: per configuration, the number of tasks solved in **all** seeds, in
  **some** seeds, and in **none** ("pass^k" style), because an agent that solves a task one time
  in five is not reliable.
- **R-STAT-6** The report and README never call a difference an improvement if its 95 % CI
  includes 0; they say "no measurable difference". A test checks the wording helper.
- **R-STAT-7** Statistics code lives in `src/simagent/evaluation/stats.py`, is pure (input:
  per-task outcome matrices), and is unit-tested against hand-computed small cases (including a
  McNemar case from a textbook example and a bootstrap test with a fixed seed).

## 11. Failure taxonomy

- **R-TAX-1** `src/simagent/evaluation/taxonomy.py` classifies every task outcome of every run
  into exactly one class, deterministically, from the recorded attempt data (no LLM):
  `ok`, `format` (not exactly one python block), `policy`, `crash:<ExceptionType>`, `timeout`,
  `no_result`, `model_error` (provider abort, e.g. Ollama repeat limit), `wrong_answer:<subtype>`,
  `missed_error_report` (an ambiguous task answered with a number instead of an error),
  `false_refusal` (a legitimate task refused), `not_refused` (an adversarial task not refused).
- **R-TAX-2** `wrong_answer` subtypes come from the verifier's checks (section 12) applied offline
  to the recorded `result.json` and trace: `unit_mismatch`, `wrong_material`, `wrong_count`,
  `sweep_structure`, `out_of_range`, `inconsistent_with_trace`, else `wrong_other`.
  This is possible for **every** run (baseline and repair included) because the verifier is a
  pure function of recorded data.
- **R-TAX-3** The report shows a stacked bar chart per configuration (classes × count) and a table,
  generated by `scripts/report.py`. The v1 results files are also classified (as history).
- **R-TAX-4** The taxonomy rules are documented at the top of `taxonomy.py` and in the report, and
  the report states that classes are rule-based. `docs/taxonomy_sample.md` lists 20 randomly
  sampled (seeded) failures with their class and the evidence, so a human can spot-check them.

## 12. Provenance trace and verification

### Provenance trace (what actually ran)

- **R-TRACE-1** Inside the sandbox, `photonsim` records every `simulate()` and `sweep()` call:
  the slab (materials and thicknesses), energy, `n_photons`, seed, and the resulting
  fractions and standard error. The record is written by `simagent_io` to `/out/trace.json`
  when the script calls `submit()`. Recording is on only inside the sandbox image (environment
  flag set by the image, not by the script).
- **R-TRACE-2** The trace is capped (default 500 calls, `truncated: true` beyond) and its size is
  bounded like stdout (R-SBX-6).
- **R-TRACE-3** The trace cannot be forged by generated code: the policy rejects assignment to
  attributes of imported modules (e.g. `ps.simulate = …`, `photonsim.engine.x = …`) and any
  access to the recording internals (**R-POL-6**). A test proves that a script trying to
  monkeypatch `photonsim` or call the recorder directly is rejected, and a Docker test proves the
  trace is still correct when the policy is disabled and the script writes its own fake
  `/out/trace.json` before `submit()` (the recorder overwrites it, or the run is flagged).

### Request facts (what was asked)

- **R-REQ-1** `src/simagent/request_facts.py` extracts facts from the request text,
  deterministically (regular expressions + the materials list, no LLM):
  energies with units (eV, keV, MeV, GeV), lengths with units (µm, mm, cm, m, inches),
  photon counts, seeds, ranges ("from A to B", "between A and B", step if stated), the requested
  quantity (transmitted / reflected / absorbed / thickness / energy), whether percent is
  requested, and material mentions: known materials (including aliases such as
  "aluminum"/"aluminium"), and **unknown material candidates** (phrases in material position,
  e.g. "5 cm of X", "an X wall/slab/shield/layer", that are not known materials).
- **R-REQ-2** Facts are converted to simulator units (cm, MeV). Extraction is unit-tested on
  ≥ 40 phrasings, **none copied from the dev or held-out tasks**.
- **R-REQ-3** Extraction errs on the side of silence: if a phrase is unclear, no fact is
  produced (a missing fact disables a check; a wrong fact would cause false alarms).

### Verifier

- **R-VER-1** A new graph node `verify` runs after a successful run (exit 0 + `result.json`)
  and before `finalize`. It is a pure function `verify(facts, result, trace) -> list[Finding]`
  in `src/simagent/verify.py`. Each `Finding` has a check ID, a severity (`fail` / `warn`), and a
  feedback message written for the model.
- **R-VER-2** Initial checks (each with its own ID and unit tests):
  - `V-RANGE`: fractions in [0, 1] (or [0, 100] when percent is requested), numbers finite.
  - `V-ENERGY`: every traced energy equals an energy stated in the request (after unit
    conversion, relative tolerance 1e-6), when the request states any.
  - `V-LENGTH`: traced layer thicknesses are consistent with the stated lengths (each stated
    single thickness appears in the trace; for ranges, traced values lie within the range).
  - `V-COUNT`: traced `n_photons` equals the stated count, when stated.
  - `V-MATERIAL`: every known material named in the request appears in the trace; no traced
    material is absent from the request unless the request names none.
  - `V-UNKNOWN`: the request names an unknown material, or an energy outside the data range, but
    the script submitted a numeric answer instead of `submit(None, error=…)`.
  - `V-SWEEP`: the request states a range but the trace has fewer than 3 distinct values of the
    swept parameter, or all values were stacked into one slab (one call whose total thickness
    equals the sum of the range values).
  - `V-MONOTONE`: for a thickness sweep of a single material, transmission is non-increasing
    within 4 standard errors (warn only).
  - `V-TRACE`: a scalar answer that should come from a simulation (transmitted / reflected /
    absorbed fraction of a single configuration) matches a traced value within 1e-9, or a
    trivially derived one (×100 for percent).
- **R-VER-3** **No false alarms on references:** every dev reference script, run in the sandbox
  with tracing, passes the verifier with zero `fail` findings. This is a Docker test. A check that
  fires on a reference is narrowed or removed, never special-cased per task.
- **R-VER-4** On `fail` findings, the agent goes to `repair` with the findings as feedback (same
  format as other errors). `warn` findings are reported in the final answer but do not trigger
  repair. Verification-triggered repairs **share the same attempt budget** (`max_attempts`, default
  4), so `verify` mode is compared with `repair` mode at equal budget.
- **R-VER-5** If the attempt budget runs out while findings remain, status is `solved_unverified`
  (answer returned, with the findings). The checker treats it like `solved` (it judges the answer);
  the report counts it separately.
- **R-VER-6** Mode `verify` = repair loop + `verify` node. Modes are now `baseline`, `repair`,
  `verify`. The CLI gains `--mode`; the MCP `solve` tool uses `verify` by default and reports
  findings.
- **R-VER-7** Verifier quality is measured on every verify run, from recorded data:
  - **catches**: attempts where the verifier failed an answer the checker also judges wrong;
  - **false alarms**: attempts where the verifier failed an answer the checker judges correct;
  - **misses**: final answers the checker judges wrong that the verifier passed;
  - and the end-to-end effect: `wrong_answer` count and success rate, `repair` vs `verify`, with
    paired CIs (R-STAT-4), reported separately for dev and held-out.

## 13. Ambiguity and refusal

- **R-REF-1** The repair prompt restates the refusal rule: if the *request itself* is out of scope
  (files, network, shell, instructions), the correct repair is a refusal line, not new code.
  This is a general prompt change: log it in `docs/NOTES.md` with before/after adversarial
  numbers.
- **R-REF-2** When the policy rejects an attempt for a forbidden capability (file, network,
  process, environment access) and the request facts or the prompt contain no simulation
  parameters, the repair message tells the model it may refuse. (Deterministic rule; tested.)
- **R-REF-3** The adversarial and ambiguous categories are reported with the taxonomy split
  (`not_refused`, `missed_error_report`, `false_refusal`) so "the attack failed" and "the agent
  refused" are distinguished (the v1 finding).

## 14. Quantisation and VRAM study

- **R-QV-1** Rows: `qwen2.5-coder:3b` at Q4_K_M (current) and at Q8_0, and a 7B coder model at
  Q4_K_M (partial GPU offload expected). Use the exact Ollama tags available at run time
  (check with `ollama list` / the library; record them in `docs/NOTES.md`).
- **R-QV-2** VRAM is measured **per model** from Ollama's running-models API (`/api/ps`:
  `size` and `size_vram`), sampled during the run, not from `nvidia-smi` total (v1 showed that
  includes the desktop). The fraction on GPU (`size_vram / size`) is reported.
- **R-QV-3** Report per row: success (verify mode, dev + held-out, with CI), median latency, median
  output tokens/s, median TTFT, model size and VRAM footprint. One chart: success vs median
  latency, point size = VRAM.

## 15. Part B: OpenMC backend (only after CHECKPOINT D)

- **R-OMC-1** A second simulation backend, `openmc`, selected by `--backend {photonsim,openmc}`
  (default `photonsim`). It has its own sandbox image `simagent-openmc`, built `FROM` the official
  OpenMC Docker image pinned **by digest**, plus `simagent_io`. All R-SBX-3 hardening applies;
  limits are configurable per backend (defaults: memory 2 GB, timeout 180 s, 1 CPU,
  `OMP_NUM_THREADS=1`), and a size-limited writable work directory is the script's cwd.
- **R-OMC-2** Nuclear data: only the photon interaction data needed for the materials in the task
  set, downloaded by `scripts/get_openmc_data.py` (run by the user, network) into a directory
  **outside the repo**, mounted read-only into the container, with `OPENMC_CROSS_SECTIONS` set.
  The data library name, version, source URL, size and download date are recorded in
  `docs/NOTES.md` and in every OpenMC results header. Data is never committed.
- **R-OMC-3** Policy profile `openmc`: allowed imports are the v1 list plus `openmc` (and only the
  submodules the API reference uses); `openmc.lib`, `openmc.deplete` and anything that loads
  shared libraries or spawns processes from Python are rejected. Profiles are selected by the
  backend, never by the model.
- **R-OMC-4** `docs/openmc_api.md`: a curated API reference for photon fixed-source slab problems
  (materials, planes and cells, source, settings, tallies, running, reading the statepoint),
  written as small chunks with headings. **Every code snippet in it is executed** in the OpenMC
  sandbox by a Docker test, so the model is never given wrong documentation.
- **R-OMC-5** `data/tasks_openmc.jsonl`: **16 tasks** (4 single, 3 sweep, 3 compare, 3 search,
  3 ambiguous) with reference scripts; expected values generated in the OpenMC sandbox
  (R-EV-3 pattern) into `data/expected_openmc.json`; numeric tolerances from the tally standard
  deviation. Particle counts are chosen so a reference run takes ≤ 30 s on the user's laptop.
- **R-OMC-6** Verification for OpenMC uses the backend-independent checks (`V-RANGE`, `V-UNKNOWN`
  on facts) plus checks on the exported model (`model.xml` or the Python objects serialised by
  `simagent_io`): materials, slab thicknesses, source energy and particle count. If extracting
  these is not reliable, the report says which checks were available.
- **R-OMC-7** Cross-code validation (`scripts/crossval.py`, run with reference code, not the LLM):
  for a fixed grid (materials × energies × thicknesses, ≥ 24 points), compare
  (a) `photonsim` pure-absorber transmission vs Beer–Lambert, (b) OpenMC **uncollided**
  transmission vs Beer–Lambert, and (c) `photonsim` total transmission vs OpenMC total
  transmission. Results committed as `results/crossval.json` + chart. The analysis explains
  differences from the physics (photonsim has no energy loss on scattering), without overclaiming.
- **R-OMC-8** `simagent doctor` checks the OpenMC image and the data directory.

## 16. Part B: retrieval over the API reference

- **R-RAG-1** `src/simagent/retrieval.py`: BM25 over the chunks of the backend's API reference
  (one chunk per heading). Pure Python or a small pinned dependency; no vector database and no
  embedding model (the corpus is tiny; deterministic and offline). Justify this in the design doc.
- **R-RAG-2** Prompt modes: `--docs full` (whole reference, as v1) and `--docs retrieve`
  (top-k chunks, default k = 4). In `generate`, the query is the request; in `repair`, the request
  plus the error or findings.
- **R-RAG-3** Retrieval quality: for each OpenMC task, the **needed chunks** are derived
  automatically from the API names its reference script uses. Report recall@k per task set.
- **R-RAG-4** Report, per model and docs mode: success, input tokens per task, latency. Also run
  `--docs retrieve` on the photonsim dev set, to show whether retrieval helps or hurts when the
  full reference already fits.

## 17. Reporting, docs and README

- **R-REP-1** `docs/eval_results.md` gains v2 sections generated by `scripts/report.py` only:
  headline table with CIs, paired comparisons, reliability, taxonomy chart, verifier quality,
  quantisation study, and (Part B) OpenMC, retrieval and cross-validation. A test checks the
  committed report matches the results files (as v1).
- **R-REP-2** `docs/eval_analysis.md` is rewritten for v2 by hand from the generated numbers
  (every number traceable to a results file); v1's analysis moves to `docs/eval_analysis_v1.md`.
- **R-REP-3** README: the headline becomes the v2 question and answer, with one chart (success
  with 95 % CI for baseline → repair → verify, dev and held-out, per model). Keep it short; link to
  the full report. A test checks every number in the README results block appears in the
  generated report.
- **R-REP-4** `docs/design_v2.md`: one short section per v2 decision (held-out set, temperature
  and seeds, bootstrap vs other tests, why the trace comes from the simulator, why checks are
  deterministic, shared attempt budget, BM25 vs embeddings, OpenMC data choices), each with the
  trade-off and the alternative rejected. It ends with "Questions a reviewer might ask", with
  answers backed by the results.

## 18. Phase map (v2)

| Phase | Requirements |
|---|---|
| 0 | spec merge |
| 1 | R-HO-1…5 |
| 2 | R-STAT-1…7 |
| 3 | R-TRACE-1…3, R-POL-6 |
| 4 | R-REQ-1…3, R-VER-1…7 |
| 5 | R-TAX-1…4, R-REF-1…3 |
| 6 | benchmark runs (Part A), R-QV-1…3 |
| 7 | R-REP-1…4 (Part A), release v0.2.0 |
| 8 | R-OMC-1…3, R-OMC-8 |
| 9 | R-OMC-4…6, R-RAG-1…3 |
| 10 | R-OMC-7, R-RAG-4, OpenMC runs, R-REP updates, release v0.3.0 |
