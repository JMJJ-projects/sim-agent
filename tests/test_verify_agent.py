"""Verify mode end to end with the scripted model and the local runner (R-VER-1, R-VER-4..6).

A script that runs fine but answers the wrong question (5 mm of water instead of 5 cm) is
caught by the verifier, repaired within the same attempt budget, and solved.
"""

from typing import Any

from simagent.graph import route_after_evaluate, route_after_verify, solve
from simagent.llm import ScriptedChatModel
from simagent.nodes import AgentDeps, AttemptHook
from simagent.request_facts import RequestFacts, extract
from simagent.runners import LocalRunner
from simagent.runners.base import Runner, RunResult
from simagent.state import AgentState, AttemptRecord, FinalAnswer, initial_state

REQUEST = "Transmitted fraction of 1 MeV photons through 5 cm of water, 2000 photons, seed 1."

WRONG_UNIT = """\
import photonsim as ps
import simagent_io

res = ps.simulate(ps.Slab([ps.Layer("water", 0.5)]), 1.0, 2000, seed=1)
simagent_io.submit(res.transmitted)
"""

RIGHT = """\
import photonsim as ps
import simagent_io

res = ps.simulate(ps.Slab([ps.Layer("water", 5.0)]), 1.0, 2000, seed=1)
simagent_io.submit(res.transmitted)
"""


def reply(code: str) -> str:
    return f"Plan.\n\n```python\n{code}```\n"


class Recorder(Runner, AttemptHook):
    name = "recording"

    def __init__(self) -> None:
        super().__init__()
        self.inner = LocalRunner(enabled=True)
        self.codes: list[str] = []
        self.seen: list[AttemptRecord] = []

    def run(self, code: str, timeout_s: float = 60.0) -> RunResult:
        self.codes.append(code)
        return self.inner.run(code, timeout_s=timeout_s)

    def on_attempt(self, attempt: AttemptRecord) -> None:
        self.seen.append(attempt)

    def on_final(self, state: AgentState, final: FinalAnswer) -> None:
        pass


def run(
    replies: list[str], *, verify: bool, max_attempts: int = 4
) -> tuple[FinalAnswer, ScriptedChatModel, Recorder]:
    model = ScriptedChatModel(replies=replies)
    rec = Recorder()
    deps = AgentDeps(model=model, runner=rec, provider="fake", model_name="scripted", hooks=[rec])
    return solve(REQUEST, deps, max_attempts=max_attempts, verify=verify), model, rec


def test_wrong_answer_is_caught_and_repaired() -> None:
    """Covers R-VER-1 and R-VER-4: a verify finding triggers a repair with the findings."""
    final, model, rec = run([reply(WRONG_UNIT), reply(RIGHT)], verify=True)
    assert final["status"] == "solved"
    assert final["attempts"] == 2
    assert rec.codes == [WRONG_UNIT, RIGHT]
    first, second = rec.seen
    assert first["outcome"] == "verify_failed"
    assert {f["check"] for f in first["findings"]} >= {"V-LENGTH"}
    assert second["outcome"] == "ok"
    assert second["findings"] == []
    assert final["findings"] == []
    assert "[V-LENGTH]" in (final["errors"][0] or "")
    repair_prompt = model.calls[-1][-1].content
    assert isinstance(repair_prompt, str)
    assert "failed verification" in repair_prompt
    assert WRONG_UNIT.strip() in repair_prompt


def test_repair_mode_does_not_verify() -> None:
    """Covers R-VER-6: without verify mode the same wrong answer is accepted as solved."""
    final, _, rec = run([reply(WRONG_UNIT)], verify=False)
    assert final["status"] == "solved"
    assert final["attempts"] == 1
    assert final["findings"] == []
    assert rec.seen[0]["outcome"] == "ok"


def test_budget_runs_out_with_findings_left() -> None:
    """Covers R-VER-4 and R-VER-5: the shared budget; status solved_unverified with findings."""
    final, _, rec = run([reply(WRONG_UNIT), reply(WRONG_UNIT)], verify=True, max_attempts=2)
    assert final["status"] == "solved_unverified"
    assert final["attempts"] == 2
    assert final["answer"] is not None  # the answer is still returned
    assert any(f["check"] == "V-LENGTH" for f in final["findings"])
    assert [a["outcome"] for a in rec.seen] == ["verify_failed", "verify_failed"]


def test_correct_first_answer_is_verified_once() -> None:
    final, _, rec = run([reply(RIGHT)], verify=True)
    assert final["status"] == "solved"
    assert final["attempts"] == 1
    assert len(rec.seen) == 1  # the hook sees the attempt once, after verification


def test_routing_with_and_without_verify() -> None:
    state = initial_state("req", 4, verify=True)
    state["status"] = "solved"
    assert route_after_evaluate(state) == "verify"
    state["verify"] = False
    assert route_after_evaluate(state) == "finalize"
    for status, route in [("running", "repair"), ("solved", "finalize")]:
        state["status"] = status  # type: ignore[typeddict-item]
        assert route_after_verify(state) == route
    state["status"] = "solved_unverified"
    assert route_after_verify(state) == "finalize"


def test_facts_round_trip() -> None:
    facts = extract("from 1 to 4 cm in 1 cm steps, and 2, 3 and 5 MeV, 100 photons, aluminum")
    assert RequestFacts.from_dict(facts.to_dict()) == facts
    assert RequestFacts.from_dict({}) == RequestFacts()


def test_initial_state_carries_the_mode() -> None:
    state: dict[str, Any] = dict(initial_state("req", 2, verify=True))
    assert state["verify"] is True
    assert state["facts"] == {}
    assert dict(initial_state("req", 2))["verify"] is False
