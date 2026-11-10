"""Resumable evaluation runner (R-EV-5).

For every task: a fresh agent run (baseline = ``max_attempts=1``, repair = the full loop,
verify = the full loop plus verification with the same budget, R-VER-6), the
deterministic checker against the reference result, and one JSON line appended to
``results/<run-name>.jsonl``. Lines are flushed one by one, so an interrupted run resumes with
``--resume``. Per-task artifacts go to ``runs/eval/<run-name>/<task-id>/`` (gitignored).

A results file starts with one header line (``"kind": "header"``) holding the sampling settings,
task set, model digest and code commit (R-STAT-2); resuming a file whose header disagrees with
the current settings is refused, so runs with different settings never mix. v1 files have no
header and are still readable.

The evaluation always uses the Docker sandbox; the unsafe local runner is rejected (R-SBX-8).
With ``--provider fake`` each task's scripted reply is its own reference solution: this proves
the harness end to end and says nothing about model accuracy (R-EV-8).
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from simagent.artifacts import ArtifactWriter
from simagent.config import ConfigError
from simagent.evaluation.checkers import CheckInput, needs_expected, run_checker
from simagent.evaluation.runinfo import FetchJson, ollama_loaded
from simagent.evaluation.tasks import Task
from simagent.graph import solve
from simagent.llm import ScriptedChatModel
from simagent.nodes import AgentDeps, AttemptHook
from simagent.request_facts import RequestFacts
from simagent.request_facts import extract as extract_facts
from simagent.runners.base import Runner, RunnerUnavailableError
from simagent.runners.local import LocalRunner
from simagent.state import AgentState, AttemptRecord, FinalAnswer
from simagent.verify import failures, verify

MODES = ("baseline", "repair", "verify")
ANSWERED = ("solved", "solved_unverified")
HEADER_KIND = "header"
HEADER_SCHEMA = 2
# Header fields that must match to resume a results file (sampling and run identity).
RESUME_KEYS = (
    "provider",
    "model",
    "model_digest",
    "mode",
    "task_set",
    "temperature",
    "seed",
    "prompt_version",
    "max_attempts",
    "max_output_tokens",
)


def _file_safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def run_name_for(
    provider: str,
    model: str,
    mode: str,
    prompt_version: int,
    task_set: str | None = None,
    seed: int | None = None,
) -> str:
    """Default run name, safe as a file name.

    v1: ``<provider>-<model>-p<version>-<mode>``; v2 (a seed is given):
    ``<provider>-<model>-p<version>-<mode>-<task set>-s<seed>`` (R-STAT-1).
    """
    base = f"{provider}-{model}-p{prompt_version}-{mode}"
    return _file_safe(base + seed_suffix(task_set, seed))


def seed_suffix(task_set: str | None, seed: int | None) -> str:
    """``-<task set>-s<seed>`` for a v2 run; empty for a v1 run (no seed)."""
    return "" if seed is None else f"-{task_set or 'dev'}-s{seed}"


RATE_LIMIT_MARKERS = ("RateLimit", "rate limit", "rate_limit", "429")


# A daily quota (tokens or requests per day) will not clear by waiting minutes: stop the run
# without recording the task, so a later run resumes it instead of scoring a quota stop as a
# model failure.
DAILY_LIMIT_MARKERS = ("per day", "TPD", "RPD")


class DailyLimitError(RuntimeError):
    """The provider's daily quota is used up; the run stops and the task is not recorded."""


class RateLimitedError(RuntimeError):
    """The provider rate-limited a model call; the task should be retried later."""


def fake_reply(task: Task, root: Path) -> str:
    """Scripted reply for the fake provider: the task's reference solution."""
    text = (root / task.reference).read_text(encoding="utf-8")
    if task.runs_reference:
        return f"Reference solution for {task.id}.\n\n```python\n{text.rstrip()}\n```\n"
    return text


def price_note(prices: dict[str, Any], provider: str, model: str) -> str | None:
    """The price table's note for a model (shown instead of a cost), if any."""
    entry = (prices.get("models") or {}).get(f"{provider}/{model}")
    note = entry.get("note") if isinstance(entry, dict) else None
    return str(note) if note else None


def load_prices(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"models": {}}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def cost_usd(
    prices: dict[str, Any], provider: str, model: str, tokens_in: int | None, tokens_out: int | None
) -> float | None:
    """Estimated cost from the dated price table; None when no price or tokens are unknown."""
    entry = (prices.get("models") or {}).get(f"{provider}/{model}")
    if entry is None or tokens_in is None or tokens_out is None:
        return None
    if entry.get("input_per_mtok") is None or entry.get("output_per_mtok") is None:
        return None  # e.g. free tier with no official price: the report shows the entry's note
    return (
        tokens_in * float(entry["input_per_mtok"]) + tokens_out * float(entry["output_per_mtok"])
    ) / 1e6


class VramSampler:
    """Samples GPU memory use with nvidia-smi on a thread; ``peak_mib`` is None if unavailable."""

    def __init__(self, interval_s: float = 0.5) -> None:
        self.interval_s = interval_s
        self.exe = shutil.which("nvidia-smi")
        self.peak_mib: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> int | None:
        assert self.exe is not None
        try:
            out = subprocess.run(
                [self.exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        values = [int(v) for v in out.stdout.split() if v.strip().isdigit()]
        return max(values) if values else None

    def _loop(self) -> None:
        while not self._stop.is_set():
            value = self._sample()
            if value is not None:
                self.peak_mib = value if self.peak_mib is None else max(self.peak_mib, value)
            self._stop.wait(self.interval_s)

    def __enter__(self) -> VramSampler:
        if self.exe is not None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)


MIB = 1024 * 1024


class OllamaPsSampler:
    """Per-model memory from Ollama's ``/api/ps`` on a thread (R-QV-2).

    Unlike the ``nvidia-smi`` total (which includes the desktop), this is the model's own
    footprint: peak ``size`` and ``size_vram`` while the task ran, and the fraction on the GPU.
    """

    def __init__(
        self, base_url: str, model: str, interval_s: float = 0.5, fetch: FetchJson | None = None
    ) -> None:
        self.base_url, self.model, self.interval_s = base_url, model, interval_s
        self.fetch = fetch
        self.peak_size: int | None = None
        self.peak_vram: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample(self) -> None:
        got = (
            ollama_loaded(self.base_url, self.model, self.fetch)
            if self.fetch is not None
            else ollama_loaded(self.base_url, self.model)
        )
        if got is None:
            return
        size, vram = got
        self.peak_size = size if self.peak_size is None else max(self.peak_size, size)
        self.peak_vram = vram if self.peak_vram is None else max(self.peak_vram, vram)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(self.interval_s)

    def __enter__(self) -> OllamaPsSampler:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    @staticmethod
    def empty() -> dict[str, Any]:
        return {"model_size_mib": None, "model_vram_mib": None, "gpu_fraction": None}

    def fields(self) -> dict[str, Any]:
        size, vram = self.peak_size, self.peak_vram
        return {
            "model_size_mib": round(size / MIB) if size is not None else None,
            "model_vram_mib": round(vram / MIB) if vram is not None else None,
            "gpu_fraction": round(vram / size, 4) if size and vram is not None else None,
        }


@dataclass
class _Collector(AttemptHook):
    attempts: list[AttemptRecord] = field(default_factory=list)

    def on_attempt(self, attempt: AttemptRecord) -> None:
        self.attempts.append(attempt)

    def on_final(self, state: AgentState, final: FinalAnswer) -> None:
        pass


@dataclass
class EvalConfig:
    provider: str
    model: str
    mode: str
    results_dir: Path
    runs_dir: Path
    max_attempts: int = 4
    run_name: str | None = None
    limit: int | None = None
    resume: bool = False
    timeout_s: float = 60.0
    prompt_version: int = 1
    max_output_tokens: int | None = None
    delay_s: float = 0.0
    rate_limit_retries: int = 6
    rate_limit_wait_s: float = 30.0
    sample_vram: bool = False
    ollama_base_url: str | None = None  # set for Ollama runs: per-model VRAM via /api/ps
    prices: dict[str, Any] = field(default_factory=dict)
    task_set: str = "dev"
    temperature: float | None = None
    seed: int | None = None
    seed_supported: bool | None = None
    model_digest: str | None = None
    quantization: str | None = None
    code_commit: str | None = None

    @property
    def name(self) -> str:
        """The run name; a custom ``run_name`` still gets the task-set/seed suffix (v2)."""
        if self.run_name:
            return _file_safe(self.run_name + seed_suffix(self.task_set, self.seed))
        return run_name_for(
            self.provider, self.model, self.mode, self.prompt_version, self.task_set, self.seed
        )

    @property
    def attempts_for_mode(self) -> int:
        return 1 if self.mode == "baseline" else self.max_attempts

    @property
    def results_path(self) -> Path:
        return self.results_dir / f"{self.name}.jsonl"

    @property
    def summary_path(self) -> Path:
        return self.results_dir / f"{self.name}.summary.json"


def is_header(obj: dict[str, Any]) -> bool:
    return obj.get("kind") == HEADER_KIND


def read_header(path: Path) -> dict[str, Any] | None:
    """The header line of a results file, or None (missing/empty file, or a v1 file)."""
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                obj: dict[str, Any] = json.loads(line)
                return obj if is_header(obj) else None
    return None


def results_header(cfg: EvalConfig) -> dict[str, Any]:
    """The header line for ``cfg`` (R-STAT-2)."""
    return {
        "kind": HEADER_KIND,
        "schema": HEADER_SCHEMA,
        "run_name": cfg.name,
        "provider": cfg.provider,
        "model": cfg.model,
        "model_digest": cfg.model_digest,
        "quantization": cfg.quantization,
        "mode": cfg.mode,
        "task_set": cfg.task_set,
        "temperature": cfg.temperature,
        "seed": cfg.seed,
        "seed_supported": cfg.seed_supported,
        "prompt_version": cfg.prompt_version,
        "max_attempts": cfg.attempts_for_mode,
        "max_output_tokens": cfg.max_output_tokens,
        "code_commit": cfg.code_commit,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def check_resume_header(path: Path, header: dict[str, Any]) -> None:
    """Refuse to resume a results file written with different settings (R-STAT-1/2)."""
    existing = read_header(path)
    if existing is None:
        return
    diff = {k: (existing.get(k), header.get(k)) for k in RESUME_KEYS}
    diff = {k: v for k, v in diff.items() if v[0] != v[1]}
    if diff:
        detail = ", ".join(f"{k}: file {a!r} vs now {b!r}" for k, (a, b) in diff.items())
        raise ConfigError(f"cannot resume {path.name}: settings differ ({detail})")


def done_task_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if not is_header(obj):
                ids.add(obj["task_id"])
    return ids


def attempt_checks(
    task: Task, facts: RequestFacts, attempts: list[AttemptRecord], ref: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Checker verdict and verifier verdict for every attempt that produced a result (R-VER-7).

    The verifier is re-run here as a pure function of the recorded result and trace, so the same
    numbers exist for every mode (in verify mode they equal what the agent saw).
    """
    out: list[dict[str, Any]] = []
    for a in attempts:
        run = a["run"] or {}
        result = run.get("result")
        if result is None or a["outcome"] not in ("ok", "verify_failed"):
            continue
        checked = run_checker(task.checker, CheckInput("solved", result, True), ref)
        fails = failures(verify(facts, result, run.get("trace")))
        out.append(
            {
                "attempt": a["number"],
                "checker_passed": checked.passed,
                "verifier_failed": bool(fails),
                "failed_checks": sorted({f.check for f in fails}),
            }
        )
    return out


def evaluate_task(
    task: Task,
    cfg: EvalConfig,
    model: BaseChatModel,
    runner: Runner,
    expected: dict[str, Any],
    *,
    allow_rate_limit: bool = False,
) -> dict[str, Any]:
    """Run the agent on one task and score it."""
    collector = _Collector()
    writer = ArtifactWriter(
        cfg.runs_dir / cfg.name / task.id,
        {"provider": cfg.provider, "model": cfg.model, "mode": cfg.mode, "task_id": task.id},
    )
    deps = AgentDeps(
        model=model,
        runner=runner,
        provider=cfg.provider,
        model_name=cfg.model,
        timeout_s=cfg.timeout_s,
        prompt_version=cfg.prompt_version,
        hooks=[collector, writer],
    )
    sampler = VramSampler() if cfg.sample_vram else None
    ps_sampler = (
        OllamaPsSampler(cfg.ollama_base_url, cfg.model)
        if cfg.sample_vram and cfg.ollama_base_url
        else None
    )
    verify_mode = cfg.mode == "verify"
    start = time.perf_counter()
    error: str | None = None
    final: FinalAnswer | None = None
    try:
        with contextlib.ExitStack() as stack:
            for s in (sampler, ps_sampler):
                if s is not None:
                    stack.enter_context(s)
            final = solve(task.prompt, deps, max_attempts=cfg.attempts_for_mode, verify=verify_mode)
    except RunnerUnavailableError as exc:
        # The sandbox, not the model, failed: stop the run without recording the task, so a
        # resumed run retries it instead of keeping an infrastructure failure as a model one.
        raise RunnerUnavailableError(f"sandbox unavailable on {task.id}: {exc}") from None
    except Exception as exc:  # recorded as a failed task; the run goes on
        error = f"{type(exc).__name__}: {exc}"
    latency = time.perf_counter() - start

    attempts = collector.attempts
    for a in attempts if not allow_rate_limit else []:
        if a["outcome"] == "model_error" and any(
            m in (a["error"] or "") for m in RATE_LIMIT_MARKERS
        ):
            raise RateLimitedError(a["error"] or "rate limited")
    executed = any(a["run"] is not None for a in attempts)
    status = final["status"] if final is not None else "error"
    # An unverified answer is still an answer: the checker judges it (R-VER-5).
    result = (
        {"answer": final["answer"], "data": final["data"]}
        if final is not None and status in ANSWERED
        else None
    )
    ref = expected.get(task.id, {}).get("result")
    if needs_expected(task.checker) and ref is None:
        raise ConfigError(f"no expected result for {task.id}; run scripts/make_expected.py")
    outcome = run_checker(task.checker, CheckInput(status, result, executed), ref)
    facts = extract_facts(task.prompt)
    checks = attempt_checks(task, facts, attempts, ref)
    last_run = (attempts[-1]["run"] or {}) if attempts and result is not None else {}
    final_findings = (
        [f.to_dict() for f in verify(facts, last_run.get("result"), last_run.get("trace"))]
        if result is not None
        else []
    )
    metrics = final["metrics"] if final is not None else {}
    tokens_in = metrics.get("input_tokens")
    tokens_out = metrics.get("output_tokens")
    return {
        "task_id": task.id,
        "category": task.category,
        "provider": cfg.provider,
        "model": cfg.model,
        "mode": cfg.mode,
        "prompt_version": cfg.prompt_version,
        "task_set": cfg.task_set,
        "temperature": cfg.temperature,
        "seed": cfg.seed,
        "code_commit": cfg.code_commit,
        "max_output_tokens": cfg.max_output_tokens,
        "max_attempts": cfg.attempts_for_mode,
        "status": status,
        "passed": outcome.passed,
        "check_reason": outcome.reason,
        "attempts": len(attempts),
        "attempt_outcomes": [a["outcome"] for a in attempts],
        "errors": [a["error"] for a in attempts],
        "harness_error": error,
        "policy_violations": sum(a["outcome"] == "policy_violation" for a in attempts),
        "timeouts": sum(bool(a["run"] and a["run"]["timed_out"]) for a in attempts),
        "answer": final["answer"] if final is not None else None,
        "attempt_checks": checks,
        "final_findings": final_findings,
        "latency_s": round(latency, 3),
        "model_s": round(sum(a["model_s"] for a in attempts), 3),
        "run_s": round(sum(a["run_s"] for a in attempts), 3),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "ttft_s": metrics.get("ttft_s", []),
        "tokens_per_s": metrics.get("tokens_per_s", []),
        "cost_usd": cost_usd(cfg.prices, cfg.provider, cfg.model, tokens_in, tokens_out),
        "peak_vram_mib": sampler.peak_mib if sampler is not None else None,
        **(ps_sampler.fields() if ps_sampler is not None else OllamaPsSampler.empty()),
        "run_dir": writer.dir.as_posix(),
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def run_eval(
    cfg: EvalConfig,
    tasks: list[Task],
    expected: dict[str, Any],
    runner: Runner,
    model_for: Callable[[Task], BaseChatModel],
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate ``tasks`` (first ``cfg.limit``), one appended line per task; returns new records."""
    if isinstance(runner, LocalRunner):
        raise ConfigError("the evaluation never uses the unsafe local runner")
    if cfg.mode not in MODES:
        raise ConfigError(f"mode must be one of {MODES}")
    path = cfg.results_path
    if path.exists() and not cfg.resume:
        raise ConfigError(f"{path} exists; pass --resume to continue it or use another --run-name")
    header = results_header(cfg)
    check_resume_header(path, header)
    done = done_task_ids(path)
    selected = tasks[: cfg.limit] if cfg.limit else tasks
    path.parent.mkdir(parents=True, exist_ok=True)
    new: list[dict[str, Any]] = []
    fresh = not path.is_file() or not path.read_text(encoding="utf-8").strip()
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        if fresh:
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")
            fh.flush()
        for task in selected:
            if task.id in done:
                continue
            record = _evaluate_with_retries(task, cfg, model_for, runner, expected)
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            new.append(record)
            if progress is not None:
                progress(record)
            if cfg.delay_s > 0:
                time.sleep(cfg.delay_s)  # free-tier rate limits; not part of any latency
    return new


def _evaluate_with_retries(
    task: Task,
    cfg: EvalConfig,
    model_for: Callable[[Task], BaseChatModel],
    runner: Runner,
    expected: dict[str, Any],
) -> dict[str, Any]:
    """Retry a rate-limited task after a backoff; give up (and record it) after the limit."""
    for attempt in range(cfg.rate_limit_retries + 1):
        try:
            record = evaluate_task(task, cfg, model_for(task), runner, expected)
        except RateLimitedError as exc:
            if any(m in str(exc) for m in DAILY_LIMIT_MARKERS):
                raise DailyLimitError(f"daily limit reached on {task.id}: {exc}") from None
            if attempt == cfg.rate_limit_retries:
                break
            wait = cfg.rate_limit_wait_s * (2**attempt)
            print(f"rate limited on {task.id}; retrying in {wait:.0f} s ({exc})", flush=True)
            time.sleep(wait)
            continue
        record["rate_limit_retries"] = attempt
        return record
    # Still rate limited: score the task as it is (a failed run), never skip it silently.
    record = evaluate_task(task, cfg, model_for(task), runner, expected, allow_rate_limit=True)
    record["rate_limit_retries"] = cfg.rate_limit_retries
    return record


def fake_model_factory(root: Path) -> Callable[[Task], BaseChatModel]:
    """One scripted model per task, replying with the task's reference."""

    def factory(task: Task) -> BaseChatModel:
        return ScriptedChatModel(replies=[fake_reply(task, root)])

    return factory
