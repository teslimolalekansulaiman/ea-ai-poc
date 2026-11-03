"""A stage shown as documents: one draft per demand, composed in code, edited and approved by the architect."""
import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.api import cases as api  # noqa: E402
from eawiki.cases import document  # noqa: E402
from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import CaseStore  # noqa: E402

SPEC = base.SPEC
STAGE = SPEC["stages"][1]
PID = "recommendation"
ID = "D-2026-001"


def _cell(value, status="answered", need="", evidence=()):
    return {"value": value, "status": status, "need": need, "evidence": list(evidence)}


def test_the_document_is_composed_from_the_cells_in_the_order_the_use_case_declares():
    cells = {
        "Recommendation": _cell("Merge/CR"), "Recommended action": _cell("Do not raise a new demand. Merge it into D-2026-014."),
        "Recommended owner": _cell("Customer Services IT"), "Consolidate with demand(s)": _cell(["D-2026-014"]),
        "Overlaps with": _cell(["CRM Suite", "Customer Portal"]), "Contract / licence match": _cell("Covered until March 2027"),
        "Security fit": _cell("", "needs_input", need="Which data classification applies?"), "Justification": _cell("The module exists."),
        "Confidence": _cell("Medium"), "Evidence": _cell(["Applications:3", "Contracts:41"]),
    }
    d = document.compose(SPEC, STAGE, {"_id": ID, "title": "Complaint tracking"}, cells, [("Linked initiative or project", "Which roadmap project?")])
    assert d["title"] == "Complaint tracking" and d["meta"] == ID
    assert d["rec"] == {"title": STAGE["name"], "body": "Do not raise a new demand. Merge it into D-2026-014."}
    # the tag is the stage's row tag, then the key lines; list values read one to a line
    assert d["facts"] == [{"label": "Recommendation", "value": "Merge/CR"}, {"label": "Recommended owner", "value": "Customer Services IT"},
                          {"label": "Consolidate with demand(s)", "value": "D-2026-014"}]
    titles = [s["title"] for s in d["sections"]]
    assert titles == ["Overlaps with", "Contract / licence match", "Justification", document.TO_CONFIRM, document.EVIDENCE]
    assert d["sections"][0]["body"] == "CRM Suite\nCustomer Portal"
    # a grade is for the table, not for a page that is signed; an open cell is listed to confirm, not shown as a section
    assert "Confidence" not in titles and "Security fit" not in titles
    assert d["sections"][3]["body"] == "? Security fit: Which data classification applies?\n? Linked initiative or project: Which roadmap project?"
    assert d["sections"][4]["body"] == "Applications:3\nContracts:41"


def test_without_a_statement_property_the_stage_summary_opens_the_document():
    stage = copy.deepcopy(STAGE)
    stage["output"].pop("document")
    d = document.compose(SPEC, stage, {"_id": ID}, {"Justification": _cell("Because.")})
    assert d["rec"]["body"] == "Because." and d["facts"] == []


def test_an_edit_may_only_be_text_and_is_bounded():
    got = document.clean({"title": " T ", "meta": 5, "rec": {"title": "R", "body": "x" * 9000, "extra": 1}, "junk": 1,
                          "facts": [{"label": "a", "value": "b"}, {"label": "", "value": ""}, "no"] + [{"label": "k", "value": "v"}] * 20,
                          "sections": [{"title": "S", "body": "B"}, {"title": "", "body": ""}]})
    assert got["title"] == "T" and got["meta"] == "" and len(got["rec"]["body"]) == document.MAX_TEXT and set(got) == {"title", "meta", "rec", "facts", "sections"}
    assert len(got["facts"]) == document.MAX_FACTS and got["sections"] == [{"title": "S", "body": "B"}]
    with pytest.raises(ValueError):
        document.clean("text")


# ---- review: a case run for real ------------------------------------------------------------------------------------

def _llm(prompt):
    m = re.search(r"PROPERTY: (.+?)  \[", prompt)
    if m and m.group(1) == "Recommended action":
        return {"value": "Merge this request into D-2026-014.", "status": "answered", "evidence": ["Strategy:1"], "needs": "", "note": "n"}
    return base.fake_llm(prompt)


def _case():
    def tools():
        t = base.fake_tools()
        t.llm_json = _llm
        return t
    e = Engine(CaseStore(), tools, workers=2)
    cid = e.create(SPEC, base.ITEMS[:2], "docs")
    e.run_phase(cid, "screening")
    e.approve(cid, "screening", background=False)
    return e, cid


def test_a_draft_follows_the_results_until_the_architect_edits_it():
    e, cid = _case()
    case = e.store.get_case(cid)
    docs = document.listing(e.store, case, PID)
    assert [d["item_id"] for d in docs] == [ID, "D-2026-003"] and {d["status"] for d in docs} == {"draft"}
    d = docs[0]
    assert d["doc"]["rec"]["body"] == "Merge this request into D-2026-014." and not d["edited"] and d["doc"] == d["original"]
    # the first edit keeps the draft it started from
    changed = copy.deepcopy(d["doc"])
    changed["rec"]["body"] = "Do not raise a new demand."
    out = document.edit(e.store, case, PID, ID, changed)
    assert out["edited"] and out["doc"]["rec"]["body"] == "Do not raise a new demand." and out["original"]["rec"]["body"] == "Merge this request into D-2026-014."
    # a second edit still compares with the first draft
    changed["rec"]["body"] = "Merge into D-2026-014."
    assert document.edit(e.store, case, PID, ID, changed)["original"] == d["original"]
    # the answers change underneath: the edit stays, and the screen is told
    e.store.save_cell(cid, ID, PID, "Recommended owner", value="Someone else", status="answered", source="model")
    again = next(x for x in document.listing(e.store, case, PID) if x["item_id"] == ID)
    assert again["doc"]["rec"]["body"] == "Merge into D-2026-014." and again["stale"] is True


def test_approve_locks_the_text_and_the_last_approval_closes_the_phase():
    e, cid = _case()
    case = e.store.get_case(cid)
    assert case["state"]["phases"][PID]["status"] == "review"            # the run has finished and waits for the architect
    first = document.decide(e.store, case, PID, ID, "approve")
    assert first["status"] == "approved" and first["decided_at"]
    assert e.store.get_case(cid)["state"]["phases"][PID]["status"] == "review"           # one demand is still open
    with pytest.raises(PermissionError):
        document.edit(e.store, case, PID, ID, first["doc"])
    with pytest.raises(PermissionError):
        document.decide(e.store, case, PID, ID, "return", "no")
    # running the stage again does not touch an approved document
    e.store.save_cell(cid, ID, PID, "Recommended action", value="Something new", status="answered", source="model")
    assert next(x for x in document.listing(e.store, case, PID) if x["item_id"] == ID)["doc"]["rec"]["body"] == "Merge this request into D-2026-014."
    document.decide(e.store, case, PID, "D-2026-003", "approve")
    assert e.store.get_case(cid)["state"]["phases"][PID]["status"] == "approved"


def test_a_return_needs_a_note_and_can_be_reopened_but_nothing_is_decided_before_the_phase_is_finished():
    e, cid = _case()
    e.store.set_phase(cid, PID, status="running")
    case = e.store.get_case(cid)
    with pytest.raises(PermissionError, match="not finished"):
        document.decide(e.store, case, PID, ID, "approve")
    e.store.set_phase(cid, PID, status="review")
    case = e.store.get_case(cid)
    with pytest.raises(ValueError, match="what should change"):
        document.decide(e.store, case, PID, ID, "return", "  ")
    with pytest.raises(ValueError):
        document.decide(e.store, case, PID, ID, "reopen")                               # only a returned one
    r = document.decide(e.store, case, PID, ID, "return", "Name the licence owner.")
    assert r["status"] == "returned" and r["note"] == "Name the licence owner."
    assert document.decide(e.store, case, PID, ID, "reopen")["status"] == "draft"
    with pytest.raises(ValueError):
        document.decide(e.store, case, PID, ID, "sign")


def test_a_phase_not_shown_as_documents_has_none():
    e, cid = _case()
    with pytest.raises(LookupError):
        document.listing(e.store, e.store.get_case(cid), "screening")


def test_the_download_is_a_page_that_says_when_it_is_only_a_draft():
    e, cid = _case()
    page = document.render_html(document.listing(e.store, e.store.get_case(cid), PID)[0])
    assert page.startswith("<!doctype html>") and "Merge this request into D-2026-014." in page and "Draft. Nothing in it is a decision" in page
    assert "<script" not in page


# ---- the routes -----------------------------------------------------------------------------------------------------

def test_the_routes_list_edit_decide_and_download():
    e, cid = _case()
    e.store.set_phase(cid, PID, status="review")
    api.get_engine = lambda: e
    api.store = lambda: e.store
    app = FastAPI()
    app.include_router(api.router)
    c = TestClient(app)
    base_url = f"/api/cases/{cid}/phases/{PID}/documents"
    docs = c.get(base_url).json()["documents"]
    assert docs[0]["item_id"] == ID and docs[0]["status"] == "draft"
    assert c.get(f"/api/cases/{cid}/phases/screening/documents").status_code == 404
    doc = docs[0]["doc"]
    doc["sections"].append({"title": "Added by the EA", "body": "A note."})
    r = c.put(f"{base_url}/{ID}", json={"doc": doc})
    assert r.status_code == 200 and r.json()["edited"] and r.json()["doc"]["sections"][-1]["title"] == "Added by the EA"
    assert c.put(f"{base_url}/{ID}", json={"doc": "text"}).status_code == 422             # not an object: refused before it is read
    assert c.post(f"{base_url}/{ID}/decision", json={"action": "return", "note": ""}).status_code == 400
    assert c.post(f"{base_url}/{ID}/decision", json={"action": "approve"}).json()["status"] == "approved"
    assert c.put(f"{base_url}/{ID}", json={"doc": doc}).status_code == 409
    x = c.get(f"{base_url}/{ID}/export")
    assert x.status_code == 200 and x.headers["content-disposition"].startswith("attachment") and "Added by the EA" in x.text
    assert c.get(f"{base_url}/nobody/export").status_code == 404
    phases = c.get(f"/api/cases/{cid}").json()["phases"]
    assert [p["mode"] for p in phases] == ["table", "document"]


# ---- the settings ---------------------------------------------------------------------------------------------------

def test_the_document_settings_are_checked():
    spec = copy.deepcopy(SPEC)
    assert usecases.validate(spec) == []
    out = spec["stages"][1]["output"]
    assert out["mode"] == "document" and out["document"]["statement"] == "Recommended action"
    out["mode"] = "poster"
    assert any("table or as documents" in e for e in usecases.validate(spec))
    out["mode"] = "document"
    out["document"]["statement"] = "Recommendation"                        # a pick list is not text
    assert any("headline text" in e for e in usecases.validate(spec))
    out["document"]["statement"] = "Recommended action"
    out["document"]["facts"] = ["No such property"]
    assert any("key lines" in e for e in usecases.validate(spec))
