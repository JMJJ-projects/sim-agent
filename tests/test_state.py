"""Tests for the agent state helpers."""

import json

import pytest

from simagent.state import initial_state, new_attempt


def test_initial_state() -> None:
    state = initial_state("req", 4)
    assert state["status"] == "running"
    assert state["attempts"] == []
    assert state["max_attempts"] == 4


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        initial_state("req", 0)


def test_attempt_is_json_serialisable() -> None:
    attempt = new_attempt(1, "generate")
    assert attempt["outcome"] == "pending"
    json.dumps(attempt)
