# Plan v2: "What actually helps a small local model?"

> **How to use this file:** work through the phases in order; a phase starts only when the previous
> phase's **Done when** checks pass. Each step lists the commit(s) it should produce (a step may
> need an extra `fix:`/`refactor:` commit, never a "WIP" commit). `SPEC.md` (after Phase 0) is the
> source of truth; this file is the order of work.
> **Library rule:** LangGraph, LangChain integrations, Ollama, the `mcp` SDK and OpenMC change.
> Check the installed version and real API before coding against them. Never code from memory.
> Record anything surprising in `docs/NOTES.md`.

**Two parts, two time boxes:**
- **Part A (Phases 0–7):** about one weekend of agent work (~14–18 h) plus checkpoints and
  overnight benchmark runs. Ends with release `v0.2.0`.
- **Part B (Phases 8–10):** OpenMC + retrieval, about one more weekend. **Starts only after the
  user says go at CHECKPOINT D.** Ends with release `v0.3.0`.

Anything that doesn't fit becomes a Roadmap bullet. Do not start Part B items early.

---

## 0. What changes, in one picture

```
v1:  request ─▶ generate ─▶ policy ─▶ execute ─▶ evaluate_run ─▶ repair ─┐ … ─▶ finalize
v2:  request ─▶ facts ─▶ generate ─▶ policy ─▶ execute(+trace) ─▶ evaluate_run ─▶ verify ─▶ finalize
                                        ▲                              │ error       │ findings
                                        └──────────── repair ◀─────────┴─────────────┘
     (same attempt budget for every repair, whatever triggered it)

eval: dev (36) + held-out (24, frozen first) × seeds 0–4 × {baseline, repair, verify}
      → stats (bootstrap CIs, paired tests, pass^k) → taxonomy → report
Part B: --backend openmc (own image + read-only nuclear data) · --docs {full,retrieve} (BM25) · cross-validation
```

**Fixed decisions (do not re-debate):**

| Topic | Decision |
|---|---|
| Held-out set | 24 tasks, written and tagged `heldout-frozen` **before** any verifier code |
| Sampling for v2 runs | temperature 0.7, seeds 0–4 for local models; 3 seeds for the hosted model (rate limits) |
| Statistics | bootstrap over tasks (10 000, fixed RNG seed) for CIs and paired differences; exact McNemar on seed 0; pass^k counts. NumPy + `math` only |
| Trace | recorded by `photonsim` inside the sandbox, written by `simagent_io`; never trusted from the model |
| Request facts | deterministic regex + materials list; silent when unsure |
| Verifier | pure function, deterministic checks, zero false alarms on dev references (Docker test); same `max_attempts` budget as repair |
| Models (Part A matrix) | `qwen2.5-coder:3b` (Q4), `qwen2.5-coder:1.5b` (Q4), Groq `openai/gpt-oss-120b`. Quantisation study adds 3B Q8 and a 7B coder Q4 |
| VRAM | Ollama `/api/ps` (`size`, `size_vram`) per model, not `nvidia-smi` total |
| OpenMC (Part B) | official image pinned by digest; photon data only, outside the repo, mounted read-only |
| Retrieval (Part B) | BM25 over API-reference chunks; no embeddings, no vector DB |
| Graph change | add nodes `facts` (start) and `verify` (after `evaluate_run`); keep existing node names |

---

## Phase 0: Spec merge (≈30 min)

| Step | Commits |
|---|---|
| 0.1 Merge `SPEC-v2.md` into `SPEC.md` as sections 9–18 (keep IDs); delete `SPEC-v2.md` | `docs(spec): add v2 requirements for verification, statistics and OpenMC` |
| 0.2 Commit `PLAN-v2.md` and the updated `CLAUDE.md`; add a "v2" section to `docs/PROGRESS.md`; move `docs/eval_analysis.md` to `docs/eval_analysis_v1.md` (update links) | `docs: add v2 plan and progress section` |

**Done when:** `SPEC.md` contains every v2 ID; all tests still pass.

---

## Phase 1: Held-out task set (≈2 h), then **CHECKPOINT A**

| Step | Commits |
|---|---|
| 1.1 Write `data/tasks_heldout.jsonl` (24 tasks, R-HO-1/2/3) and reference scripts in `data/reference/heldout/`. Different materials/energies/phrasings from the dev set; new instances of v1's ambiguity failure modes | `data(eval): add 24-task held-out set` |
| 1.2 Generalise `scripts/make_expected.py` with `--task-set` (dev/heldout); generate `data/expected_heldout.json` in the Docker sandbox | `feat(eval): support several task sets in make_expected` + `data(eval): add expected values for the held-out set` |
| 1.3 Task loader + tests accept both sets; `tests/test_tasks.py` checks schema, category counts and that no held-out prompt is a near-duplicate of a dev prompt (normalised token overlap below a threshold) | `test(eval): validate the held-out set` |
**Done when:** both sets load, expected values exist for every non-refusal task, tests pass.

**CHECKPOINT A: stop.** Update `PROGRESS.md` and show the user a table of the 24 held-out prompts
(id, category, prompt, checker type). Ask: "Do these read like questions a real user would ask, and
do any look like copies of the dev tasks?" The user approves or asks for changes. Requested changes
go in a normal follow-up commit (`data(eval): revise held-out tasks after review`, regenerating the
expected values), never by rewriting pushed history.

**Only after approval:** create the annotated tag `heldout-frozen` on the last held-out commit (the
message lists the R-HO rules), then ask the user to push `main` and the tag. From then on the set is
frozen for good.

---

## Phase 2: Repeated runs and statistics (≈3 h)

| Step | Commits |
|---|---|
| 2.1 Config: temperature and seed per run; results-file header stores provider, model, tag/digest if available, temperature, seed, `seed_supported`, prompt version, mode, task set, code commit (R-STAT-2) | `feat(eval): record sampling settings in results headers` |
| 2.2 `scripts/evaluate.py --seeds 0,1,2 --task-set {dev,heldout,all}`; one results file per (config, seed); `--resume` per file (R-STAT-1). Results naming: `results/v2/<provider>-<model>-<mode>-<taskset>-s<seed>.jsonl` | `feat(eval): run several seeds and task sets` |
| 2.3 `src/simagent/evaluation/stats.py`: outcome matrix builder, bootstrap CI, paired bootstrap difference, exact McNemar, pass^k counts, and the wording helper for R-STAT-6. Tests with hand-computed cases | `feat(eval): add bootstrap CIs, paired tests and reliability counts` |
| 2.4 `scripts/bench.py` reads `data/bench_plan_v2.json` (runs listed with round, model, mode, task set, seeds, delay, `vram`), runs them in order with resume, and prints an ETA from the per-task medians of finished runs | `feat(eval): add v2 benchmark plan runner with ETA` |
| 2.5 Fake-provider smoke: 3 tasks × 2 seeds × 2 modes in CI, then stats on the result (proves the pipeline end to end, claims nothing) | `ci: run the v2 statistics pipeline on fake results` |

**Done when:** a fake run over both task sets with 2 seeds produces stats with CIs; CI green.

---

## Phase 3: Provenance trace (≈2 h)

| Step | Commits |
|---|---|
| 3.1 `photonsim` recorder: records `simulate`/`sweep` calls when the image's env flag is set; capped (R-TRACE-1/2). Unit tests outside Docker using the flag | `feat(sim): record simulation calls for provenance` |
| 3.2 `simagent_io.submit` writes `/out/trace.json`; `RunResult` gains `trace`; artifacts save it (R-AG-7 extended). Rebuild sandbox image (bump image tag) | `feat(runner): return the provenance trace with each run` |
| 3.3 Policy R-POL-6: reject assignment to attributes of imported modules and any reference to recorder internals; tests for each bypass attempt (alias imports, `setattr`, `vars(...)`, `__dict__` already blocked, etc.) | `feat(policy): forbid patching imported modules` |
| 3.4 Docker test (R-TRACE-3): policy disabled, script writes a fake `/out/trace.json` then submits; the recorder's trace wins (or the run is flagged) | `test(sandbox): prove the trace cannot be forged` |
| 3.5 Re-run `make_expected.py` for dev and held-out so references now carry traces (expected values must not change: assert equal) | `data(eval): regenerate expected values with traces` |

**Done when:** every reference run returns a trace; forging tests pass; expected values unchanged.

---

## Phase 4: Request facts and the verifier (≈4–5 h), then **CHECKPOINT B**

| Step | Commits |
|---|---|
| 4.1 `request_facts.py` (R-REQ-1/2/3) with ≥ 40 test phrasings **not** taken from either task set (units, ranges, aliases, unknown materials, percent, counts, seeds) | `feat(agent): extract request facts deterministically` |
| 4.2 `verify.py` with the R-VER-2 checks, one function per check ID, each with unit tests on synthetic traces | `feat(verify): add deterministic verification checks` |
| 4.3 Docker test R-VER-3: all dev references pass with zero `fail` findings. Narrow or remove any check that fires; log each change in `NOTES.md` | `test(verify): references pass the verifier` |
| 4.4 Graph: `facts` node at start, `verify` node after a successful `evaluate_run`; findings → `repair` within the same budget; `solved_unverified` status (R-VER-4/5/6). Regenerate `docs/graph.mmd`. Update the fake-provider e2e test: wrong-but-running script → verify finding → repaired → solved | `feat(agent): verify answers against the request and the trace` + `docs: regenerate graph diagram` |
| 4.5 CLI `--mode {baseline,repair,verify}`; output shows findings; MCP `solve` defaults to `verify` and returns findings | `feat(cli): add verify mode and show findings` + `feat(mcp): return verification findings` |
| 4.6 Verifier-quality metrics from recorded attempts: catches, false alarms, misses (R-VER-7) | `feat(eval): measure verifier catches and false alarms` |

**Done when:** offline demo (fake provider) shows a wrong answer caught and repaired; all tests pass.

**CHECKPOINT B: stop.** Show the user: the list of checks with one example finding each, every check
you narrowed in 4.3 and why, and the verifier run **offline** over the v1 results files (they have
`result.json` but no trace: run only the checks that don't need a trace, and say so). This gives a
first estimate of how many v1 wrong answers would have been caught. Do **not** use held-out data.
The user says go or asks for changes.

---

## Phase 5: Taxonomy and refusal (≈2–3 h)

| Step | Commits |
|---|---|
| 5.1 `taxonomy.py` (R-TAX-1/2), table-driven tests covering every class | `feat(eval): add deterministic failure taxonomy` |
| 5.2 Report: stacked taxonomy chart + table per configuration; classify v1 results as history (R-TAX-3) | `feat(report): add failure taxonomy chart` |
| 5.3 `docs/taxonomy_sample.md` generator: 20 seeded random failures with class + evidence (R-TAX-4) | `feat(report): add taxonomy spot-check sample` |
| 5.4 Refusal-aware repair: prompt rule (R-REF-1) and the deterministic "you may refuse" hint (R-REF-2), with tests; log the prompt change in `NOTES.md` | `feat(agent): allow refusal during repair for out-of-scope requests` |

**Done when:** fake results produce the taxonomy chart; refusal tests pass.

---

## Phase 6: Benchmark runs (Part A), with **CHECKPOINT C** first

**CHECKPOINT C: stop before any real run.** Show the user `data/bench_plan_v2.json`, the ETA for
each block from a timing probe (run 3 tasks per local model and 2 on Groq, then extrapolate),
disk space for results, and what they need running (Ollama, Docker Desktop, laptop plugged in,
sleep disabled). Check the Groq free-tier limits on the official page **now** and set the delay.
Get the go-ahead. The user may split blocks over several nights.

Planned runs (`--task-set all` = dev 36 + held-out 24):

| Block | Runs | Rough size |
|---|---|---|
| 6.1 Main local | `qwen2.5-coder:3b` and `qwen2.5-coder:1.5b` × {baseline, repair, verify} × seeds 0–4 | 30 runs × 60 tasks |
| 6.2 Hosted | Groq `openai/gpt-oss-120b` × {baseline, repair, verify} × seeds 0–2 | 9 runs × 60 tasks, rate-limited |
| 6.3 Quantisation (R-QV-1/2/3) | 3B Q8_0 and 7B coder Q4_K_M × verify × seeds 0–2 (+ the 3B Q4 verify rows from 6.1) | 6 runs × 60 tasks |

| Step | Commits |
|---|---|
| 6.0 `ollama /api/ps` sampler replaces the `nvidia-smi` sampler for per-model VRAM (keep `nvidia-smi` total as a secondary column) | `feat(eval): measure per-model VRAM from Ollama` |
| 6.1–6.3 Run each block; commit results per model as each finishes (so nothing is lost) | `data(eval): add v2 results for <model> (<modes>, seeds <list>)` |
| 6.4 Check every planned run is complete (report lists missing runs); re-run only failed infrastructure tasks (log them) | `data(eval): complete v2 benchmark` (if needed) |

**Done when:** every planned run is complete or explicitly marked skipped with the reason.

---

## Phase 7: Report, analysis, README, release (≈3 h)

| Step | Commits |
|---|---|
| 7.1 `scripts/report.py` v2 sections (R-REP-1): headline table with CIs, paired comparisons (repair vs baseline, verify vs repair) for dev and held-out separately, pass^k, taxonomy, verifier quality, quantisation chart. Regenerate `docs/eval_results.md` and charts | `feat(report): add v2 results with confidence intervals` + `docs: regenerate v2 results` |
| 7.2 `docs/eval_analysis.md` rewritten for v2 (R-REP-2). Lead with the most interesting **true** finding, whatever it is (including "verification did not help measurably", if that is what the numbers say). Separate dev and held-out; flag any result that only holds on dev | `docs: add v2 benchmark analysis` |
| 7.3 README (R-REP-3): new headline question and answer, one chart, short; v1 story kept as one paragraph with a link | `docs: rewrite README for v2` |
| 7.4 `docs/design_v2.md` (R-REP-4), including "Questions a reviewer might ask" | `docs: add v2 design notes` |
| 7.5 Re-record `docs/demo.svg` with a real `verify` run where a finding triggers a repair (local model; if none happens naturally in 5 tries, use the fake provider and label it as such) | `docs: re-record demo with verification` |
| 7.6 Final pass: fresh clone, `pip install -e .`, offline demo, `doctor`; full test suite with Docker; coverage ≥ 85 %; ruff, mypy clean; PROGRESS self-review table mapping every Part A requirement to its tests | `chore: v2 part A final pass` |

**Done when:** all of the above, CI green.

**CHECKPOINT D: stop.** Report to the user: headline results, anything surprising, and what Part B
would add. Ask for (1) the go-ahead to tag `v0.2.0` and publish a GitHub release (draft the release
notes: verification, held-out set, statistics, taxonomy, quantisation study, and the honest
headline), and (2) whether to start Part B now, later, or not at all.

---

# Part B (only after the user says go)

## Phase 8: OpenMC backend (≈4 h), with **CHECKPOINT E** inside

| Step | Commits |
|---|---|
| 8.1 Read the current OpenMC docs (installation with Docker, photon transport, fixed-source settings, data configuration). Find the official image and its digest; find the **smallest** official way to get photon data for the needed elements (the official data libraries, or a per-element downloader if it is maintained and uses official data). Write findings in `NOTES.md` | `docs: record OpenMC image and data findings` |

**CHECKPOINT E: stop.** Tell the user: image size, data size, disk space needed, download time, and
the exact command for `scripts/get_openmc_data.py` (they run it; it needs network). Get the go-ahead.

| Step | Commits |
|---|---|
| 8.2 `sandbox/openmc/Dockerfile` FROM the pinned image + `simagent_io`; Makefile target; same hardening flags; per-backend limits (R-OMC-1) | `build(sandbox): add OpenMC sandbox image` |
| 8.3 `scripts/get_openmc_data.py` (R-OMC-2) and mounting the data read-only; `doctor` checks (R-OMC-8) | `feat(openmc): add nuclear data setup and doctor checks` |
| 8.4 Backend abstraction: `--backend`, per-backend policy profile (R-OMC-3), API reference, runner image and limits; photonsim stays the default and its tests don't change | `refactor(agent): make the simulation backend pluggable` + `feat(policy): add OpenMC policy profile` |
| 8.5 Docker tests: a minimal OpenMC photon slab run inside the sandbox; network blocked; data read-only; timeout enforced | `test(sandbox): run OpenMC in the hardened sandbox` |

**Done when:** a hand-written OpenMC script runs through `simagent run-script --backend openmc`.

---

## Phase 9: OpenMC API reference, tasks, verification, retrieval (≈5 h)

| Step | Commits |
|---|---|
| 9.1 `docs/openmc_api.md` (R-OMC-4): short chunks with headings; a Docker test executes every snippet | `docs(openmc): add tested API reference for photon slab problems` |
| 9.2 `data/tasks_openmc.jsonl` + references + `data/expected_openmc.json` (R-OMC-5) | `data(eval): add OpenMC task set` + `data(eval): add OpenMC expected values` |
| 9.3 OpenMC verification (R-OMC-6): extract materials, thicknesses, source energy and particle count from the run; reuse backend-independent checks. References pass with zero `fail` findings | `feat(verify): verify OpenMC runs` |
| 9.4 `retrieval.py` (R-RAG-1/2) + `--docs {full,retrieve}`; recall@k from reference API usage (R-RAG-3); tests on a toy corpus | `feat(agent): retrieve API reference chunks with BM25` + `feat(eval): measure retrieval recall` |

**Done when:** fake-provider e2e passes on the OpenMC backend in both docs modes.

---

## Phase 10: Cross-validation, OpenMC runs, report, release (≈4 h + overnight runs)

| Step | Commits |
|---|---|
| 10.1 `scripts/crossval.py` (R-OMC-7); run it; commit `results/crossval.json` and chart | `feat(eval): add photonsim vs OpenMC cross-validation` + `data(eval): add cross-validation results` |

**CHECKPOINT F: stop before the OpenMC benchmark.** Same as C: plan, timing probe, ETA, go-ahead.

| Step | Commits |
|---|---|
| 10.2 Runs: `qwen2.5-coder:3b` and Groq `gpt-oss-120b` × {repair, verify} × docs {full, retrieve} on OpenMC tasks, seeds 0–2; plus `qwen2.5-coder:3b` verify × docs retrieve on photonsim dev+held-out, seeds 0–2 (R-RAG-4) | `data(eval): add OpenMC results for <model>` |
| 10.3 Report sections for OpenMC, retrieval and cross-validation; update analysis, README (one extra short section + chart), design doc | `feat(report): add OpenMC, retrieval and cross-validation sections` + `docs: update analysis and README for OpenMC` |
| 10.4 Final pass as in 7.6, with OpenMC tests skipped cleanly when the image/data are absent (CI builds the OpenMC image only if feasible within CI limits; otherwise document why it is skipped) | `chore: v2 part B final pass` |

**CHECKPOINT G: stop.** Report results; ask for the go-ahead to tag `v0.3.0` and publish the release.

---

## Roadmap (not in this plan; list in README)

- Fine-tune the 1.5B model on its own verified successes (rejection-sampling fine-tuning, QLoRA),
  with the verifier as the filter; compare on the held-out set.
- A tool-calling agent (MCP tools step by step) vs the script writer, same tasks and budget.
- Clarifying questions for ambiguous requests (interactive mode) instead of error reports.
