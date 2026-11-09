"""LangGraph wiring of the self-correcting agent (R-AG-1, R-AG-5, R-VER-4..6).

    facts -> generate -> check_policy -> execute -> evaluate_run -> repair -> check_policy ...
    check_policy -> evaluate_run              (no runnable code)
    evaluate_run -> verify -> repair | finalize   (verify mode, successful run)
    evaluate_run -> finalize -> END

Routing is done by pure functions so every outcome is unit-testable. Modes (R-VER-6): baseline
is the graph with ``max_attempts=1``, repair the full loop, and verify the full loop with the
``verify`` node on (``state["verify"]``). Verification-triggered repairs share the same attempt
budget as every other repair (R-VER-4).
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from simagent.nodes import AgentDeps, make_nodes
from simagent.state import AgentState, FinalAnswer, initial_state

DEFAULT_MAX_ATTEMPTS = 4


def route_after_policy(state: AgentState) -> Literal["execute", "evaluate_run"]:
    """Run the code only if the attempt produced code that passed the policy."""
    attempt = state.get("current")
    if attempt is not None and attempt["outcome"] == "pending" and attempt["code"] is not None:
        return "execute"
    return "evaluate_run"


def route_after_evaluate(state: AgentState) -> Literal["repair", "verify", "finalize"]:
    """Repair while the run is open; verify a successful run in verify mode; else finish."""
    status = state.get("status")
    if status == "running":
        return "repair"
    if status == "solved" and state.get("verify"):
        return "verify"
    return "finalize"


def route_after_verify(state: AgentState) -> Literal["repair", "finalize"]:
    """Repair on failed checks while attempts remain (R-VER-4); else finish."""
    return "repair" if state.get("status") == "running" else "finalize"


def build_graph(deps: AgentDeps) -> Any:
    """Compile the agent graph with ``deps`` bound into the nodes."""
    nodes = make_nodes(deps)
    g: StateGraph[AgentState] = StateGraph(AgentState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "facts")
    g.add_edge("facts", "generate")
    g.add_edge("generate", "check_policy")
    g.add_conditional_edges(
        "check_policy",
        route_after_policy,
        {"execute": "execute", "evaluate_run": "evaluate_run"},
    )
    g.add_edge("execute", "evaluate_run")
    g.add_conditional_edges(
        "evaluate_run",
        route_after_evaluate,
        {"repair": "repair", "verify": "verify", "finalize": "finalize"},
    )
    g.add_conditional_edges(
        "verify", route_after_verify, {"repair": "repair", "finalize": "finalize"}
    )
    g.add_edge("repair", "check_policy")
    g.add_edge("finalize", END)
    return g.compile(name="simagent")


def solve(
    request: str,
    deps: AgentDeps,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    *,
    verify: bool = False,
) -> FinalAnswer:
    """Run the agent on ``request`` and return the final answer (``verify``: R-VER-6)."""
    state = initial_state(request, max_attempts, verify=verify)
    graph = build_graph(deps)
    out = graph.invoke(state, config={"recursion_limit": 8 * max_attempts + 12})
    final: FinalAnswer = out["final"]
    return final


def mermaid() -> str:
    """Mermaid source of the agent graph (``docs/graph.mmd``)."""
    from simagent.llm import ScriptedChatModel
    from simagent.runners.base import Runner, RunResult

    class _NoRun(Runner):
        """Placeholder: the diagram only needs the graph structure, nothing is executed."""

        def run(self, code: str, timeout_s: float = 60.0) -> RunResult:
            raise RuntimeError("diagram-only runner")

    deps = AgentDeps(
        model=ScriptedChatModel(replies=[]), runner=_NoRun(), provider="fake", model_name="-"
    )
    text: str = build_graph(deps).get_graph().draw_mermaid()
    return text.rstrip() + "\n"
