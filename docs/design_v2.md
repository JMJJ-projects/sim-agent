# Design notes (v2)

One short section per v2 decision: what was chosen, the trade-off, and the alternative rejected.
Numbers come from [eval_results.md](eval_results.md); the discussion is in
[eval_analysis.md](eval_analysis.md); dated details and incidents are in [NOTES.md](NOTES.md).

## A held-out set frozen before the verifier

**Chosen:** 24 new tasks (same categories and checkers as dev), committed and tagged
`heldout-frozen` before any verification code existed. Never edited since; a broken task would be
excluded with the reason, not fixed. No check, prompt or threshold may change because of a
held-out result.

**Trade-off:** 24 tasks give wide intervals (often ±12 pp), and once results are seen the set is
spent for future tuning rounds.

**Rejected:** evaluating only on dev. The verifier's checks were designed while looking at dev
reference scripts and v1 failures; a gain measured only there could be the checks fitting dev.
Also rejected: paraphrases of dev tasks, which would share their blind spots (a near-duplicate
test keeps token-set Jaccard against every dev prompt below 0.6; the maximum is 0.54).

## Temperature 0.7 and several seeds

**Chosen:** temperature 0.7 with the seed passed to the provider; seeds 0-4 for the main local
matrix, 0-2 for the quantisation rows, 0-1 for the hosted model (its daily token limit). Every
setting is in each results file's header; resuming with different settings is refused.

**Trade-off:** 5x the compute of a single run, and a single answer is no longer reproducible
across GPUs, only the distribution is.

**Rejected:** temperature 0 with one run (v1's setup). It hides variance instead of removing it:
GPU inference at temperature 0 was already not fully deterministic in v1, and the v2 seed ranges
show how much one run can mislead (3B repair on held-out: 20.8 % to 54.2 % across seeds).

## Bootstrap over tasks, paired, plus McNemar on one seed

**Chosen:** success = each task's pass rate over seeds, averaged; 95 % CI from a percentile
bootstrap over tasks (10 000 resamples, fixed RNG seed). Comparisons bootstrap the per-task
difference, so they are paired by task. An exact McNemar test on seed 0 is reported alongside.
A difference is only called an improvement when its CI excludes 0 (enforced by a tested wording
helper). NumPy and `math` only.

**Trade-off:** the task bootstrap treats the task set as a sample of possible tasks, which is the
question being asked, but it gives wide intervals with 24-36 tasks. McNemar on one seed throws
away the other seeds, which is why it is secondary.

**Rejected:** an unpaired test on two proportions (ignores that both modes see the same tasks,
which is most of the variance); Wilson intervals over tasks x seeds (would treat seeds of one task
as independent tasks and overstate precision); mixed-effects models (more assumptions and a
dependency for a modest gain in power).

## The trace comes from the simulator, not the model

**Chosen:** `photonsim` itself records every `simulate()` call and sweep point inside the sandbox
(materials, thicknesses, energy, photon count, results). `simagent_io.submit()` writes it next to
the result and overwrites anything the script put there. The static policy keeps generated code
away from the recorder and from `os` (R-POL-6). Verification compares the answer with this
record.

**Trade-off:** it only sees what goes through the public API; a script that computes an answer
without simulating gets no trace (the verifier then skips the trace checks rather than guessing).
With the policy disabled, a script could still tamper with its own process; that is the same trust
boundary as the result itself, and the sandbox limits the damage.

**Rejected:** asking the model to report what it simulated. That is a claim, not evidence, and
the failures the verifier is meant to catch (a sweep stacked into one slab, the wrong unit) are
exactly the cases where the model's own account would be wrong.

## Deterministic checks, silent when unsure

**Chosen:** request facts come from regular expressions and a materials list (units, energies,
thicknesses, lists, ranges and steps, counts, materials, unknown materials) and say nothing when
unsure. The verifier is a pure function of facts, result and trace with nine checks (range,
energy, length, count, material, unknown material, sweep structure, monotonicity as a warning,
consistency with the trace). It had to pass all 32 runnable dev references with zero failures
before any benchmark run; no check was narrowed after running them.

**Trade-off:** it misses wrong answers with the right shape (the report counts the misses: e.g.
20 for the 3B model in verify mode on held-out) and it cannot judge intent. A candidate rule that
removed the four known false alarms of the v1 replay was rejected because it also lost two catches.

**Rejected:** an LLM judge or self-critique. It would be non-reproducible, could be argued with,
would cost another model call per attempt on a 4 GB GPU, and would share the generating model's
blind spots. Being a pure function also lets the verifier score every recorded run, including
baseline and repair runs, which is what makes "would it have caught this?" measurable.

## One attempt budget for every repair

**Chosen:** `verify` mode is the repair loop plus the verify node, with the same 4 attempts.
A verifier finding uses an attempt exactly like a crash does. If the budget runs out with findings
left, the answer is returned as `solved_unverified` and judged by the checker like any answer.

**Trade-off:** a finding can use the attempt that would have fixed a crash, so verify can in
principle score below repair.

**Rejected:** extra attempts for verification. Any gain would then confound "checking helps" with
"more tries help".

## Per-model VRAM from Ollama, not `nvidia-smi`

**Chosen:** Ollama's running-models API (`/api/ps`: `size`, `size_vram`), sampled during runs;
the share on the GPU is `size_vram / size`.

**Rejected:** `nvidia-smi` total memory, which in v1 moved between 2.2 GB and 3.9 GB for the same
model depending on what else the desktop was doing.

## Part B decisions (not built yet)

- **BM25, not embeddings, for retrieval over the OpenMC API reference:** no vector store or
  embedding model to fit beside the generator on 4 GB, deterministic and easy to test; the
  trade-off is weaker matching of paraphrases. To be measured against the full reference.
- **OpenMC data:** the official image pinned by digest, photon data only, kept outside the repo
  and mounted read-only; the same sandbox flags as `photonsim`.

These start only if Part B is approved at CHECKPOINT D.

## Questions a reviewer might ask

**Isn't the verifier just fitted to the dev set?** It was designed on dev, so that was the risk
the held-out set was built for. The gain from verification is larger on held-out (3B: +3.3 pp,
95 % CI +0.8 to +6.7) than on dev (+2.8 pp, no measurable difference), and false alarms on
held-out are low (1 of 36 flagged attempts for the 3B model).

**Is +3.3 pp real?** Its bootstrap CI excludes 0, so the report may call it an improvement, but it
is small, the McNemar test on seed 0 sees one discordant task (p = 1.0), it is one of 16 paired
comparisons, and it does not repeat on dev or for the 1.5B model. The analysis says exactly this.

**Then why keep verification?** Because it is precise and cheap: on held-out it caught 35 wrong
answers with one false alarm for the 3B model, and it costs no model call. What limits it is the
model's ability to act on a finding (7 of 18 flagged dev tasks and 5 of 19 held-out ended
correct), not the checks. A stronger model or better repair messages would use it more; that is a
measurable next step, not an assumption.

**Why does verify sometimes score lower (1.5B on dev, -1.1 pp)?** The 1.5B model answers a finding
with a refusal: 5 of 6 flagged dev tasks ended `refused`. That comes from the v3 repair prompt's
refusal rule (below), not from the checks.

**Did a prompt change backfire?** Yes. Prompt v3 added "if the request is out of scope, refuse" to
the repair prompt. Compared like for like with v2 (block 6.1b), it brought no adversarial gain and
caused 12 (dev) and 13 (held-out) false refusals for the 3B model, all after a failed attempt.
It was not changed after seeing this, because that would tune on the held-out set; the fix is a
roadmap item that needs a fresh held-out set.

**Is the 7B result an artefact of more seeds or more time?** It had fewer seeds (3 against 5) and
the same 4-attempt budget. It is slower (median 32.7 s per task against 9.8 s), and it runs with
only 44 % of its weights on the GPU. Against the 3B Q4 row it gains 16.5 pp (dev) and 21.7 pp
(held-out), both CIs above 0.

**Why is the hosted model at 100 % in verify mode if the verifier never fired?** Sampling
variation: the verifier flagged nothing for `gpt-oss-120b` in either mode, and the difference to
repair (98.6 % and 97.9 %) is reported as no measurable difference.

**Could the model forge the trace to pass verification?** Not with the policy on: generated code
cannot import `os`, reach the recorder or patch imported modules, and `submit()` overwrites any
trace file the script wrote. Docker tests with the policy disabled show that forging before
`submit()` fails; the remaining gap (tampering after `submit()` with the policy off) is documented
in NOTES.md and is the same boundary as forging the result itself.

**Why count a refusal of a legitimate request as a failure? Refusing is safe.** Because the user
asked a valid question and got no answer. The taxonomy keeps `false_refusal` separate from wrong
answers and from `not_refused`, so "safe but useless" is visible rather than hidden in a success
rate.
