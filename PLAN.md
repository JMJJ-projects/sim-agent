# Project Plan: Simulation Agent

> **How to use this file:** work through the phases in order. A phase starts only when the previous
> phase's **Done when** checks pass. Each step lists the commit(s) it should produce; a step may need
> an extra `fix:`/`refactor:` commit, but never a "WIP" commit.
> **Rule for the AI agent:** library APIs (LangGraph, LangChain, the `mcp` SDK, Ollama, Docker SDK)
> change often. Before coding against one, check the installed version and its real API
> (`pip show`, `help()`, official docs). Never code from memory. Log any mismatch with this plan in
> `docs/NOTES.md`.

---

## 0. Goal and what makes it stand out

**Product:** a CLI + MCP server that turns a natural-language request about a particle-transport
simulation into a Python script, runs it in a locked-down sandbox, repairs it from the error output
when it fails, and returns a checked answer.

**Target readers:** recruiters for agentic-AI / applied-LLM internships (CEA, Dassault Systèmes…).
Those postings ask for: agents and tool use, **MCP**, **code that actually runs**, **local
open-weight models**, **evaluation against baselines**, latency/cost awareness, clean engineering.

**Design for these, in order:**
1. **One-command demo** that works with no API key and no GPU (`fake` provider) and a real one with
   a small local model.
2. **Measured, honest results:** baseline vs. repair loop, local vs. hosted model, with accuracy,
   latency, TTFT, tokens/s, cost. Failures shown, not hidden.
3. **Security:** static policy + hardened Docker sandbox, proven by tests (network blocked, secrets
   not visible, read-only FS, timeouts).
4. **MCP:** usable from any MCP client; a GIF/SVG shows it.
5. **Clean repo:** typed, linted, tested, CI badge, readable history.

**Non-goals:** web UI, multi-user, fine-tuning/RL, real shielding-grade physics, GPU simulation,
VLMs, RAG (possible later extension; see §5).

---

## 1. Fixed decisions (do not re-debate)

| Topic | Decision |
|---|---|
| Language / packaging | Python 3.11+, `pyproject.toml` (hatchling), `src/` layout with two packages: `photonsim`, `simagent` |
| Env | `uv` if available, else `pip` + venv |
| Agent | LangGraph `StateGraph`; LangChain chat models behind a provider factory |
| Providers | `ollama` (default real provider), `groq`, `openai`, `fake` (scripted, for tests) |
| Local models (4 GB VRAM: RTX 3050 Mobile) | Primary: a ~3B coding model (e.g. Qwen2.5-Coder 3B, Q4). Also a ~1.5B model and a ~3B general model. A ~7B model is an optional "partial GPU offload" row, expected slow. **Check what is actually available with `ollama list` / the Ollama library at implementation time; record exact tags in `docs/NOTES.md`.** Keep `num_ctx` modest (≈4–8k) to fit VRAM. |
| Hosted model | One strong model via Groq's free tier (check its current model list) and optionally one OpenAI model. |
| Sandbox | Docker (Docker Desktop + WSL2 on Windows) via the `docker` CLI through `subprocess` (no Docker SDK, fewer moving parts) |
| Schemas / CLI / output | Pydantic v2 / `typer` / `rich` |
| MCP | Official Python `mcp` SDK, stdio transport |
| Quality | `ruff`, `mypy --strict` (src), `pytest`, `pytest-cov`, GitHub Actions |
| Config | `.env` via `python-dotenv`; `.env.example` committed |
| Licence | MIT |

---

## 2. Target layout

```
sim-agent/
├── src/
│   ├── photonsim/
│   │   ├── __init__.py        # public API re-exports
│   │   ├── geometry.py        # Layer, Slab
│   │   ├── materials.py       # loading + log-log interpolation
│   │   ├── transport.py       # vectorised Monte Carlo
│   │   ├── result.py          # Result
│   │   ├── sweep.py
│   │   └── data/materials.json
│   └── simagent/
│       ├── __init__.py
│       ├── config.py
│       ├── llm.py             # provider factory + FakeLLM (scripted)
│       ├── metrics.py         # token/TTFT/latency capture
│       ├── prompts.py         # system / generate / repair templates
│       ├── codeblock.py       # extract exactly one ```python block
│       ├── policy.py          # AST allow-list
│       ├── runners/{base.py,docker.py,local.py}
│       ├── io_helper/simagent_io.py   # copied into the sandbox image
│       ├── state.py, nodes.py, graph.py
│       ├── artifacts.py       # runs/<id>/ writer
│       ├── mcp_server.py
│       └── cli.py
├── sandbox/Dockerfile
├── data/{tasks.jsonl, expected.json, prices.json, reference/*.py}
├── scripts/{gen_api_doc.py, make_expected.py, evaluate.py, report.py, export_graph.py, render_demo.py}
├── results/                   # committed eval outputs (*.jsonl, summaries)
├── docs/{api.md, PROGRESS.md, NOTES.md, eval_results.md, eval_chart.png, graph.mmd, demo.svg}
├── tests/
├── .github/workflows/ci.yml
├── CLAUDE.md, SPEC.md, PLAN.md, README.md, LICENSE, Makefile, .env.example, .gitignore
```

---

## 3. Phases

Time estimates assume an AI agent doing the coding; the user's review time is extra.

### Phase 0: Scaffold (≈1 h)

| Step | Commits |
|---|---|
| 0.1 Commit `CLAUDE.md`, `SPEC.md`, `PLAN.md` as they are | `docs: add spec, plan and agent instructions` |
| 0.2 `pyproject.toml` (deps + extras `ollama`, `groq`, `openai`, `dev`), layout with empty modules, `.gitignore`, `.env.example`, `LICENSE`, `Makefile` | `chore: scaffold package layout and tooling` |
| 0.3 `docs/PROGRESS.md`, `docs/NOTES.md` | `docs: add progress and notes logs` |
| 0.4 CI: ruff, ruff format --check, mypy, pytest | `ci: add lint, type-check and test workflow` |

**Done when:** `pip install -e ".[dev]"`, `make lint`, `pytest` (0 tests is fine) all pass.

### Phase 1: `photonsim` simulator (≈4 h)

| Step | Commits |
|---|---|
| 1.1 `materials.json` with ~6 materials (e.g. water, concrete, aluminium, iron, lead, polyethylene) over ~0.1–10 MeV. Prefer real NIST XCOM values with the citation in `source`; if not retrievable offline, mark `"illustrative"` (R-SIM-3). Loader + log-log interpolation + range errors | `feat(photonsim): add material data and interpolation` + tests |
| 1.2 `Layer`, `Slab`, validation messages (R-SIM-5) | `feat(photonsim): add slab geometry with validated inputs` + tests |
| 1.3 Vectorised transport: positions/directions as arrays, loop over interaction steps (not photons) until all photons have exited or been absorbed | `feat(photonsim): add vectorised Monte Carlo transport` |
| 1.4 `Result` (+ binomial stderr), `simulate`, `sweep`, `list_materials`, `energy_range` | `feat(photonsim): add simulate and sweep API` |
| 1.5 Physics tests: Beer–Lambert check (R-SIM-7), fractions sum to 1, determinism with seed, monotonic transmission vs thickness, perf ≤ 2 s for 1e5 photons (R-SIM-6, marked `slow` if needed) | `test(photonsim): validate against Beer-Lambert and invariants` |
| 1.6 `scripts/gen_api_doc.py` → `docs/api.md` (≤ ~1 500 tokens) + staleness test | `docs: generate compact API reference for the model` |

**Done when:** all physics tests pass; `python -c "import photonsim as p; print(p.simulate(p.Slab([p.Layer('lead',2)]),1.0,100000,seed=1))"` works.

### Phase 2: Policy and sandbox (≈5 h), then **CHECKPOINT A**

| Step | Commits |
|---|---|
| 2.1 `simagent_io.submit()` (writes `/out/result.json`, validates JSON-serialisable) | `feat(sandbox): add result submission helper` + tests |
| 2.2 `policy.py` AST allow-list (R-POL-1..4) with clear messages | `feat(policy): add static allow-list check for generated code` + tests (each forbidden pattern, each allowed module) |
| 2.3 `sandbox/Dockerfile` (pinned versions, non-root user, photonsim + simagent_io installed), `make sandbox-image` | `build(sandbox): add hardened sandbox image` |
| 2.4 `Runner` interface + `DockerRunner` with all R-SBX-3 flags, timeout kill, output caps, temp dirs cleaned up | `feat(runner): add Docker runner with resource limits` |
| 2.5 Security tests (`@pytest.mark.docker`): network blocked, host env var not visible, write outside `/out` fails, `/` read-only, timeout kills, memory limit triggers, fork bomb contained by PID limit, malicious script with policy *disabled* still contained (R-POL-5) | `test(runner): prove sandbox isolation` |
| 2.6 `LocalRunner` behind `--unsafe-local` with warning (R-SBX-8) | `feat(runner): add opt-in unsafe local runner for development` |
| 2.7 `simagent run-script FILE` and `simagent doctor` | `feat(cli): add run-script and doctor commands` |
| 2.8 CI builds the image and runs Docker tests | `ci: build sandbox image and run isolation tests` |

**Done when:** all sandbox tests pass locally and in CI.
**CHECKPOINT A: stop and update PROGRESS.md.** The user reviews the sandbox flags and security
tests before any model-generated code is executed.

### Phase 3: LLM layer (≈3 h)

| Step | Commits |
|---|---|
| 3.1 Provider factory (`ollama`, `groq`, `openai`, `fake`); check each provider's current LangChain integration package and API first | `feat(llm): add provider factory` |
| 3.2 `FakeLLM` scripted replies (list of strings, consumed in order; error if exhausted). Ship a built-in demo script used by `--provider fake` in the CLI: first reply has a realistic bug (e.g. unknown material name), second is the fix, so the offline demo shows a repair | `feat(llm): add scripted fake provider for tests and demo` + tests |
| 3.3 `metrics.py`: streaming call wrapper recording TTFT, latency, tokens in/out, tokens/s; `null` when unknown (R-LLM-3). Check how Ollama/Groq report token counts in response metadata | `feat(metrics): record tokens, TTFT and throughput per call` + tests with fake streaming |
| 3.4 `prompts.py` (system, generate, repair) and `codeblock.py` (exactly one ```python block, R-AG-3) | `feat(prompts): add generation and repair prompts` + `feat(agent): extract a single code block from replies` + tests |

**Done when:** a manual call with Ollama (`simagent doctor` shows the model) returns a code block and metrics.

### Phase 4: Agent graph (≈5 h)

| Step | Commits |
|---|---|
| 4.1 `state.py` (attempts list, current code, last error, metrics, status) | `feat(agent): define agent state` |
| 4.2 Nodes: generate, check_policy, execute, evaluate_run, repair, finalize; error report compaction (R-AG-4) | `feat(agent): add generation, execution and repair nodes` |
| 4.3 Graph wiring + routing as a pure, unit-tested function; `max_attempts`; baseline = 1 | `feat(agent): wire self-correcting graph with attempt limit` + `test(agent): cover routing for every outcome` |
| 4.4 End-to-end tests with `FakeLLM`: success first try; KeyError → repaired; policy violation → repaired; never valid → `failed` after N; no code block; adversarial request → refused/blocked (R-AG-9) | `test(agent): end-to-end repair scenarios with scripted model` |
| 4.5 Artifacts in `runs/<id>/` (R-AG-7), gitignored | `feat(agent): save per-attempt artifacts and trace` |
| 4.6 `simagent solve` with rich output, `--json`, exit codes (R-CLI-1, R-CLI-4) | `feat(cli): add solve command` |
| 4.7 `scripts/export_graph.py` → `docs/graph.mmd` + staleness test | `docs: export agent graph diagram` |

**Done when:** `simagent solve "transmission through 5 cm of water at 1 MeV" --provider fake` works
offline, and the same with the local 3B model solves at least simple requests (try ~5 by hand,
note results in PROGRESS.md; don't tune prompts to specific tasks).

### Phase 5: Evaluation harness (≈5 h)

| Step | Commits |
|---|---|
| 5.1 Checker types (R-EV-4) + unit tests | `feat(eval): add deterministic checkers` |
| 5.2 `data/tasks.jsonl` (30–40 tasks, ≥4 per category, R-EV-2) + one reference script per task in `data/reference/`. Prompts must state the photon count / precision they need, so tolerances are fair | `feat(eval): add task set and reference solutions` |
| 5.3 `scripts/make_expected.py` → `data/expected.json` by running references in the sandbox (R-EV-3) | `feat(eval): generate expected values from reference runs` |
| 5.4 `scripts/evaluate.py` with `--mode`, `--limit`, `--resume`, one JSONL line per task, per-task artifacts; optional `nvidia-smi` VRAM sampler | `feat(eval): add resumable evaluation runner` |
| 5.5 `scripts/report.py` → `docs/eval_results.md` + `docs/eval_chart.png` (success rate by model × mode; latency vs success) | `feat(eval): add results report and chart` |
| 5.6 CI smoke eval on 3 tasks with `fake` (R-EV-8) | `ci: add fake-provider evaluation smoke run` |

**Done when:** the fake-provider eval runs in CI; a 3-task real run with the local model produces a report.

### Phase 6: MCP server (≈3 h)

| Step | Commits |
|---|---|
| 6.1 `mcp_server.py` with `describe_simulator`, `run_simulation_script`, `solve` (R-MCP-1/2); check the current `mcp` SDK API first | `feat(mcp): expose simulator, sandbox and agent as MCP tools` |
| 6.2 Tests with an in-process MCP client session (list tools, call each, limits not overridable) | `test(mcp): exercise tools through an MCP client` |
| 6.3 `simagent mcp` command + client config snippet in `docs/mcp.md` | `feat(cli): add mcp command` + `docs: document MCP client setup` |

**Done when:** tests pass; the user connects a real MCP client (e.g. Claude Desktop) and runs a request.

### Phase 7: Benchmark runs: **CHECKPOINT B (user's machine)**

Stop before this phase. Long runs need the user's GPU, Ollama models pulled, a Groq key, and the
laptop plugged in. The agent prepares commands; the user starts them (or allows the agent to).

| Step | Commits |
|---|---|
| 7.1 `make bench` target running, for each model: `--mode baseline` and `--mode repair` over all tasks, with `--resume` | `chore(eval): add benchmark make target` |
| 7.2 Run: local 3B coder, local 1.5B, local 3B general, optional local 7B (partial offload), hosted model. Commit raw results | `data(eval): add benchmark results for <model>` (one commit per model) |
| 7.3 Generate report; write the analysis honestly: where repair helps, where it doesn't, failure categories, latency/cost trade-offs, what 4 GB of VRAM allows | `docs(eval): add benchmark report and analysis` |

**Done when:** `docs/eval_results.md` is generated from committed results only (R-EV-7).

### Phase 8: README, demo, polish (≈3 h)

| Step | Commits |
|---|---|
| 8.1 `scripts/render_demo.py` → `docs/demo.svg` of a real run where a repair happens (recorded, not faked) | `docs: add recorded demo of a self-correcting run` |
| 8.2 README: pitch, demo, quickstart (fake → local model → MCP), architecture diagram, security model table, results table + chart, design decisions, limitations, roadmap | `docs: write README` |
| 8.3 Final pass: coverage ≥ 85 %, CI green, `make` targets documented, `docs/PROGRESS.md` closed | `chore: final quality pass` |

**Done when:** on a fresh clone with Docker installed: `pip install -e .` → `make sandbox-image` →
`simagent solve "..." --provider fake` shows a full repair cycle with no API key and no GPU.
Without Docker, `simagent doctor` and `solve` explain clearly what is missing (one line, exit code 2).

---

## 4. Suggested schedule for the user (around exams)

| Week | Agent work | User (≈30–45 min/day) |
|---|---|---|
| 1 | Phases 0–2 | Install Docker Desktop (WSL2) + Ollama; pull models; review Checkpoint A |
| 2 | Phases 3–6 | Try `simagent solve` by hand; connect Claude Desktop to the MCP server |
| 3 | Phase 7 runs (overnight) + Phase 8 | Read the results honestly; record the demo; update portfolio + CV |

## 5. Possible extensions (only after Phase 8)

- RAG over `docs/` + a tiny "physics notes" corpus; compare agent with/without retrieval.
- Adapter for a real Monte Carlo code (OpenMC) behind the same `Runner` + API-doc pattern.
- Use the checkers as a reward signal for a small preference-tuning experiment (only with real GPU time).
