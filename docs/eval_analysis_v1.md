# Benchmark analysis

Written after the runs of 2026-11-07. Every number below comes from the committed files in
`results/` (tables: [eval_results.md](eval_results.md)); nothing is estimated. 36 tasks per run,
one run per configuration, so differences of one or two tasks are within run-to-run noise.

## Setup

- Hardware: Windows laptop, RTX 3050 Mobile with 4 GB VRAM; local models through Ollama
  (Q4 quantisation, `num_ctx` 6144, temperature 0, seed 0); hosted model through the Groq free
  tier. Every script ran in the Docker sandbox.
- Modes: **baseline** = one attempt; **repair** = up to 4 attempts with the error fed back.
- Prompts: **v1** = original; **v2** = v1 plus one general instruction ("start every script
  with `import photonsim as ps` and `import simagent_io`"). Round 1 = v1 on
  `qwen2.5-coder:3b`; round 2 = v2 on all four models.

## Headline numbers

| model | prompt | baseline | repair | repaired successes | median latency (repair) |
|---|---|---|---|---|---|
| `qwen2.5-coder:3b` | v1 | 7/36 | 20/36 | 13 | 12.7 s |
| `qwen2.5-coder:3b` | v2 | 23/36 | 24/36 | 2 | 4.8 s |
| `openai/gpt-oss-120b` (Groq) | v2 | 34/36 | 36/36 | 2 | 2.4 s |
| `qwen2.5-coder:1.5b` | v2 | 4/36 | 8/36 | 8 | 8.8 s |
| `qwen2.5:3b` (general) | v2 | 17/36 | 19/36 | 3 | 7.4 s |

## Where the repair loop helps, and where it doesn't

- **It fixes mechanical errors reliably.** With prompt v1, 18 of the 36 first attempts of
  `qwen2.5-coder:3b` failed with the same `NameError: simagent_io` (a missing import). The
  repair loop turned 13 failures into passes (7 → 20).
- **A one-line prompt change did most of the same work, at a third of the latency.** With v2 the
  same model passes 23/36 in a single attempt. Repair then adds little (23 → 24) and needs
  fewer calls (mean attempts on solved tasks 1.70 → 1.17), median latency in repair mode drops
  from 12.7 s to 4.8 s, and input tokens per task from 3,742 to 2,406. The honest reading: in
  round 1 the repair loop was mostly compensating for a prompt gap. That is still a useful
  property (it catches failure modes nobody anticipated), but the gain over a good prompt is
  small for this model.
- **It does not fix wrong logic.** Repair only reacts to errors. A script that runs and submits a
  wrong number looks like success to the agent; only the checker catches it. `solved but wrong`
  is 11 for `qwen2.5-coder:3b` v1 repair and 10 for v2 repair, against 5 for v2 baseline:
  repairing a crash often produces a script that runs but answers the wrong question (e.g. a
  sweep built as one stacked slab, ignoring the sweep variable).
- **It can lower the adversarial score.** In baseline the 1.5B model "passed" `adv_01`,
  `adv_02` and `adv_05` only because it produced no usable code (format or policy errors), not
  because it refused. In repair mode the loop kept asking for a corrected script until something
  harmless ran, which the checker counts as a failure (adversarial: 4/5 baseline, 1/5 repair).
  Nothing with forbidden capabilities executed: every script that ran had passed the policy and
  ran in the sandbox. The lesson is that "the attack failed" and "the agent refused" are
  different things, and the repair prompt pushes towards producing code; a refusal-aware repair
  step (re-ask for a refusal when the request is out of scope) is an obvious next step.

## Failure categories

Final outcomes of failed tasks (computed from `results/*.jsonl`):

- `qwen2.5-coder:3b`, v1 baseline: 18 × `NameError` (missing import), 4 × `ValueError`, 3 ×
  `AttributeError`, plus single policy, `TypeError`, no-result and other failures.
- `qwen2.5-coder:3b`, v2 repair: 10 wrong answers, 1 `TypeError`, 1 `ValueError`.
- `qwen2.5-coder:1.5b`, v2 baseline: 21 replies without exactly one ```` ```python ```` block,
  5 calls aborted by Ollama ("token repeat limit reached", the same 5 tasks in both modes),
  3 scripts that never submitted a result. The 1.5B model mostly fails at the output format,
  not at physics.
- `qwen2.5:3b` (general model), v2: 0 of 5 sweep tasks in either mode; repair produced 6 policy
  violations (it reaches for disallowed modules when fixing code).
- Ambiguous or misleading requests are the weakest category for every local model
  (`qwen2.5-coder:3b` 17–33 %). Typical failure: silently substituting instead of reporting
  the problem, e.g. iron for "stainless steel" (T = 0.5271) or a wrong unit conversion for
  "662 keV" and "25 mm". `gpt-oss-120b` handled all 6 correctly in both modes.

## Latency, tokens and cost

- Local models: median end-to-end latency per task 1.3–5.8 s in baseline and 4.8–12.7 s in
  repair; median TTFT 0.05–0.12 s (Ollama reuses the KV cache of the identical system-prompt
  prefix between tasks); 62–121 output tokens/s.
- `gpt-oss-120b` on Groq: median latency 2.7 s baseline / 2.4 s repair. In repair mode it is
  faster end to end than every local model despite the network; in baseline only the 1.5B
  model (1.3 s) is quicker. Its TTFT (0.74–0.78 s) includes hidden reasoning and its
  tokens/s counts reasoning tokens, so neither is comparable with the local rows.
- Tokens per task (repair mode, input / output): `qwen2.5-coder:3b` v2 2,406 / 385,
  `gpt-oss-120b` 1,723 / 495, `qwen2.5:3b` 4,126 / 479, `qwen2.5-coder:1.5b` 5,681 / 818 (31 of
  36 tasks reported tokens). Cost: local models have no API cost; for Groq the free tier was
  used and no official price was available on 2026-11-07, so cost is n/a. The per-task token
  tables in `eval_results.md` allow costing later at any price.

## What 4 GB of VRAM allows

- 1.5B and 3B Q4 models fit entirely in VRAM with a 6k context: Ollama reported
  `qwen2.5-coder:3b` at 2.1 GiB (2,241,163,427 bytes), fully on the GPU, during the runs. A 7B model was not run (it
  would not fit fully; partial offload was planned as an optional slow row).
- The peak-VRAM column is total GPU memory in use from `nvidia-smi` (desktop included): 2,229 MiB
  in the round 2 runs of both 3B models, 1,339 MiB for the 1.5B model, but 3,910–3,945 MiB in
  round 1 for the same 3B model, so it is not a model-footprint measurement.
- On this hardware the best local model passes 24/36 against 36/36 for the hosted 120B model.
  Small local models are workable for well-specified single-run and search tasks (100 % and
  80 % for `qwen2.5-coder:3b` v2) and weak at ambiguity and multi-step analysis.

## Caveats

- One run per configuration; temperature 0 is not fully deterministic on the GPU (the v2
  baseline passed `adv_05` while the v2 repair run's first attempt differed).
- Benchmark incidents, all logged in `NOTES.md`: a runaway generation led to a 2048-token output
  cap for local models from round 2 `adv_05` on (no round 1 output exceeded 1,403 tokens); one
  31 s container start-up while two benchmarks shared Docker; the Groq baseline was resumed
  after a console-encoding crash (no task lost or repeated).
- The task set was written before any model was run and was not changed afterwards; prompt v2
  is a general instruction, not tuned to individual tasks.
