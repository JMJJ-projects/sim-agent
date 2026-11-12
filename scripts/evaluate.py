"""Run the evaluation (R-EV-5, R-STAT-1, R-STAT-2).

    python scripts/evaluate.py --provider ollama --model qwen2.5-coder:3b --mode repair \
        --task-set all --seeds 0,1,2,3,4 --resume

Runs every (task set, seed) pair: each appends one JSON line per task to
results/v2/<provider>-<model>-p<prompt>-<mode>-<task set>-s<seed>.jsonl (after a header line
with the sampling settings), then writes the matching .summary.json. ``--task-set all`` means
dev and held-out, as two separate files per seed. Needs Docker and the simagent-sandbox image.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from simagent import prompts
from simagent.agent import check_model, check_runner, validate_max_attempts
from simagent.config import ConfigError, Settings, load_env
from simagent.evaluation.expected import load_expected
from simagent.evaluation.harness import (
    MODES,
    DailyLimitError,
    EvalConfig,
    fake_model_factory,
    load_prices,
    run_eval,
)
from simagent.evaluation.runinfo import code_commit, ollama_model_info
from simagent.evaluation.summary import read_records, summarise
from simagent.evaluation.tasks import TASK_SETS, load_task_set
from simagent.llm import make_chat_model, resolve_model, seed_supported
from simagent.runners import DockerRunner, RunnerUnavailableError

ROOT = Path(__file__).resolve().parents[1]
V2_TEMPERATURE = 0.7  # R-STAT-2


def parse_seeds(text: str) -> list[int]:
    """``"0,1,2"`` -> ``[0, 1, 2]``; non-negative, no duplicates."""
    try:
        seeds = [int(part) for part in text.split(",") if part.strip()]
    except ValueError:
        raise ConfigError(f"--seeds must be comma-separated integers, got {text!r}") from None
    if not seeds or any(s < 0 for s in seeds) or len(set(seeds)) != len(seeds):
        raise ConfigError(f"--seeds needs distinct non-negative integers, got {text!r}")
    return seeds


def task_set_names(choice: str) -> list[str]:
    return list(TASK_SETS) if choice == "all" else [choice]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Evaluate the agent on a task set.")
    ap.add_argument("--provider", default=None, help="ollama | groq | openai | fake")
    ap.add_argument("--model", default=None)
    ap.add_argument("--mode", choices=MODES, required=True)
    ap.add_argument("--task-set", choices=[*TASK_SETS, "all"], default="dev")
    ap.add_argument("--seeds", default="0", help="comma-separated sampling seeds, e.g. 0,1,2")
    ap.add_argument(
        "--temperature", type=float, default=V2_TEMPERATURE, help="sampling temperature"
    )
    ap.add_argument("--max-attempts", type=int, default=4, help="attempts in repair mode")
    ap.add_argument("--limit", type=int, default=None, help="only the first N tasks of each set")
    ap.add_argument("--resume", action="store_true", help="continue existing results files")
    ap.add_argument("--run-name", default=None, help="prefix; -<task set>-s<seed> is appended")
    ap.add_argument(
        "--prompt-version",
        type=int,
        default=None,
        help="prompt version (default: latest, as in the v2 benchmark plan)",
    )
    ap.add_argument(
        "--delay", type=float, default=0.0, help="seconds to wait between tasks (rate limits)"
    )
    ap.add_argument(
        "--vram",
        action="store_true",
        help="sample memory: per-model from Ollama /api/ps (Ollama runs) and nvidia-smi total",
    )
    ap.add_argument("--no-warmup", action="store_true", help="skip the untimed warm-up call")
    ap.add_argument("--results-dir", type=Path, default=ROOT / "results" / "v2")
    ap.add_argument("--runs-dir", type=Path, default=ROOT / "runs" / "eval")
    return ap.parse_args(argv)


def _progress(rec: dict[str, Any]) -> None:
    mark = "PASS" if rec["passed"] else "fail"
    print(
        f"{mark} {rec['task_id']:<14} {rec['status']:<8} attempts={rec['attempts']} "
        f"{rec['latency_s']:6.1f}s  {rec['check_reason'][:70]}",
        flush=True,
    )


def _safe_stdout() -> None:
    """Never let a console encoding (e.g. cp1252 on Windows) crash a long run on model text."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="replace")


def _write_summary(cfg: EvalConfig) -> dict[str, Any]:
    summary = summarise(read_records(cfg.results_path))
    text = json.dumps(summary, indent=2) + "\n"
    cfg.summary_path.write_text(text, encoding="utf-8", newline="\n")
    return summary


def main(argv: list[str] | None = None) -> int:
    _safe_stdout()
    args = parse_args(argv)
    load_env()
    try:
        seeds = parse_seeds(args.seeds)
        if not 0.0 <= args.temperature <= 2.0:
            raise ConfigError(f"--temperature must be in [0, 2], got {args.temperature}")
        base = Settings.from_env(provider=args.provider, model=args.model)
        base = replace(base, temperature=args.temperature)
        validate_max_attempts(args.max_attempts)
        try:
            # The benchmark keeps using the latest prompt unless told otherwise, so planned
            # runs and their file names do not depend on the agent's default.
            prompt_version = prompts.resolve_version(
                args.prompt_version or prompts.PROMPT_VERSION_LATEST
            )
        except ValueError as exc:
            raise ConfigError(str(exc)) from None
        model_name = resolve_model(base)
        runner = DockerRunner(base.limits)
        check_runner(runner)
        check_model(base)
        info = (
            ollama_model_info(base.ollama_base_url, model_name)
            if base.provider == "ollama"
            else None
        ) or {}
        commit = code_commit(ROOT)
        warmed = args.no_warmup or base.provider == "fake"
        for set_name in task_set_names(args.task_set):
            tasks = load_task_set(set_name, ROOT)
            expected = load_expected(TASK_SETS[set_name].expected_path(ROOT))["tasks"]
            for seed in seeds:
                settings = replace(base, llm_seed=seed)
                cfg = EvalConfig(
                    provider=settings.provider,
                    model=model_name,
                    mode=args.mode,
                    results_dir=args.results_dir,
                    runs_dir=args.runs_dir,
                    max_attempts=args.max_attempts,
                    run_name=args.run_name,
                    limit=args.limit,
                    resume=args.resume,
                    timeout_s=settings.timeout_s,
                    prompt_version=prompt_version,
                    max_output_tokens=(
                        settings.max_output_tokens if settings.provider == "ollama" else None
                    ),
                    delay_s=args.delay,
                    sample_vram=args.vram,
                    ollama_base_url=(
                        settings.ollama_base_url if settings.provider == "ollama" else None
                    ),
                    prices=load_prices(ROOT / "data" / "prices.json"),
                    task_set=set_name,
                    temperature=settings.temperature,
                    seed=seed,
                    seed_supported=seed_supported(settings.provider),
                    model_digest=info.get("digest"),
                    quantization=info.get("quantization"),
                    code_commit=commit,
                )
                if settings.provider == "fake":
                    model_for = fake_model_factory(ROOT)
                else:
                    model = make_chat_model(settings)
                    if not warmed:
                        model.invoke("Reply with OK.")  # load the model before anything is timed
                        warmed = True
                    model_for = lambda task, m=model: m  # noqa: E731
                n = len(tasks[: args.limit] if args.limit else tasks)
                print(f"run {cfg.name}: {n} tasks", flush=True)
                run_eval(cfg, tasks, expected, runner, model_for, progress=_progress)
                summary = _write_summary(cfg)
                print(
                    f"passed {summary['passed']}/{summary['tasks']}; "
                    f"summary written to {cfg.summary_path}",
                    flush=True,
                )
    except DailyLimitError as exc:
        print(
            f"stopped: {exc}\nnothing was recorded for that task; resume after the reset",
            file=sys.stderr,
        )
        return 3
    except (ConfigError, RunnerUnavailableError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
