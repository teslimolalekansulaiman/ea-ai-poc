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
from eawiki.query import executor as ew
from eawiki.query import graphquery as gq
from eawiki.query import guardrails as det
from eawiki.query import route as rt
from eawiki.query.retrieve import Retriever
from eawiki.query.safety import NeMoGuard
from eawiki.subjects import llm_text


def _condense(question: str, history: list, backend: str, model: Optional[str]) -> str:
    """Rewrite a follow-up into a standalone question using the recent turns, so the
    router and vector search (which only see text) can resolve pronouns/references."""
    convo = "\n".join(f"{h.get('role')}: {h.get('content')}" for h in history[-6:])
    prompt = (
        "Given the conversation and a follow-up question, rewrite the follow-up as a "
        "STANDALONE question understandable without the conversation: resolve pronouns and "
        "vague references to the explicit names from the conversation. If it is already "
        "standalone, return it unchanged. Output ONLY the question, nothing else.\n\n"
        f"Conversation:\n{convo}\n\nFollow-up: {question}\n\nStandalone question:"
    )
    out = llm_text(prompt, backend, model).strip()
    return (out.splitlines()[0].strip().strip('"') if out else "") or question


class QAState(TypedDict, total=False):
    # inputs
    question: str
    history: list            # prior turns [{role, content}] for follow-ups
    backend: str
    model: Optional[str]
    kinds: Optional[list]
    k: int
    max_distance: float
    safety: bool
    use_llm: bool
    # working / outputs
    search_question: str     # standalone rewrite used for routing + retrieval
    status: str
    input_guard: dict
    route: dict
    graph_result: dict       # structured graph-query result (facts + render + evidence)
    blocks: list
    _block_objs: list
    subgraph: Optional[dict]
    page: str
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


def n_condense(s: QAState) -> dict:
    hist = s.get("history") or []
    if hist and s.get("use_llm", True):
        try:
            return {"search_question": _condense(
                s["question"], hist, s.get("backend", "cli"), s.get("model"))}
        except Exception:
            pass
    return {"search_question": s["question"]}


def n_route(s: QAState) -> dict:
    return {"route": rt.route(s.get("search_question") or s["question"])}


# Analytic wording that warrants a structured graph query even when the keyword router
# did not pick the "graph" strategy (e.g. "capabilities with no owner" routes vector).
# Covers impact/path language, the relation vocabulary (own/suppl/send/serve/access/…),
# and aggregation words (most/how many/count/rank) so filter + aggregate questions fire.
_GQ_HINTS = (
    "retire", "impact", "affect", "depend", "break", "without", "missing", "orphan",
    "path", "connect", "related", "relationship", "reach", "upstream", "downstream",
    "how does", "no owner", "no owning",
    # relation vocabulary
    "own", "suppl", "send", "data to", "resid", "access", "serve", "realiz",
    "communicat", "trigger", "contribut",
    # aggregation
    "most", "least", "how many", "number of", "count", "rank", "top ", "list all",
)


def n_graphquery(s: QAState) -> dict:
    """The single graph layer for both the answer and the UI. Try a whitelisted template
    (path / impact / orphans / aggregate / filter / neighbors): the LLM only classifies +
    fills typed slots; the traversal is fixed code over graph.json. One result feeds the
    answer (facts), the citations (block_ids) and the UI (nodes) — so view and retrieval
    cannot disagree."""
    q = (s.get("search_question") or s["question"])
    strat = s.get("route", {}).get("strategy")
    r = None
    # LLM slot-fill for analytic questions (skipped in no-llm mode).
    if s.get("use_llm", True) and (strat in ("graph", "browse")
                                   or any(h in q.lower() for h in _GQ_HINTS)):
        try:
            r = gq.answer(q, s.get("backend", "cli"), s.get("model"))
        except Exception:
            r = None
    # Deterministic 1-hop fallback for a plain entity question (no LLM needed) — this is
    # what replaced the old ArcadeDB subgraph + _subgraph_view two-source path.
    if (r is None or (r.get("template") == "neighbors" and not r.get("found"))) and strat in ("graph", "browse"):
        try:
            g = gq._load()
            hits = sorted((nid for nid, n in g.by_id.items()
                           if n.get("name", "").lower() in q.lower()),
                          key=lambda x: len(g.name(x)), reverse=True)
            if hits:
                r = gq.neighbors(g, hits[0])
        except Exception:
            pass
    # Middle tier: no template fit, but the question is structural → let the model WRITE a
    # read-only query, guard it, run it; on any failure this returns None → vector search.
    if r is None and s.get("use_llm", True) and (strat in ("graph", "browse")
                                                  or any(h in q.lower() for h in _GQ_HINTS)):
        try:
            r = gq.generate(q, s.get("backend", "cli"), s.get("model"))
        except Exception:
            r = None
    if r and (r.get("found", True) or r.get("template") in ("path", "impact", "orphans", "filter")):
        return {"graph_result": r}
    return {}


def n_retrieve(s: QAState) -> dict:
    r = _retriever()
    q = s.get("search_question") or s["question"]
    blocks = r.vector_search(q, k=s.get("k", 8), kinds=s.get("kinds"))
    gqr = s.get("graph_result")
    if gqr and gqr.get("block_ids"):
        # Structured graph answer: lead with its cited blocks, keep vector hits as backup.
        ev = r.blocks_by_ids(gqr["block_ids"])
        if ev:
            seen = {b["block_id"] for b in ev}
            blocks = ev + [b for b in blocks if b["block_id"] not in seen]
    block_ids = [b["block_id"] for b in blocks]
    # Context by question type: GLOBAL → the Step-8 community summaries (condensed,
    # thematic — the right source for whole-landscape questions), falling back to the
    # full wiki only on a tiny corpus with no summaries. Otherwise → the PRECISE subject
    # page(s), found from the top vector blocks' subjects (reuses the block index).
    if s["route"]["strategy"] == "global":
        page = ew._community_summaries() or (ew._all_wiki() if ew._wiki_fits() else "")
    else:
        page = ew._pages_from_blocks(block_ids, limit=2)
    return {"_block_objs": blocks, "blocks": block_ids, "subgraph": None, "page": page}


def n_relevance(s: QAState) -> dict:
    gqr = s.get("graph_result")
    if (gqr is None and s.get("subgraph") is None and not s.get("page")
            and not det.relevance_ok(s.get("_block_objs", []), max_distance=s.get("max_distance", 0.95))):
        return {"status": "abstained", "answer": det.ABSTAIN}
    context = ans.assemble_context(s.get("_block_objs", []), s.get("subgraph"))
    if s.get("page"):
        context = ("WIKI (synthesized, connected context — cite the block ids it references, "
                   "not the page):\n" + s["page"] + "\n\n" + context)
    if gqr:
        # The structured result is the authoritative answer to a graph question; put it first.
        context = (f"GRAPH QUERY RESULT ({gqr.get('template')}, authoritative — this is the "
                   f"structural answer; use the source blocks below for wording and citations):\n"
                   + gqr.get("facts", "") + "\n\n" + context)
    return {"context": context}


def n_answer(s: QAState) -> dict:
    if not s.get("use_llm", True):
        return {"status": "retrieved"}
    text = ans.answer(s["question"], s["context"], s.get("backend", "cli"),
                      s.get("model"), history=s.get("history"))
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
    g.add_node("condense", n_condense)
    g.add_node("route", n_route)
    g.add_node("graphquery", n_graphquery)
    g.add_node("retrieve", n_retrieve)
    g.add_node("relevance", n_relevance)
    g.add_node("answer", n_answer)
    g.add_node("output_guard", n_output_guard)

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", _after_input, {"refused": END, "ok": "condense"})
    g.add_edge("condense", "route")
    g.add_edge("route", "graphquery")
    g.add_edge("graphquery", "retrieve")
    g.add_edge("retrieve", "relevance")
    g.add_conditional_edges("relevance", _after_relevance, {"abstained": END, "ok": "answer"})
    g.add_edge("answer", "output_guard")
    g.add_edge("output_guard", END)
    return g.compile()


def run(question: str, backend: str = "cli", model=None, k: int = 8,
        kinds=None, use_llm: bool = True, safety: bool = True,
        max_distance: float = 0.95, history=None) -> dict:
    state: QAState = {"question": question, "history": history or [],
                      "backend": backend, "model": model,
                      "k": k, "kinds": kinds, "use_llm": use_llm, "safety": safety,
                      "max_distance": max_distance}
    out = dict(build_app().invoke(state))
    out.pop("_block_objs", None)
    out.setdefault("status", "answered")
    return out
