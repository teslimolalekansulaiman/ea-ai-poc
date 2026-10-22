"""LangGraph orchestration of the guarded AI layer.

A StateGraph whose nodes are the capability functions built earlier:

  input_guard ──(refused)──────────────► END
       │
   (ok)▼
     route ─► retrieve ─► relevance ──(abstained)──► END
                               │
                          (ok) ▼
                            answer ─► output_guard ─► END

Guards short-circuit via conditional edges. Model calls go through BackendLLM
(claude -p local / Pulse via env). NeMo Guardrails runs in the input/output guard nodes.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from eawiki.query import answer as ans
from eawiki.query import guardrails as det
from eawiki.query import route as rt
from eawiki.query.retrieve import Retriever
from eawiki.query.safety import NeMoGuard


class QAState(TypedDict, total=False):
    # inputs
    question: str
    backend: str
    model: Optional[str]
    kinds: Optional[list]
    k: int
    max_distance: float
    safety: bool
    use_llm: bool
    # working / outputs
    status: str
    input_guard: dict
    route: dict
    blocks: list
    _block_objs: list
    subgraph: Optional[dict]
    context: str
    answer: str
    citation_check: dict
    output_guard: dict


@lru_cache(maxsize=4)
def _retriever() -> Retriever:
    return Retriever()


@lru_cache(maxsize=4)
def _guard(backend: str, model: Optional[str]) -> NeMoGuard:
    return NeMoGuard(backend=backend, model=model)


# --- nodes ---------------------------------------------------------------
def n_input_guard(s: QAState) -> dict:
    q = s["question"]
    if s.get("safety", True) and s.get("use_llm", True):
        res = _guard(s.get("backend", "cli"), s.get("model")).check_input(q)
    else:
        res = det.check_input_deterministic(q)
        res["layer"] = "deterministic"
    if not res["allowed"]:
        return {"input_guard": res, "status": "refused", "answer": det.REFUSAL}
    return {"input_guard": res}


def n_route(s: QAState) -> dict:
    return {"route": rt.route(s["question"])}


def n_retrieve(s: QAState) -> dict:
    r = _retriever()
    q = s["question"]
    blocks = r.vector_search(q, k=s.get("k", 8), kinds=s.get("kinds"))
    subgraph = None
    if s["route"]["strategy"] in ("graph", "browse"):
        ents = r.entities_in_question(q)
        if ents:
            subgraph = r.subgraph(ents[0]["node_id"])
            ev = r.blocks_by_ids(subgraph.get("blocks", []))
            if ev:
                blocks = ev
    return {"_block_objs": blocks, "blocks": [b["block_id"] for b in blocks],
            "subgraph": subgraph}


def n_relevance(s: QAState) -> dict:
    if s.get("subgraph") is None and not det.relevance_ok(
            s.get("_block_objs", []), max_distance=s.get("max_distance", 0.95)):
        return {"status": "abstained", "answer": det.ABSTAIN}
    context = ans.assemble_context(s.get("_block_objs", []), s.get("subgraph"))
    return {"context": context}


def n_answer(s: QAState) -> dict:
    if not s.get("use_llm", True):
        return {"status": "retrieved"}
    text = ans.answer(s["question"], s["context"], s.get("backend", "cli"), s.get("model"))
    return {"answer": text}


def n_output_guard(s: QAState) -> dict:
    if s.get("status") == "retrieved":      # no answer generated
        return {}
    allowed_ids = {b["block_id"] for b in s.get("_block_objs", [])}
    cite = det.verify_citations(s.get("answer", ""), allowed_ids)
    out = {"citation_check": cite, "status": "answered"}
    if s.get("safety", True) and s.get("use_llm", True):
        og = _guard(s.get("backend", "cli"), s.get("model")).check_output(s.get("answer", ""))
        out["output_guard"] = og
        if not og["allowed"]:
            out["status"] = "blocked_output"
            out["answer"] = det.REFUSAL
    return out


# --- wiring --------------------------------------------------------------
def _after_input(s: QAState) -> str:
    return "refused" if s.get("status") == "refused" else "ok"


def _after_relevance(s: QAState) -> str:
    return "abstained" if s.get("status") == "abstained" else "ok"


@lru_cache(maxsize=1)
def build_app():
    g = StateGraph(QAState)
    g.add_node("input_guard", n_input_guard)
    g.add_node("route", n_route)
    g.add_node("retrieve", n_retrieve)
    g.add_node("relevance", n_relevance)
    g.add_node("answer", n_answer)
    g.add_node("output_guard", n_output_guard)

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", _after_input, {"refused": END, "ok": "route"})
    g.add_edge("route", "retrieve")
    g.add_edge("retrieve", "relevance")
    g.add_conditional_edges("relevance", _after_relevance, {"abstained": END, "ok": "answer"})
    g.add_edge("answer", "output_guard")
    g.add_edge("output_guard", END)
    return g.compile()


def run(question: str, backend: str = "cli", model=None, k: int = 8,
        kinds=None, use_llm: bool = True, safety: bool = True,
        max_distance: float = 0.95) -> dict:
    state: QAState = {"question": question, "backend": backend, "model": model,
                      "k": k, "kinds": kinds, "use_llm": use_llm, "safety": safety,
                      "max_distance": max_distance}
    out = dict(build_app().invoke(state))
    out.pop("_block_objs", None)
    out.setdefault("status", "answered")
    return out
