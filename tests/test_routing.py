"""Routing covers every outcome (R-AG-1, R-AG-5)."""

import pytest

from simagent.graph import route_after_evaluate, route_after_policy
from simagent.state import AgentState, Outcome, Status, initial_state, new_attempt


def _with_current(outcome: Outcome, code: str | None) -> AgentState:
    state = initial_state("req", 4)
    attempt = new_attempt(1, "generate")
    attempt["outcome"] = outcome
    attempt["code"] = code
    state["current"] = attempt
    return state


def test_pending_code_is_executed() -> None:
    assert route_after_policy(_with_current("pending", "x = 1\n")) == "execute"


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        ("policy_violation", "import os\n"),
        ("format_error", None),
        ("refused", None),
        ("model_error", None),
        ("pending", None),
    ],
)
def test_non_runnable_attempts_skip_execution(outcome: Outcome, code: str | None) -> None:
    """Covers R-AG-9: refusals and policy violations never reach execution."""
    assert route_after_policy(_with_current(outcome, code)) == "evaluate_run"


def test_missing_current_skips_execution() -> None:
    assert route_after_policy(initial_state("req", 1)) == "evaluate_run"


@pytest.mark.parametrize(
    ("status", "route"),
    [
        ("running", "repair"),
        ("solved", "finalize"),
        ("failed", "finalize"),
        ("refused", "finalize"),
    ],
)
def test_route_after_evaluate(status: Status, route: str) -> None:
    state = initial_state("req", 4)
    state["status"] = status
    assert route_after_evaluate(state) == route
