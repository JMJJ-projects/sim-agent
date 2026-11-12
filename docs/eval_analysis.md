# Benchmark analysis (v2)

Written after the v2 runs of 2026-11-10 to 2026-11-12. Every number below is in the generated
report [eval_results.md](eval_results.md), which is computed from the committed files in
`results/v2/`; nothing is estimated or typed from memory. v1 (temperature 0, one run each) is in
[eval_analysis_v1.md](eval_analysis_v1.md) and is never mixed into these numbers.

## The question and the short answer

**What actually helps a small local model write correct simulation code on a 4 GB laptop GPU?**

1. **A bigger model, even half on the CPU.** The 7B coder at Q4 (44 % of it on the GPU) beats the
   3B coder in the same mode by **16.5 pp on dev and 21.7 pp on held-out**, both with 95 % CIs
   above 0, at about 3.3 times the median latency (32.7 s vs 9.8 s per task).
2. **The repair loop.** Feeding errors back helps both small models on both task sets:
   **+10.6 / +11.7 pp** (3B, dev / held-out) and **+16.7 / +13.3 pp** (1.5B).
3. **Verification helps much less than it catches.** On top of repair, the verifier adds
   **+3.3 pp on held-out for the 3B model** (95 % CI +0.8 to +6.7) and **no measurable
   difference** in the other three local comparisons. It flags wrong answers with very few false
   alarms, but the small models rarely turn a flagged answer into a correct one.
4. **Q8 instead of Q4: no measurable difference** (+5.4 / +9.2 pp, both CIs include 0), at
   3.3 times the latency, because the Q8 model no longer fits in VRAM.
5. **The refusal-aware repair prompt (v3) backfired.** No measurable difference in success against
   v2, no measurable gain on adversarial tasks, and it introduced false refusals: after an ordinary
   crash, small models now often reply `REFUSED:` to a legitimate request.

## Setup

- Hardware: Windows laptop, RTX 3050 Mobile (4 GB VRAM), Docker sandbox for every script; local
  models through Ollama, `openai/gpt-oss-120b` through the Groq free tier.
- Tasks: **dev** (36, the v1 set, seen while building the verifier) and **held-out** (24, written
  and tagged `heldout-frozen` before any verifier code existed). No held-out task was edited or
  excluded, and no check, prompt or threshold was changed after the held-out runs.
- Sampling: temperature 0.7 with the seed passed to the provider. Seeds 0-4 for the main local
  matrix, 0-2 for the quantisation rows, 0-1 for Groq (daily token limit; no baseline mode, a
  CHECKPOINT C decision).
- Modes, all with the same budget of 4 attempts except baseline (1): **repair** feeds errors back;
  **verify** also runs the deterministic verifier on every answer and feeds its findings back.
- Statistics: success is the mean over seeds; CIs are a bootstrap over tasks (10 000 resamples);
  paired differences use the same tasks on both sides; a difference is only called an improvement
  when its 95 % CI excludes 0. McNemar on seed 0 is reported next to it.
- All 90 planned results files are complete, with no harness errors.

## Headline numbers (prompt v3, success with 95 % CI)

| model | task set | baseline | repair | verify |
|---|---|---|---|---|
| `qwen2.5-coder:3b` | dev | 48.9 % (37.8-60.6) | 59.4 % (48.3-70.6) | 62.2 % (52.2-72.2) |
| `qwen2.5-coder:3b` | held-out | 34.2 % (20.0-49.2) | 45.8 % (32.5-60.0) | 49.2 % (35.8-62.5) |
| `qwen2.5-coder:1.5b` | dev | 17.2 % (7.8-28.3) | 33.9 % (22.8-46.1) | 32.8 % (22.2-44.4) |
| `qwen2.5-coder:1.5b` | held-out | 9.2 % (1.7-19.2) | 22.5 % (8.3-39.2) | 22.5 % (8.3-39.2) |
| `openai/gpt-oss-120b` | dev | not planned | 98.6 % (95.8-100.0) | 100.0 % (100.0-100.0) |
| `openai/gpt-oss-120b` | held-out | not planned | 97.9 % (93.8-100.0) | 100.0 % (100.0-100.0) |

Held-out is harder than dev for every local configuration (e.g. 3B verify 62.2 % vs 49.2 %).
The held-out tasks were written as new shapes of question rather than paraphrases of dev, so
they are not of equal difficulty; the gap alone does not show overfitting. What would show it is a
verification gain on dev that vanishes on held-out, and the opposite happened (next section).

## Verification: precise, but the model can't use it

The verifier is a pure function of the recorded answer and the simulator's own trace, so it can be
scored on every run, including repair runs where its findings were not used.

- **It flags wrong answers with few false alarms.** 3B verify on held-out: 36 flagged attempts,
  35 catches, 1 false alarm. On dev: 23 flagged, 19 catches, 4 false alarms (all V-LENGTH). The
  worst false-alarm rate is the 7B model on dev: 6 of 15 flags, all V-LENGTH.
- **It misses a lot.** In the same 3B verify runs, 28 (dev) and 20 (held-out) final answers that
  the checker judges wrong passed the verifier. The checks only look at things a request states
  explicitly (units, energies, lengths, counts, materials, sweep structure, the trace); a wrong
  number with the right shape gets through.
- **Catching is not fixing.** Of the 3B task outcomes with at least one flagged attempt, **7 of 18
  (dev) and 5 of 19 (held-out)** ended correct in verify mode, against 3 of 18 and 1 of 19 in
  repair mode, where the findings were not fed back. So the findings do help, but most flagged
  tasks still end wrong: 4 (dev) and 9 (held-out) end `solved_unverified`, with the findings
  still open when the budget ran out.
- **End to end:** wrong answers (taxonomy class `wrong_answer:*`) drop from 29 to 21 (dev) and
  25 to 21 (held-out) for 3B repair -> verify. Success moves by +2.8 pp on dev (no measurable
  difference) and +3.3 pp on held-out (an improvement, but a small one: the McNemar test on seed
  0 alone sees 1 discordant task, p = 1.0, and this is one of 16 paired comparisons in the report).
  **This gain holds only on held-out, not on dev.**
- **1.5B:** no measurable difference on either set. When it is told about a finding it tends to
  refuse instead of fixing: 5 of 6 (dev) and 7 of 9 (held-out) flagged task outcomes ended
  `refused` in verify mode. See the next section.
- **gpt-oss-120b:** the verifier flagged nothing in either mode. Verify scores 100 % on both sets
  against 98.6 % / 97.9 % for repair, but no measurable difference, and the gap cannot come from
  the verifier since it never fired; it is sampling variation (one dev and one held-out answer
  wrong in repair, both passed by the verifier).

## The refusal rule in the repair prompt backfired

Prompt v3 (R-REF-1) added one rule to the repair prompt: if the request itself is out of scope,
reply `REFUSED:` instead of new code. It was meant to stop the v1 pattern where an adversarial
request was "repaired" into harmless code that ran. Block 6.1b ran the 3B repair mode with prompt
v2 under identical settings, so the comparison is like for like:

| 3B, repair | v2 dev | v3 dev | v2 held-out | v3 held-out |
|---|---|---|---|---|
| success | 61.7 % | 59.4 % | 48.3 % | 45.8 % |
| adversarial passed (tasks x seeds) | 20 / 25 | 19 / 25 | 8 / 10 | 9 / 10 |
| false refusals | 0 | 12 | 0 | 13 |
| ... of which after a failed attempt | 0 | 12 | 0 | 13 |

- Success: **no measurable difference** (-2.2 pp dev, CI -7.2 to +2.8; -2.5 pp held-out, CI -9.2
  to +4.2).
- Adversarial: one more pass on held-out, one fewer on dev: no gain to report.
- **Every 3B false refusal under v3 came after a failed attempt**, that is, in reply to the
  repair prompt. The model reads "if the request is out of scope, refuse" after a crash and
  refuses a legitimate request.
- The 1.5B model shows it at scale: 96 false refusals in 180 dev outcomes in repair mode (91 after
  a failed attempt) and 68 of 120 on held-out (64), against 5 and 4 in baseline, where there is
  no repair prompt. Despite that, its repair mode still beats baseline (+16.7 / +13.3 pp), so the
  loop helps it more than the rule hurts; how much better it would do without the rule was not
  measured (no 1.5B v2 run in v2).
- The bigger models do it too: the 7B model has 8 (dev) and 13 (held-out) false refusals, all
  after a failed attempt.

The rule is general (no task-specific wording) and was logged before the runs, so this is a fair
negative result. It should be narrowed (e.g. only offered together with the R-REF-2 hint, when the
policy rejected a forbidden capability) or removed; that is a change for a later round, measured
on dev first and then on a fresh held-out set, because this held-out set has now been seen.

## Quantisation and model size on 4 GB

| model | dev | held-out | median latency | tokens/s | model size | in VRAM | on GPU |
|---|---|---|---|---|---|---|---|
| 3B Q4_K_M | 62.2 % | 49.2 % | 9.8 s | 69.5 | 2,137 MiB | 2,137 MiB | 100 % |
| 3B Q8_0 | 67.6 % | 58.3 % | 32.8 s | 13.8 | 3,773 MiB | 2,258 MiB | 60 % |
| 7B Q4_K_M | 78.7 % | 70.8 % | 32.7 s | 7.1 | 5,027 MiB | 2,234 MiB | 44 % |

(verify mode, prompt v3; CIs in the report.)

- **Ollama never placed more than 2,258 MiB of a model in VRAM** on this 4 GB card: both larger
  rows sit at 2,234-2,258 MiB in VRAM and run the remainder on the CPU.
- **The 7B model is the best use of that budget.** Against the 3B Q4 row: +16.5 pp on dev (CI +7.0
  to +26.3) and +21.7 pp on held-out (CI +4.7 to +39.4). Of the local models it also has the fewest
  verifier misses (7 dev, 4 held-out) and the best ambiguous-task score (15/18, 10/12). The held-out McNemar on seed 0 is
  not significant (7 / 5, p = 0.774); the bootstrap over all three seeds is the primary measure.
- **Q8 is the worst trade:** no measurable gain over Q4 (+5.4 pp dev, CI -2.8 to +13.7; +9.2 pp
  held-out, CI -1.1 to +20.3) for the same 3.3x latency as the 7B model.
- Throughput collapses once a model spills to the CPU: 69.5 -> 13.8 -> 7.1 output tokens/s.

## Reliability across seeds

At temperature 0.7, a task solved once is not a task solved reliably. For 3B verify on dev, 10
tasks were solved in all 5 seeds, 25 in some, 1 in none; the per-seed success ranges from 52.8 %
to 75.0 %. The 7B row is steadier (20 all, 14 some, 2 none over 3 seeds). Held-out 3B repair
ranges from 20.8 % to 54.2 % across seeds: single runs, like v1's, can mislead by more than any
effect measured here.

## Caveats

- Groq ran 2 seeds and no baseline; the 6.3 rows ran 3 seeds against 5 for the 3B Q4 row. Paired
  comparisons use each task's mean over its own seeds, so they remain valid, but intervals are
  wider than with equal seeds.
- 16 paired comparisons are reported; at 95 % roughly one could exclude 0 by chance. The two large
  effects (repair vs baseline, 7B vs 3B) hold on both task sets; the small verify gain does not.
- `gpt-oss-120b` is a reasoning model: its tokens/s and TTFT include hidden reasoning and are not
  comparable with the local rows.
- One Q8 results file records its code commit as `c2ed85fc9b7b-dirty`: the working tree held
  uncommitted results files at the time; no source file differed (`git log` shows no `src/`
  change after `507e521`, the commit of the 6.1 runs).
- The taxonomy and the "after a failed attempt" counts are rule-based classifications of the
  recorded data; [taxonomy_sample.md](taxonomy_sample.md) lists 20 seeded random failures with
  their evidence for a spot-check.
