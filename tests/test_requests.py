"""A request: demands gathered before a case exists. What is missing is worked out in code; the person fills it in,
asks the requester, or starts anyway; submitting hands the demands to the engine the way a sheet always did."""
import csv
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from eawiki import completeness, usecases  # noqa: E402
from eawiki.api import cases as cases_api  # noqa: E402
from eawiki.api.app import app  # noqa: E402
from eawiki.cases import intake  # noqa: E402
from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import store  # noqa: E402
from eawiki.query import executor  # noqa: E402

SPEC = base.SPEC
UC = "demand-management"
HEAD = ["Demand ID", "Date submitted", "Requesting department", "Requester role", "Business sponsor", "Demand title", "Business need / problem",
        "Expected outcome / benefit", "Request type", "Requester urgency", "Reason for urgency / deadline", "Target go-live", "Systems or data mentioned"]


def _row(id_, **over):
    r = {"Demand ID": id_, "Date submitted": "2026-10-01", "Requesting department": "Customer Services", "Requester role": "Manager",
         "Business sponsor": "Chief Customer Officer", "Demand title": f"Title of {id_}", "Business need / problem": "A real need, described.",
         "Expected outcome / benefit": "A real outcome.", "Request type": "New solution", "Requester urgency": "High",
         "Reason for urgency / deadline": "", "Target go-live": "2027-03-31", "Systems or data mentioned": ""}
    r.update(over)
    return r


def _csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEAD)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


ROWS = [_row("D-2026-014"), _row("D-2026-055", **{"Business sponsor": ""}),
        _row("D-2026-056", **{"Business sponsor": "", "Target go-live": ""}), _row("D-2026-052")]


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(usecases, "DIR", base.ROOT / "use_cases")             # other tests leave the use case folder pointing at a temporary one
    e = Engine(store(), base.fake_tools, workers=2)
    cases_api.set_engine(e)
    yield TestClient(app)
    cases_api.set_engine(None)


def _start(client, rows=ROWS, name="october.csv"):
    r = client.post("/api/requests/from-file", params={"use_case_id": UC}, files={"file": (name, _csv(rows))})
    assert r.status_code == 200, r.text
    return r.json()


# ---- the check, in code ---------------------------------------------------------------------------------------------

def test_a_field_is_missing_when_it_is_required_and_has_no_text():
    miss = completeness.missing_fields(SPEC, {"demand_id": "D-1", "title": "  ", "sponsor": "x"})
    names = [m["name"] for m in miss]
    assert "title" in names and "sponsor" not in names and "urgency_reason" not in names and "systems_mentioned" not in names
    assert miss[0] == {"name": "date_submitted", "label": "Date submitted"}                         # the use case's order, with its labels
    assert completeness.missing_fields(SPEC, {f["name"]: "x" for f in completeness.input_fields(SPEC)}) == []


def test_it_asks_about_whatever_fields_a_use_case_declares():
    other = {"input": {"item_fields": [{"name": "site", "label": "Site", "required": True}, {"name": "note", "required": False}, {"name": "owner", "required": True}]}}
    assert [m["label"] for m in completeness.missing_fields(other, {"owner": "x"})] == ["Site"]


def _old_missing_required(spec, it):
    """The gate's check as it was before it shared the function."""
    if it.get("_pasted"):
        return []
    fields = (spec.get("input") or {}).get("item_fields") or []
    names = {f["name"] for f in fields if f.get("name")}
    if sum(1 for k in it if k in names and str(it[k]).strip()) < 3:
        return []
    return [f.get("label") or f["name"] for f in fields
            if f.get("required") and f.get("name") and not str(it.get(f["name"]) or "").strip()]


def test_the_engines_gate_check_is_unchanged():
    full = {f["name"]: "x" for f in completeness.input_fields(SPEC)}
    cases = [{}, {"title": "t"}, {"title": "t", "business_need": "n"}, {"_pasted": True, "title": "t", "business_need": "n", "sponsor": "s"},
             dict(full), {**full, "sponsor": ""}, {**full, "sponsor": "  ", "target_go_live": None}, {**full, "_pasted": True, "sponsor": ""},
             {"title": "t", "business_need": "n", "department": "d"}, {"title": "t", "business_need": "n", "department": "d", "sponsor": ""}]
    for it in cases:
        assert executor._missing_required(SPEC, it) == _old_missing_required(SPEC, it), it


# ---- the request ------------------------------------------------------------------------------------------------------

def test_a_sheet_becomes_a_request_that_says_what_each_demand_is_missing(client):
    v = _start(client)
    assert v["status"] == "drafting" and v["files"] == ["october.csv"] and v["name"] == "october"
    by = {i["id"]: i for i in v["items"]}
    assert set(by) == {"D-2026-014", "D-2026-055", "D-2026-056", "D-2026-052"}
    assert by["D-2026-014"]["missing"] == []
    assert [m["name"] for m in by["D-2026-055"]["missing"]] == ["sponsor"]
    assert [m["name"] for m in by["D-2026-056"]["missing"]] == ["sponsor", "target_go_live"]
    assert v["summary"] == {"total": 4, "complete": 2, "incomplete": 2, "problems": 0} and v["ready"] is False
    # a field missing in several demands is offered once, with the demands it is missing from
    assert [(g["field"], g["items"]) for g in v["groups"]] == [("sponsor", ["D-2026-055", "D-2026-056"])]
    assert v["item_label"]["plural"] == "demands" and any(f["name"] == "request_type" and f["values"] for f in v["fields"])
    assert client.get(f"/api/requests/{v['id']}").json()["summary"] == v["summary"]


def test_the_person_chooses_which_demands_share_a_value(client):
    v = _start(client)
    rid = v["id"]
    r = client.post(f"/api/requests/{rid}/fill", json={"field": "sponsor", "items": ["D-2026-055"], "value": "Chief Operating Officer"}).json()
    assert r["changed"] == ["D-2026-055"] and r["skipped"] == []
    by = {i["id"]: i for i in r["items"]}
    assert by["D-2026-055"]["missing"] == [] and by["D-2026-055"]["set"] == {"sponsor": "you"} and by["D-2026-055"]["values"]["sponsor"] == "Chief Operating Officer"
    assert [m["name"] for m in by["D-2026-056"]["missing"]] == ["sponsor", "target_go_live"]               # not touched: never assumed shared
    # a demand that already has a value is left alone
    r2 = client.post(f"/api/requests/{rid}/fill", json={"field": "sponsor", "items": ["D-2026-055", "D-2026-014"], "value": "Someone"}).json()
    assert r2["changed"] == [] and sorted(r2["skipped"]) == ["D-2026-014", "D-2026-055"]
    assert {i["id"]: i for i in r2["items"]}["D-2026-014"]["values"]["sponsor"] == "Chief Customer Officer"


def test_ask_the_requester_is_remembered_and_cleared_by_a_value(client):
    rid = _start(client)["id"]
    r = client.post(f"/api/requests/{rid}/fill", json={"field": "sponsor", "items": ["D-2026-055", "D-2026-056"], "decline": True}).json()
    by = {i["id"]: i for i in r["items"]}
    assert by["D-2026-055"]["declined"] == ["sponsor"] and by["D-2026-056"]["declined"] == ["sponsor"]
    assert by["D-2026-055"]["missing"] != []                                                               # declined is still a gap: the demand is held
    r = client.put(f"/api/requests/{rid}/items/D-2026-055", json={"values": {"sponsor": "COO"}}).json()
    by = {i["id"]: i for i in r["items"]}
    assert by["D-2026-055"]["declined"] == [] and by["D-2026-055"]["missing"] == []
    r = client.put(f"/api/requests/{rid}/items/D-2026-056", json={"declined": ["sponsor", "target_go_live", "title"]}).json()
    assert {i["id"]: i for i in r["items"]}["D-2026-056"]["declined"] == ["sponsor", "target_go_live"]   # a field with a value cannot be declined


def test_values_are_checked(client):
    rid = _start(client)["id"]
    url = f"/api/requests/{rid}/items/D-2026-055"
    assert client.put(url, json={"values": {"nonsense": "x"}}).status_code == 400
    assert client.put(url, json={"values": {"sponsor": "x" * 4001}}).status_code == 400
    bad = client.put(url, json={"values": {"request_type": "Magic"}})
    assert bad.status_code == 400 and "not one of" in bad.json()["detail"]
    assert client.put(url, json={"values": {"request_type": "new solution"}}).json()["items"][1]["values"]["request_type"] == "New solution"   # the pick list's own spelling
    assert client.put(f"/api/requests/{rid}/items/D-9", json={"values": {}}).status_code == 404
    assert client.get("/api/requests/nope").status_code == 404
    assert client.post(f"/api/requests/{rid}/fill", json={"field": "sponsor", "items": ["D-2026-055"]}).status_code == 400    # nothing to fill in


def test_two_demands_with_the_same_id_block_the_submit_until_one_changes(client):
    v = _start(client, [_row("D-1"), _row("D-1", **{"Demand title": "Another"})])
    assert v["summary"]["problems"] == 2 and "same ID" in v["items"][0]["problems"][0]
    r = client.post(f"/api/requests/{v['id']}/submit", json={"allow_incomplete": True})
    assert r.status_code == 400 and "same ID" in r.json()["detail"]
    fixed = client.put(f"/api/requests/{v['id']}/items/D-1", json={"values": {"demand_id": "D-2"}}).json()
    assert fixed["summary"]["problems"] == 0 and sorted(i["id"] for i in fixed["items"]) == ["D-1", "D-2"]    # the id follows its field


def test_the_gaps_come_as_a_sheet_to_send_back(client):
    rid = _start(client)["id"]
    r = client.get(f"/api/requests/{rid}/gaps")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"] and "attachment" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Missing information"]
    assert [c.value for c in ws[1]] == ["Demand", "Title", "Missing", "Business sponsor", "Target go-live"]
    assert [c.value for c in ws["A"]][1:] == ["D-2026-055", "D-2026-056"]                                      # only the incomplete demands
    assert ws["C3"].value == "Business sponsor; Target go-live" and ws["D2"].value in (None, "") and ws["E2"].value == "2027-03-31"
    assert ws["D2"].fill.fgColor.rgb.endswith("FBF0D9") and not ws["E2"].fill.fgColor.rgb.endswith("FBF0D9")      # the gaps are marked, what is there is shown
    guide = wb["Field guide"]
    assert guide.max_row == len(SPEC["input"]["item_fields"]) + 1 and "New solution" in (guide["C10"].value or "")


def test_a_request_that_is_complete_starts_a_case_like_the_sheet_always_did(client):
    full = [_row("D-2026-014"), _row("D-2026-052")]
    v = _start(client, full)
    assert v["ready"] is True
    out = client.post(f"/api/requests/{v['id']}/submit", json={}).json()
    assert out["held"] == [] and out["case_id"]
    got = store().get_case(out["case_id"])
    direct = intake.parse_file(SPEC, "x.csv", _csv(full))["items"]
    strip = lambda it: {k: val for k, val in it.items() if not k.startswith("_")}                            # noqa: E731
    assert [strip(i) for i in got["items"]] == [strip(i) for i in direct]
    assert [i["_id"] for i in got["items"]] == ["D-2026-014", "D-2026-052"] and got["name"] == "october"
    # submitted: the request says which case, and can no longer be changed
    after = client.get(f"/api/requests/{v['id']}").json()
    assert after["status"] == "submitted" and after["case_id"] == out["case_id"]
    assert client.put(f"/api/requests/{v['id']}/items/D-2026-014", json={"values": {"sponsor": "x"}}).status_code == 409
    assert client.post(f"/api/requests/{v['id']}/submit", json={}).status_code == 409


def test_starting_with_gaps_needs_the_person_to_say_so_and_the_engine_then_holds_those_demands(client):
    v = _start(client)
    rid = v["id"]
    r = client.post(f"/api/requests/{rid}/submit", json={})
    assert r.status_code == 409 and "2 demands still miss required information" in r.json()["detail"]
    out = client.post(f"/api/requests/{rid}/submit", json={"allow_incomplete": True}).json()
    assert out["held"] == ["D-2026-055", "D-2026-056"]
    cid = out["case_id"]
    for _ in range(100):
        d = client.get(f"/api/cases/{cid}").json()
        if d["phases"][0]["state"].get("status") == "review":
            break
        time.sleep(0.1)
    gate = {i: c["Is it a true demand?"] for i, c in d["cells"]["screening"].items()}
    assert gate["D-2026-055"]["value"].startswith("Not yet") and "Business sponsor" in " ".join(gate["D-2026-055"]["how"])
    assert "Target go-live" in " ".join(gate["D-2026-056"]["how"])
    assert gate["D-2026-014"]["value"] == "Yes" and gate["D-2026-052"]["value"] == "Yes"                      # the complete ones carry on


def test_a_typed_demand_can_start_a_request_too(client):
    r = client.post("/api/requests/from-text", json={"use_case_id": UC, "text": "We need a way to track complaints and report response times."})
    assert r.status_code == 200
    v = r.json()
    assert v["summary"]["total"] == 1 and len(v["items"][0]["missing"]) > 5 and v["files"] == []
    assert client.post("/api/requests/from-file", params={"use_case_id": UC}, files={"file": ("e.csv", b"nothing,here\n")}).status_code == 400
    assert client.post("/api/requests/from-file", params={"use_case_id": "nope"}, files={"file": ("e.csv", b"x")}).status_code == 404
