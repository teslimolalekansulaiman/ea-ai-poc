"""A follow-up question on a case: asked inside everything the case knows (the request, every stage, what was written once for the whole
request, the drafts as they stand, what is still open), with the last five exchanges of the conversation, and with the question made
standalone against the case so that the documents are searched for the right thing."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import test_shipped_recommendation as shipped  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.cases import casecontext as cc  # noqa: E402
from eawiki.query import answer as ans  # noqa: E402


@pytest.fixture(autouse=True)
def _use_cases(monkeypatch):
    monkeypatch.setattr(usecases, "DIR", base.ROOT / "use_cases")


def _case():
    e, cid, _order, _seen = shipped._run()
    return e, cid


def _context(e, cid, focus=None, monkeypatch=None):
    import importlib
    api = importlib.import_module("eawiki.api.cases")
    if monkeypatch:
        monkeypatch.setattr(api, "store", lambda: e.store)
    return api.case_context(cid, e.store.get_case(cid), focus)


# ---- what the follow-up is asked inside -----------------------------------------------------------------------------------

def test_the_context_holds_the_request_every_stage_what_was_written_for_the_whole_request_and_the_drafts(monkeypatch):
    e, cid = _case()
    ctx = _context(e, cid, monkeypatch=monkeypatch)
    head = ctx.split("\n## ", 1)[0]
    assert head.startswith("# THE REQUEST") and "D-2026-001" in head and "Demand ID: D-2026-001" in head           # each demand, with its fields' own labels
    stages = [ln for ln in ctx.splitlines() if ln.startswith("## STAGE: ")]
    assert stages == ["## STAGE: Screening & Impact Assessment", "## STAGE: Recommendation"]                       # both phases, none dropped
    assert "(the first check)" in ctx                                                                              # the verdict that let it through
    assert "Written once for the whole request" in ctx and f"- Request overview: {shipped.OVERVIEW}" in ctx
    assert "# THE DRAFTS, as they stand" in ctx and "## DRAFT (Recommendation):" in ctx and "[draft]" in ctx
    assert "Section for D-2026-001." in ctx                                                                         # a demand's own section, from the draft
    assert ctx.index("# THE REQUEST") < ctx.index("## STAGE: Screening") < ctx.index("## STAGE: Recommendation") < ctx.index("# THE DRAFTS")


def test_what_the_architect_changed_in_a_draft_and_where_it_is_in_review_is_what_the_follow_up_reads(monkeypatch):
    from eawiki.cases import document
    e, cid = _case()
    case = e.store.get_case(cid)
    [entry] = document.listing(e.store, case, shipped.PID)
    doc = copy.deepcopy(entry["doc"])
    doc["rec"]["body"] = "The architect's own words about this request."
    document.edit(e.store, case, shipped.PID, entry["item_id"], doc)
    ctx = _context(e, cid, monkeypatch=monkeypatch)
    assert "The architect's own words about this request." in ctx and "edited by the architect" in ctx
    document.decide(e.store, case, shipped.PID, entry["item_id"], "return", "Say who agrees the schedule.")
    ctx = _context(e, cid, monkeypatch=monkeypatch)
    assert "Returned with this note: Say who agrees the schedule." in ctx and "[returned" in ctx


def test_the_demand_the_architect_has_open_is_named_and_a_stranger_is_not(monkeypatch):
    e, cid = _case()
    assert _context(e, cid, "D-2026-003", monkeypatch).startswith("The architect has D-2026-003 open")
    assert not _context(e, cid, "D-9999-999", monkeypatch).startswith("The architect has")


def _synthetic(items=3, per=40, size=700):
    stages = [{"name": f"Stage {s}", "output": {"columns": [{"name": f"P{s}-{c}", "type": "text"} for c in range(per)]}} for s in (1, 2, 3)]
    spec = {"input": {"title_field": "title", "item_fields": [{"name": "title", "label": "Title"}, {"name": "need", "label": "Need"}]},
            "stages": stages}
    case = {"id": "c", "name": "Big", "spec": spec, "items": [{"_id": f"D-{i}", "title": f"Demand {i}", "need": "n" * size} for i in range(items)]}
    cells = [{"phase_id": cc.phase_id(st), "item_id": it["_id"], "column": c["name"], "value": "v" * size, "status": "answered", "need": ""}
             for st in stages for it in case["items"] for c in st["output"]["columns"]]
    return case, cells


def test_a_long_case_is_shortened_all_over_and_no_stage_is_dropped():
    case, cells = _synthetic()
    full = sum(len(c["value"]) for c in cells)
    assert full > cc.LIMIT * 3                                                                                       # far too long as it is
    text = cc.build(case, cells)
    assert len(text) <= cc.LIMIT + 200 and "more lines cut" in text                                                  # each part says how much it lost
    assert [ln for ln in text.splitlines() if ln.startswith("## STAGE: ")] == ["## STAGE: Stage 1", "## STAGE: Stage 2", "## STAGE: Stage 3"]    # the last phase is there
    assert "…" in text and "P3-39" in text                                                                           # shortened, but the last property of the last stage is in
    short, small = _synthetic(items=1, per=3, size=60)
    assert "…" not in cc.build(short, small) and "[the rest was cut" not in cc.build(short, small)                   # a small case is whole


def test_the_digest_is_the_request_alone():
    case, cells = _synthetic(items=2, per=2, size=30)
    ctx = cc.build(case, cells)
    d = cc.digest(ctx)
    assert "THE REQUEST" in d and "D-0" in d and "STAGE" not in d
    assert len(cc.digest("x" * 5000)) <= 1801


# ---- the conversation: the last five exchanges ---------------------------------------------------------------------------------

def _talk(n):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(n)]


def test_the_last_five_exchanges_are_read_and_a_long_turn_is_cut():
    got = ans.recent(_talk(30))
    assert [h["content"] for h in got] == [f"turn {i}" for i in range(20, 30)]                                       # five question-and-answer pairs
    assert ans.recent(_talk(3)) == _talk(3) and ans.recent(None) == [] and ans.recent([{"role": "user", "content": "  "}]) == []
    assert len(ans.recent([{"role": "assistant", "content": "x" * 5000}])[0]["content"]) == ans.HISTORY_CHARS
    prompt = ans.build_prompt("q?", "ctx", _talk(30))
    assert "turn 29" in prompt and "turn 20" in prompt and "turn 19" not in prompt


def test_the_route_asks_the_pipeline_with_the_case_and_the_last_five_exchanges(monkeypatch):
    from eawiki.api import cases as api
    e, cid = _case()
    api.set_engine(e)
    monkeypatch.setattr(api, "store", lambda: e.store)
    seen = {}

    def fake_ask(question, **kw):
        seen.update(question=question, **kw)
        return {"answer": "ok", "status": "answered", "context": "never returned"}
    import eawiki.query.ask as askmod
    monkeypatch.setattr(askmod, "ask", fake_ask)
    app = FastAPI()
    app.include_router(api.router)
    c = TestClient(app)
    r = c.post(f"/api/cases/{cid}/ask", json={"question": "who owns it?", "history": _talk(30), "focus": "D-2026-001"})
    assert r.status_code == 200 and r.json()["answer"] == "ok" and "context" not in r.json()
    assert seen["question"] == "who owns it?" and [h["content"] for h in seen["history"]] == [f"turn {i}" for i in range(20, 30)]
    ctx = seen["case_context"]
    assert ctx.startswith("The architect has D-2026-001 open") and "## STAGE: Recommendation" in ctx and "# THE DRAFTS" in ctx
    assert c.post("/api/cases/nope/ask", json={"question": "x"}).status_code == 404


# ---- the question, made standalone against the case --------------------------------------------------------------------------------

def test_a_question_with_no_history_is_read_against_the_case_so_the_documents_are_searched_for_the_right_thing(monkeypatch):
    from eawiki.query import graph as g
    case, cells = _synthetic(items=1, per=2, size=30)
    ctx = cc.build(case, cells)
    prompts = []
    monkeypatch.setattr(g, "llm_text", lambda p, b, m: (prompts.append(p), "Who owns the demand Demand 0?")[1])
    out = g.n_condense({"question": "who owns it?", "history": [], "case_context": ctx, "use_llm": True, "backend": "x", "model": None})
    assert out == {"search_question": "Who owns the demand Demand 0?"}
    assert "THE REQUEST" in prompts[0] and "Demand 0" in prompts[0] and "STAGE: Stage 1" not in prompts[0]           # the request, not every answer
    prompts.clear()
    same = g.n_condense({"question": "who owns it?", "history": [], "use_llm": True, "backend": "x", "model": None})
    assert same == {"search_question": "who owns it?"} and prompts == []                                              # a plain question needs no rewrite and no model call
    monkeypatch.setattr(g, "llm_text", lambda p, b, m: 1 / 0)
    assert g.n_condense({"question": "who owns it?", "history": [], "case_context": ctx, "use_llm": True, "backend": "x", "model": None}) == {"search_question": "who owns it?"}


def test_the_answer_is_told_what_the_case_is_and_to_say_whether_it_rests_on_it_or_on_the_documents():
    from eawiki.query import graph as g
    state = {"question": "q", "case_context": "# THE REQUEST: R", "_block_objs": [{"block_id": "d:1", "text": "t", "section_path": ["s"]}], "subgraph": None,
             "page": "", "wiki_pages": [], "route": {"strategy": "vector"}}
    ctx = g.n_relevance(state)["context"]
    assert ctx.startswith("THE CASE (the request, what each stage decided") and "# THE REQUEST: R" in ctx and "whether an answer rests on the case or on the documents" in ctx
