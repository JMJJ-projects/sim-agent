"""LangGraph wiring of the self-correcting agent (R-AG-1, R-AG-5).

    generate -> check_policy -> execute -> evaluate_run -> repair -> check_policy -> ...
                           \\-> evaluate_run (no runnable code)   \\-> finalize -> END

Routing is done by two pure functions so every outcome is unit-testable. Baseline mode is the
same graph with ``max_attempts=1``.
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


def route_after_evaluate(state: AgentState) -> Literal["repair", "finalize"]:
    """Repair while the run is still open (failed attempt, attempts left)."""
    return "repair" if state.get("status") == "running" else "finalize"


def build_graph(deps: AgentDeps) -> Any:
    """Compile the agent graph with ``deps`` bound into the nodes."""
    nodes = make_nodes(deps)
    g: StateGraph[AgentState] = StateGraph(AgentState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "generate")
    g.add_edge("generate", "check_policy")
    g.add_conditional_edges(
        "check_policy",
        route_after_policy,
        {"execute": "execute", "evaluate_run": "evaluate_run"},
    )
    g.add_edge("execute", "evaluate_run")
    g.add_conditional_edges(
        "evaluate_run", route_after_evaluate, {"repair": "repair", "finalize": "finalize"}
    )
    g.add_edge("repair", "check_policy")
    g.add_edge("finalize", END)
    return g.compile(name="simagent")


def solve(request: str, deps: AgentDeps, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> FinalAnswer:
    """Run the agent on ``request`` and return the final answer."""
    state = initial_state(request, max_attempts)
    graph = build_graph(deps)
    out = graph.invoke(state, config={"recursion_limit": 6 * max_attempts + 10})
    final: FinalAnswer = out["final"]
    return final
