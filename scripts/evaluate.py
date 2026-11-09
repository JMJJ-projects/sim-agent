"""Run the evaluation (R-EV-5).

    python scripts/evaluate.py --provider ollama --model qwen2.5-coder:3b --mode repair --resume

Appends one JSON line per task to results/<run-name>.jsonl, then writes
results/<run-name>.summary.json. Needs Docker and the simagent-sandbox image.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from simagent import prompts
from simagent.agent import check_model, check_runner, validate_max_attempts
from simagent.config import ConfigError, Settings, load_env
from simagent.evaluation.expected import load_expected
from simagent.evaluation.harness import (
    MODES,
    EvalConfig,
    fake_model_factory,
    load_prices,
    run_eval,
)
from simagent.evaluation.runinfo import code_commit, ollama_model_info
from simagent.evaluation.summary import read_records, summarise
from simagent.evaluation.tasks import load_tasks
from simagent.llm import make_chat_model, resolve_model, seed_supported
from simagent.runners import DockerRunner, RunnerUnavailableError

ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Evaluate the agent on data/tasks.jsonl.")
    ap.add_argument("--provider", default=None, help="ollama | groq | openai | fake")
    ap.add_argument("--model", default=None)
    ap.add_argument("--mode", choices=MODES, required=True)
    ap.add_argument("--max-attempts", type=int, default=4, help="attempts in repair mode")
    ap.add_argument("--limit", type=int, default=None, help="only the first N tasks")
    ap.add_argument("--resume", action="store_true", help="continue an existing results file")
    ap.add_argument("--run-name", default=None)
    ap.add_argument(
        "--prompt-version", type=int, default=None, help="prompt version (default: latest)"
    )
    ap.add_argument(
        "--delay", type=float, default=0.0, help="seconds to wait between tasks (rate limits)"
    )
    ap.add_argument("--vram", action="store_true", help="sample peak VRAM with nvidia-smi")
    ap.add_argument("--no-warmup", action="store_true", help="skip the untimed warm-up call")
    ap.add_argument("--results-dir", type=Path, default=ROOT / "results")
    ap.add_argument("--runs-dir", type=Path, default=ROOT / "runs" / "eval")
    return ap.parse_args(argv)


def _progress(rec: dict[str, Any]) -> None:
    mark = "PASS" if rec["passed"] else "fail"
    print(
        f"{mark} {rec['task_id']:<12} {rec['status']:<8} attempts={rec['attempts']} "
        f"{rec['latency_s']:6.1f}s  {rec['check_reason'][:70]}",
        flush=True,
    )


def _safe_stdout() -> None:
    """Never let a console encoding (e.g. cp1252 on Windows) crash a long run on model text."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _safe_stdout()
    args = parse_args(argv)
    load_env()
    try:
        settings = Settings.from_env(provider=args.provider, model=args.model)
        validate_max_attempts(args.max_attempts)
        try:
            prompt_version = prompts.resolve_version(args.prompt_version)
        except ValueError as exc:
            raise ConfigError(str(exc)) from None
        model_name = resolve_model(settings)
        runner = DockerRunner(settings.limits)
        check_runner(runner)
        check_model(settings)
        tasks = load_tasks(ROOT / "data" / "tasks.jsonl")
        expected = load_expected(ROOT / "data" / "expected.json")["tasks"]
        info = (
            ollama_model_info(settings.ollama_base_url, model_name)
            if settings.provider == "ollama"
            else None
        ) or {}
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
            prices=load_prices(ROOT / "data" / "prices.json"),
            temperature=settings.temperature,
            seed=settings.llm_seed,
            seed_supported=seed_supported(settings.provider),
            model_digest=info.get("digest"),
            quantization=info.get("quantization"),
            code_commit=code_commit(ROOT),
        )
        if settings.provider == "fake":
            model_for = fake_model_factory(ROOT)
        else:
            model = make_chat_model(settings)
            if not args.no_warmup:
                model.invoke("Reply with OK.")  # load the model before anything is timed
            model_for = lambda task: model  # noqa: E731
        print(f"run {cfg.name}: {len(tasks[: args.limit] if args.limit else tasks)} tasks")
        run_eval(cfg, tasks, expected, runner, model_for, progress=_progress)
    except (ConfigError, RunnerUnavailableError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    summary = summarise(read_records(cfg.results_path))
    text = json.dumps(summary, indent=2) + "\n"
    cfg.summary_path.write_text(text, encoding="utf-8", newline="\n")
    print(f"passed {summary['passed']}/{summary['tasks']}; summary written to {cfg.summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
