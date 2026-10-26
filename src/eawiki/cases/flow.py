"""The two flows of the cases engine, as LangGraph graphs.

They are the code that runs, not a drawing of it: `Engine.run_phase` invokes the phase graph and each
cell is decided by the cell graph. `draw()` asks LangGraph for the diagram, so the picture cannot drift
from what the engine does.

    python -m eawiki.cases.flow          # prints both diagrams as Mermaid

The human step is not a pause inside either graph. A cell that cannot be decided takes the
`open_question` exit: the cell and a question are saved and the graph ends, so every other cell keeps
running. The answer arrives later as a separate call (a typed value, a suggestion, or `look_found` /
`look_missed` when the architect points to a document), which is why a restart loses nothing.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph


class PhaseState(TypedDict, total=False):
    cid: str
    pid: str
    only_item: Optional[str]
    only_cols: Optional[set]
    resume: bool         # keep what is already decided
    run: dict            # the objects of this run: case, tools, plans, rows, the pool
    li: int              # the next round of properties to run


class CellState(TypedDict, total=False):
    cid: str
    pid: str
    spec: dict
    item: dict
    others: list
    col: dict
    plan: dict
    tools: Any
    link_cache: dict
    profile: Optional[dict]   # what the demand mentions, by group
    hint: Optional[dict]      # set when the architect pointed to a document
    question: Optional[dict]  # the open question that hint answers
    ev: dict
    cell: dict
    failed: bool


def build_phase_graph(e):
    g = StateGraph(PhaseState)
    g.add_node("prepare", e._n_prepare)
    g.add_node("gate", e._n_gate)
    g.add_node("profile", e._n_profile)
    g.add_node("run_round", e._n_round)
    g.add_node("summaries", e._n_summaries)
    g.add_node("citations", e._n_citations)
    g.add_node("consistency", e._n_consistency)
    g.add_node("finish", e._n_finish)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "gate")

    def more(s: PhaseState) -> str:
        return "run_round" if s["li"] < len(s["run"]["rounds"]) else "summaries"

    g.add_edge("gate", "profile")
    g.add_conditional_edges("profile", more, {"run_round": "run_round", "summaries": "summaries"})
    g.add_conditional_edges("run_round", more, {"run_round": "run_round", "summaries": "summaries"})
    g.add_edge("summaries", "citations")
    g.add_edge("citations", "consistency")
    g.add_edge("consistency", "finish")
    g.add_edge("finish", END)
    return g.compile()


def build_cell_graph(e):
    g = StateGraph(CellState)
    g.add_node("gather", e._c_gather)
    g.add_node("solve", e._c_solve)
    g.add_node("save_answer", e._c_save_answer)
    g.add_node("open_question", e._c_open_question)
    g.add_node("look_found", e._c_look_found)
    g.add_node("look_missed", e._c_look_missed)
    g.add_edge(START, "gather")
    g.add_edge("gather", "solve")

    def route(s: CellState) -> str:
        status = s["cell"]["status"]
        if s.get("hint"):
            return "look_found" if status == "answered" else "look_missed"
        return "open_question" if status == "needs_input" else "save_answer"

    g.add_conditional_edges("solve", route, {k: k for k in ("save_answer", "open_question", "look_found", "look_missed")})
    for n in ("save_answer", "open_question", "look_found", "look_missed"):
        g.add_edge(n, END)
    return g.compile()


def draw(e) -> dict:
    return {"phase": build_phase_graph(e).get_graph().draw_mermaid(),
            "cell": build_cell_graph(e).get_graph().draw_mermaid()}


if __name__ == "__main__":
    from eawiki.cases.engine import Engine
    from eawiki.cases.store import CaseStore

    out = draw(Engine(CaseStore(), lambda: None))
    print("%% PHASE\n" + out["phase"] + "\n%% CELL\n" + out["cell"])
