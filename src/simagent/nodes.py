"""Agent graph nodes (R-AG-1 to R-AG-6, R-AG-8, R-AG-9).

Each node is a function ``(state) -> partial state update``, built by ``make_nodes`` with the
dependencies bound in a closure. The model's output only ever becomes *code* that goes through
the static policy and then the configured ``Runner``; it never selects the runner, the timeout
or the limits (R-AG-8).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from simagent import prompts
from simagent.codeblock import extract
from simagent.metrics import stream_with_metrics
from simagent.policy import check
from simagent.runners.base import Runner, RunResult
from simagent.state import AgentState, AttemptKind, AttemptRecord, FinalAnswer, new_attempt

STDERR_TAIL_LINES = 40
STDOUT_TAIL_LINES = 10


class NodeFn(Protocol):
    """A graph node: takes the state, returns a partial update."""

    def __call__(self, state: AgentState) -> dict[str, Any]: ...


class AttemptHook:
    """Receives each finished attempt and the final answer (e.g. to write artifacts)."""

    def on_attempt(self, attempt: AttemptRecord) -> None:  # pragma: no cover - interface
        """Called once per finished attempt."""

    def on_final(self, state: AgentState, final: FinalAnswer) -> None:  # pragma: no cover
        """Called once with the final answer."""


@dataclass
class AgentDeps:
    """Everything the nodes need. Chosen by configuration, never by the model (R-AG-8)."""

    model: BaseChatModel
    runner: Runner
    provider: str
    model_name: str
    timeout_s: float = 60.0
    hooks: list[AttemptHook] = field(default_factory=list)
    clock: Callable[[], float] = time.perf_counter


def _tail(text: str, n: int) -> str:
    lines = text.rstrip("\n").splitlines()
    if len(lines) <= n:
        return "\n".join(lines)
    return "\n".join([f"[... {len(lines) - n} earlier lines omitted ...]", *lines[-n:]])


def compact_error(run: RunResult, timeout_s: float) -> str:
    """Short error report for the repair prompt (R-AG-4)."""
    if run.timed_out:
        report = f"The script timed out: it was stopped after the {timeout_s:g} s time limit."
        if run.stderr.strip():
            report += f"\nstderr (last lines):\n{_tail(run.stderr, 10)}"
        return report
    if run.exit_code != 0:
        stderr = _tail(run.stderr, STDERR_TAIL_LINES) or "(no stderr)"
        return f"The script exited with code {run.exit_code}.\nstderr (last lines):\n{stderr}"
    if run.result_error:
        return f"The script ran but its result was unusable: {run.result_error}."
    if run.result_json is None:
        report = (
            "The script exited with code 0 but no result was submitted: call "
            "simagent_io.submit(answer, **data) exactly once at the end."
        )
        if run.stdout.strip():
            report += f"\nstdout (last lines):\n{_tail(run.stdout, STDOUT_TAIL_LINES)}"
        return report
    return "no error"  # pragma: no cover - only called for failed runs


def _run_dict(run: RunResult) -> dict[str, Any]:
    return {
        "runner": run.runner,
        "exit_code": run.exit_code,
        "timed_out": run.timed_out,
        "duration_s": run.duration_s,
        "stdout": run.stdout,
        "stderr": run.stderr,
        "result": run.result_json,
        "result_error": run.result_error,
        "files": run.files,
        "warnings": run.warnings,
    }


def _sum_or_none(values: list[Any]) -> Any:
    known = [v for v in values if v is not None]
    if not known or len(known) != len(values):
        return None
    return sum(known)


def summarise_metrics(attempts: list[AttemptRecord]) -> dict[str, Any]:
    """Totals over attempts. Token totals are null unless every call reported them."""
    calls = [a["metrics"] for a in attempts if a["metrics"] is not None]
    return {
        "model_calls": len(calls),
        "input_tokens": _sum_or_none([c["input_tokens"] for c in calls]),
        "output_tokens": _sum_or_none([c["output_tokens"] for c in calls]),
        "model_s": sum(a["model_s"] for a in attempts),
        "run_s": sum(a["run_s"] for a in attempts),
        "ttft_s": [c["ttft_s"] for c in calls],
        "tokens_per_s": [c["tokens_per_s"] for c in calls],
    }


def make_nodes(deps: AgentDeps) -> dict[str, NodeFn]:
    """Build the node functions with ``deps`` bound."""

    def _call_model(
        state: AgentState, kind: AttemptKind, messages: list[BaseMessage]
    ) -> dict[str, Any]:
        attempt = new_attempt(len(state["attempts"]) + 1, kind)
        start = deps.clock()
        try:
            text, metrics = stream_with_metrics(
                deps.model, messages, provider=deps.provider, model_name=deps.model_name
            )
        except Exception as exc:  # provider/network errors end the run, they are not repairable
            attempt["outcome"] = "model_error"
            attempt["error"] = f"model call failed: {type(exc).__name__}: {exc}"
            attempt["model_s"] = deps.clock() - start
            return {"current": attempt}
        attempt["model_s"] = deps.clock() - start
        attempt["reply"] = text
        attempt["metrics"] = metrics.to_dict()
        ex = extract(text)
        attempt["explanation"] = ex.explanation
        if ex.refusal is not None:
            attempt["outcome"] = "refused"
            attempt["refusal"] = ex.refusal
        elif ex.error is not None:
            attempt["outcome"] = "format_error"
            attempt["error"] = ex.error
        else:
            attempt["code"] = ex.code
        return {"current": attempt}

    def generate(state: AgentState) -> dict[str, Any]:
        return _call_model(state, "generate", prompts.generate_messages(state["request"]))

    def repair(state: AgentState) -> dict[str, Any]:
        last = state["attempts"][-1]
        error = last["error"] or "unknown error"
        if last["code"] is None:
            messages = prompts.repair_format_messages(state["request"], last["reply"], error)
        else:
            messages = prompts.repair_messages(state["request"], last["code"], error)
        return _call_model(state, "repair", messages)

    def check_policy(state: AgentState) -> dict[str, Any]:
        attempt = state["current"]
        assert attempt is not None
        if attempt["outcome"] != "pending" or attempt["code"] is None:
            return {}
        verdict = check(attempt["code"])
        if verdict.ok:
            return {}
        updated = AttemptRecord(**attempt)
        updated["outcome"] = "policy_violation"
        updated["policy_violations"] = [str(v) for v in verdict.violations]
        updated["error"] = verdict.feedback()
        return {"current": updated}

    def execute(state: AgentState) -> dict[str, Any]:
        attempt = state["current"]
        assert attempt is not None
        assert attempt["code"] is not None
        run = deps.runner.run(attempt["code"], timeout_s=deps.timeout_s)
        updated = AttemptRecord(**attempt)
        updated["run"] = _run_dict(run)
        updated["run_s"] = run.duration_s
        if run.ok:
            updated["outcome"] = "ok"
        else:
            updated["outcome"] = "run_failed"
            updated["error"] = compact_error(run, deps.timeout_s)
        return {"current": updated}

    def evaluate_run(state: AgentState) -> dict[str, Any]:
        attempt = state["current"]
        assert attempt is not None
        attempts = [*state["attempts"], attempt]
        for hook in deps.hooks:
            hook.on_attempt(attempt)
        outcome = attempt["outcome"]
        if outcome == "ok":
            status = "solved"
        elif outcome == "refused":
            status = "refused"
        elif outcome == "model_error" or len(attempts) >= state["max_attempts"]:
            status = "failed"
        else:
            status = "running"
        return {"attempts": attempts, "current": None, "status": status}

    def finalize(state: AgentState) -> dict[str, Any]:
        attempts = state["attempts"]
        last = attempts[-1]
        status = state["status"] if state["status"] != "running" else "failed"
        result = (last["run"] or {}).get("result") if status == "solved" else None
        with_code = [a for a in attempts if a["code"] is not None]
        explanation = last["explanation"] or (with_code[-1]["explanation"] if with_code else "")
        if status == "refused":
            explanation = f"Refused: {last['refusal']}"
        final = FinalAnswer(
            status=status,
            request=state["request"],
            answer=result.get("answer") if result else None,
            data=(result.get("data") or {}) if result else {},
            explanation=explanation,
            final_script=with_code[-1]["code"] if with_code else None,
            attempts=len(attempts),
            errors=[a["error"] for a in attempts],
            refusal=last["refusal"],
            files=((last["run"] or {}).get("files") or {}) if status == "solved" else {},
            metrics=summarise_metrics(attempts),
        )
        for hook in deps.hooks:
            hook.on_final(state, final)
        return {"final": final, "status": status}

    return {
        "generate": generate,
        "check_policy": check_policy,
        "execute": execute,
        "evaluate_run": evaluate_run,
        "repair": repair,
        "finalize": finalize,
    }
