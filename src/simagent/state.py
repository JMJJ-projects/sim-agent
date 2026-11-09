"""Agent state definition.

The state is plain JSON-friendly data (TypedDicts), so it can be written to ``trace.json`` as is.
Dependencies (model, runner, limits) are *not* part of the state: they are bound when the graph
is built, so nothing in the state, and nothing the model writes, can choose them (R-AG-8).
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# "solved_unverified": an answer was returned, but verification findings remained when the
# attempt budget ran out (R-VER-5).
Status = Literal["running", "solved", "solved_unverified", "failed", "refused"]
Outcome = Literal[
    "pending",
    "ok",
    "format_error",
    "policy_violation",
    "run_failed",
    "refused",
    "model_error",
    "verify_failed",
]
AttemptKind = Literal["generate", "repair"]


class AttemptRecord(TypedDict):
    """One model call and what happened to its script."""

    number: int
    kind: AttemptKind
    reply: str
    explanation: str
    code: str | None
    outcome: Outcome
    error: str | None
    refusal: str | None
    policy_violations: list[str]
    run: dict[str, Any] | None
    metrics: dict[str, Any] | None
    model_s: float
    run_s: float
    findings: list[dict[str, str]]


class FinalAnswer(TypedDict):
    """What the agent returns (R-AG-6)."""

    status: Status
    request: str
    answer: Any
    data: dict[str, Any]
    explanation: str
    final_script: str | None
    attempts: int
    errors: list[str | None]
    refusal: str | None
    files: dict[str, str]
    metrics: dict[str, Any]
    findings: list[dict[str, str]]


class AgentState(TypedDict, total=False):
    """LangGraph state for one request."""

    request: str
    max_attempts: int
    verify: bool
    facts: dict[str, Any]
    attempts: list[AttemptRecord]
    current: AttemptRecord | None
    status: Status
    final: FinalAnswer


def new_attempt(number: int, kind: AttemptKind) -> AttemptRecord:
    return AttemptRecord(
        number=number,
        kind=kind,
        reply="",
        explanation="",
        code=None,
        outcome="pending",
        error=None,
        refusal=None,
        policy_violations=[],
        run=None,
        metrics=None,
        model_s=0.0,
        run_s=0.0,
        findings=[],
    )


def initial_state(request: str, max_attempts: int, verify: bool = False) -> AgentState:
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    return AgentState(
        request=request,
        max_attempts=max_attempts,
        verify=verify,
        facts={},
        attempts=[],
        current=None,
        status="running",
    )
