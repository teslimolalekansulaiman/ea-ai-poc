"""One draft for a whole request: the overview, a section for each demand with the demands handled together placed together, the
demand that did not pass the first check as returned, and the architect's part kept apart. Approved once, downloaded as the message."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import test_request_scope_engine as rs  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.api import cases as api  # noqa: E402
from eawiki.cases import document  # noqa: E402
from eawiki.cases.store import REQUEST_ID  # noqa: E402

PID = rs.PID


@pytest.fixture(autouse=True)
def _use_cases(monkeypatch):
    monkeypatch.setattr(usecases, "DIR", base.ROOT / "use_cases")


def _draft(items=4):
    e, cid, _ = rs._run(items=items)             # 001 names 003 (003 names nobody); 004 is alone; 006 fails the first check
    case = e.store.get_case(cid)
    [entry] = document.listing(e.store, case, PID)
    return e, cid, case, entry


def test_one_entry_for_the_request_with_the_overview_as_its_opening():
    e, cid, case, entry = _draft()
    d = entry["doc"]
    assert entry["item_id"] == REQUEST_ID and entry["title"] == "request" and entry["status"] == "draft"
    assert d["rec"] == {"title": "Recommendation for this request", "body": rs.OVERVIEW, "column": "Overview"}
    assert d["meta"] == "4 demands, 1 handled together" and d["facts"] == []


def test_demands_handled_together_come_first_under_their_group_the_others_follow_and_a_returned_one_is_last():
    e, cid, case, entry = _draft()
    msg = [s for s in entry["doc"]["sections"] if not s.get("internal")]
    assert [s["title"].split(" · ")[0] for s in msg] == ["D-2026-001", "D-2026-003", "D-2026-004", "D-2026-006"]        # the lead, its group, then the rest, then the returned
    assert [s.get("group") for s in msg] == ["Combined: D-2026-001, D-2026-003"] * 2 + [None, None]
    assert msg[0]["body"] == "Section for D-2026-001." and msg[0]["column"] == "Justification" and msg[0]["item"] == "D-2026-001"
    assert msg[3]["body"].startswith("Not assessed further. No: incident") and "column" not in msg[3]                   # the gate's own words


def test_the_architects_part_holds_each_demands_findings_what_is_open_and_where_the_answers_disagree():
    e, cid, case, entry = _draft()
    apart = [s for s in entry["doc"]["sections"] if s.get("internal")]
    titles = [s["title"] for s in apart]
    assert "D-2026-001 · Handled with" in titles and "D-2026-004 · Handled with" in titles and not any("Overlaps with" in t for t in titles)      # an open finding has no text to show
    assert next(s for s in apart if s["title"] == "D-2026-004 · Handled with")["body"] == "Alone"
    assert titles[-2:] == [document.TO_CONFIRM, document.EVIDENCE] or titles[-1] == document.TO_CONFIRM
    todo = next(s for s in apart if s["title"] == document.TO_CONFIRM)["body"]
    assert "? D-2026-003 did not name D-2026-001 as a match, though D-2026-001 named D-2026-003: confirm that they belong together." in todo
    assert all(s.get("item") for s in apart if s["title"] != document.TO_CONFIRM and s["title"] != document.EVIDENCE)        # each says which demand it is about


def test_an_edit_is_kept_and_one_approval_closes_the_phase():
    e, cid, case, entry = _draft()
    d = entry["doc"]
    d["rec"]["body"] = "Edited overview."
    out = document.edit(e.store, case, PID, REQUEST_ID, d)
    assert out["edited"] and out["doc"]["rec"]["body"] == "Edited overview." and out["original"]["rec"]["body"] == rs.OVERVIEW
    assert any(s.get("group") for s in out["doc"]["sections"]) and any(s.get("internal") for s in out["doc"]["sections"])      # the group and the part survive an edit
    assert case["state"]["phases"][PID]["status"] == "review"
    done = document.decide(e.store, case, PID, REQUEST_ID, "approve")
    assert done["status"] == "approved" and e.store.get_case(cid)["state"]["phases"][PID]["status"] == "approved"      # one approval, the whole phase
    with pytest.raises(PermissionError):
        document.edit(e.store, case, PID, REQUEST_ID, d)


def test_the_download_is_the_message_with_the_groups_named_and_without_the_architects_part():
    e, cid, case, entry = _draft()
    page = document.render_html(entry)
    assert rs.OVERVIEW in page and "Combined: D-2026-001, D-2026-003" in page and page.count("Combined: D-2026-001, D-2026-003") == 1       # the heading once for the group
    assert "Section for D-2026-004." in page and "Not assessed further." in page
    assert "Overlaps with" not in page and "Handled with" not in page and document.TO_CONFIRM not in page
    assert page.index("Section for D-2026-001.") < page.index("Section for D-2026-004.") < page.index("Not assessed further.")


def test_how_it_was_decided_works_for_a_demands_section_and_for_the_requests_own_text():
    e, cid, case, entry = _draft()
    t = document.trail(e.store, case, PID, "D-2026-001")
    assert "Justification" in t["columns"] and "Handled with" in t["columns"]
    r = document.trail(e.store, case, PID, REQUEST_ID)
    assert set(r["columns"]) == {"Overview"} and r["columns"]["Overview"]["status"] == "answered" and r["built_on"] == {}
    with pytest.raises(LookupError):
        document.trail(e.store, case, PID, "nobody")


def test_the_routes_serve_the_one_draft():
    e, cid, case, entry = _draft()
    app = FastAPI()
    app.include_router(api.router)
    api.set_engine(e)
    c = TestClient(app)
    got = c.get(f"/api/cases/{cid}/phases/{PID}/documents").json()["documents"]
    assert [x["item_id"] for x in got] == [REQUEST_ID]
    doc = got[0]["doc"]
    doc["rec"]["body"] = "Via the route."
    assert c.put(f"/api/cases/{cid}/phases/{PID}/documents/{REQUEST_ID}", json={"doc": doc}).json()["doc"]["rec"]["body"] == "Via the route."
    page = c.get(f"/api/cases/{cid}/phases/{PID}/documents/{REQUEST_ID}/export")
    assert page.status_code == 200 and "Via the route." in page.text and "Overlaps with" not in page.text
    assert c.get(f"/api/cases/{cid}/phases/{PID}/documents/{REQUEST_ID}/trail").status_code == 200
    assert c.post(f"/api/cases/{cid}/phases/{PID}/documents/{REQUEST_ID}/decision", json={"action": "approve"}).json()["status"] == "approved"
