"""A sheet of demands runs through Demand Management: gate, properties in order, questions, approval."""
import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eawiki import history  # noqa: E402

history.DB_PATH = Path(tempfile.mkdtemp()) / "cases_test.db"

from eawiki.cases import gather as gmod  # noqa: E402
from eawiki.cases import intake, plan as pmod, readiness, summary  # noqa: E402
from eawiki.cases.engine import Engine, levels  # noqa: E402
from eawiki.cases.store import CaseStore  # noqa: E402

SPEC = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))
ITEMS = intake.parse_file(SPEC, "x.csv", (ROOT / "use_cases" / "samples" / "demand-management-inputs.csv").read_bytes())["items"]
ITEMS.append({"demand_id": "D-2026-006", "title": "VPN not working for remote staff", "business_need": "VPN drops every 20 minutes",
              "expected_outcome": "Stable VPN", "department": "IT", "requester_role": "Analyst", "sponsor": "CIO",
              "date_submitted": "2026-08-20", "request_type": "New solution", "requester_urgency": "High",
              "target_go_live": "2026-09-01"})

CANNED = {
    "Demand type": "Digital", "Domain": ["Application", "Integration"], "Urgency": "High",
    "Priority": "Standard", "Mandate / business or DT objective": "O-02 / I-04",
    "Linked initiative or project": None,                           # cites nothing: the architect is asked
    "Impacted business capability": ["Employee Self-Service"], "Impacted application": ["HR system (C-204)"],
    "Is duplicate": "No", "Duplicate demand number (in the sheet)": "", "Duplicate with existing artefact / artefact name": "None",
    "Architecture principles and standards alignment": "Conforms", "Data classification": "Confidential",
    "Linked security capability": ["Identity and access management"], "Security review needed": "Yes",
    "Screening observation": "A digital demand.",
    "Recommendation": "Enhance existing", "Overlaps with": ["HR system"], "Consolidate with demand(s)": [],
    "Contract / licence match": "None", "Security fit": "Fits", "Recommended owner": "HR Systems Lead",
    "Justification": "Overlap with the HR system.", "Confidence": "Medium",
}


def fake_llm(prompt: str):
    if "decide WHERE an assistant should look" in prompt:
        return {"sources": ["demand", "documents"], "queries": ["{__text__}"], "documents": [], "bogus": 1}
    if "INTAKE QUESTIONS" in prompt:
        return {"outcome": "No: incident", "reason": "The VPN worked before."} if "VPN" in prompt else {"outcome": "Yes", "reason": ""}
    m = re.search(r"PROPERTY: (.+?)  \[", prompt)
    name = m.group(1)
    if "THE ARCHITECT POINTED YOU HERE" in prompt and "document Roadmap" in prompt:
        ids = re.findall(r"\[([^\]\s]+:\d+)\]", prompt)
        return {"value": "P-12 HR cloud move", "status": "answered", "evidence": ids[:1], "needs": "", "note": "found in the roadmap"}
    val = CANNED.get(name)
    ids = re.findall(r"\[([^\]\s]+:\d+)\]", prompt)
    if val is None:
        return {"value": "I Guess", "status": "answered", "evidence": [], "needs": "", "note": "guess"}
    ev = ids[:1] if name == "Mandate / business or DT objective" else []
    return {"value": val, "status": "answered", "evidence": ev, "needs": "", "note": "from the evidence"}


def fake_tools():
    block = {"block_id": "Strategy:1", "doc_id": "Strategy", "text": "O-02 employee requests handled digitally."}
    road = {"block_id": "Roadmap:7", "doc_id": "Roadmap", "text": "P-12 HR cloud move, owner HR."}
    return gmod.Tools(search=lambda q, k, docs: [road] if docs == ["Roadmap"] else ([] if docs else [block]), blocks_by_ids=lambda ids: [block],
                      link=lambda t: {"entities": [{"mention": "HR system", "ids": ["hr"], "names": ["HR system"]}]},
                      graph_facts=lambda ids: {"facts": "HR system --is_deployed_on--> Oracle DB", "block_ids": ["Strategy:1"]},
                      llm_json=fake_llm, doc_ids=lambda: ["Strategy", "Gap_Analysis_Sample", "Roadmap"])


def _engine():
    return Engine(CaseStore(), fake_tools, workers=4)


def test_levels_put_a_property_after_what_it_builds_on():
    cols = SPEC["stages"][0]["output"]["columns"]
    order = [[c["name"] for c in lv] for lv in levels([c for c in cols if c["name"] not in ("Screening observation", "Evidence")])]
    flat = [n for lv in order for n in lv]
    assert flat.index("Urgency") > flat.index("Mandate / business or DT objective")
    assert flat.index("Priority") > flat.index("Urgency")


def test_a_plan_cannot_point_at_something_that_does_not_exist():
    col = {"name": "X", "look_in": ["Strategy"]}
    p = pmod.validate({"sources": ["demand", "nonsense", "documents"], "queries": ["{business_need}", "{nope}"],
                       "documents": ["strategy", "Ghost"]}, col, ["business_need"], ["Strategy"])
    assert p["sources"] == ["demand", "documents"] and p["queries"] == ["{business_need}"] and p["documents"] == ["Strategy"]


def test_a_sheet_runs_asks_for_what_is_missing_and_moves_to_the_next_phase():
    e = _engine()
    cid = e.create(SPEC, ITEMS, "test")
    e.run_phase(cid, "screening")
    st = e.store
    cells = {(c["item_id"], c["column"]): c for c in st.cells(cid, "screening")}
    n_cols = len(SPEC["stages"][0]["output"]["columns"])
    assert len({c["item_id"] for c in cells.values()}) == 4 and len(cells) == 4 * n_cols
    assert cells[("D-2026-001", "Is it a true demand?")]["value"] == "Yes"
    # the incident is stopped at the gate: every other property reads Not assessed, with the reason
    assert cells[("D-2026-006", "Is it a true demand?")]["value"] == "No: incident"
    assert cells[("D-2026-006", "Domain")]["status"] == "not_assessed"
    assert cells[("D-2026-006", "Priority")]["value"] == "No score"
    assert "No: incident" in cells[("D-2026-006", "Screening observation")]["value"]
    # a property that needs a source and cited none is not answered: it opens a question
    c = cells[("D-2026-001", "Linked initiative or project")]
    assert c["status"] == "needs_input" and c["value"] == "" and "roadmap" in c["need"]
    qs = [q for q in st.questions(cid) if q["status"] == "open"]
    assert {q["column"] for q in qs} >= {"Linked initiative or project"} and len(qs) >= 3
    # a cited source is real; a property that needs none may rest on the demand
    assert cells[("D-2026-001", "Mandate / business or DT objective")]["evidence"] == ["Strategy:1"]
    assert cells[("D-2026-001", "Priority")]["status"] == "answered"
    # the citations property is the union, in code
    assert cells[("D-2026-001", "Evidence")]["value"] == ["Strategy:1"]
    # the summary is computed from the cells
    sm = summary.phase_summary(SPEC, SPEC["stages"][0], st.cells(cid), e.store.get_case(cid)["items"], st.questions(cid))
    assert sm["assessed"] == 3 and sm["total"] == 4 and sm["returned"][0]["id"] == "D-2026-006"
    assert {k["label"]: k["value"] for k in sm["kpis"]}["Security review"] == 3
    assert "Which demands were returned, and why?" in sm["suggested"]
    # the architect answers: stored as theirs, and what builds on it is decided again
    q = next(q for q in qs if q["item_id"] == "D-2026-001" and q["column"] == "Linked initiative or project")
    out = e.answer(q["id"], "P-103 HR system cloud migration", background=False)
    assert out["status"] == "answered"
    again = {c["column"]: c for c in st.cells(cid, "screening") if c["item_id"] == "D-2026-001"}
    assert again["Linked initiative or project"]["status"] == "user" and again["Linked initiative or project"]["source"] == "user"
    # approve: the next phase runs for the assessed demands only
    assert st.get_case(cid)["state"]["phases"]["screening"]["status"] == "review"
    e.approve(cid, "screening", background=False)
    rec = {(c["item_id"], c["column"]) for c in st.cells(cid, "recommendation")}
    assert {i for i, _ in rec} == {"D-2026-001", "D-2026-003", "D-2026-004"}


def test_the_architect_can_point_at_a_document_instead_of_giving_the_value():
    e = _engine()
    cid = e.create(SPEC, ITEMS[:1], "look")
    e.run_phase(cid, "screening")
    q = next(q for q in e.store.questions(cid) if q["status"] == "open" and q["column"] == "Linked initiative or project")
    for bad in (dict(document="Nope", where=""), dict(document=None, where="")):
        try:
            e.look(q["id"], bad["document"], bad["where"], background=False)
            assert False, "should refuse"
        except ValueError as err:
            assert str(err)
    # a document that has nothing: the question stays open and says what was tried; nothing is guessed
    e.look(q["id"], "Strategy", "the roadmap row", background=False)
    q2 = e.store.get_question(q["id"])
    assert q2["status"] == "open" and "Looked at document Strategy" in q2["text"]
    # the right document: answered with a real citation, the question closes
    e.look(q["id"], "Roadmap", "HR cloud move", background=False)
    assert e.store.get_question(q["id"])["status"] == "answered"
    c = next(c for c in e.store.cells(cid, "screening") if c["column"] == "Linked initiative or project")
    assert c["status"] == "answered" and c["source"] == "model" and c["evidence"] == ["Roadmap:7"]
    assert c["how"][0].startswith("The architect pointed to: document Roadmap")


def test_readiness_names_the_missing_document_and_the_empty_source():
    spec = json.loads(json.dumps(SPEC))
    spec["stages"][0]["output"]["columns"][5]["look_in"] = ["Roadmap_Not_Ingested"]
    rep = readiness.readiness(spec, [dict(i, _id=i["demand_id"]) for i in ITEMS[:3]], fake_tools())
    props = {p["property"]: p for p in rep["phases"][0]["properties"]}
    p = props["Urgency"]
    assert p["verdict"] in ("ready", "partial")
    miss = props[spec["stages"][0]["output"]["columns"][5]["name"]]
    assert miss["verdict"] == "not_ready" and "not ingested" in miss["reasons"][0]


def test_api_runs_in_the_background_and_the_screen_can_follow_it():
    from fastapi.testclient import TestClient
    from eawiki.api import cases as api
    from eawiki.api.app import app
    api.set_engine(_engine())
    client = TestClient(app)
    r = client.post("/api/cases/parse-file", params={"use_case_id": "demand-management"},
                    files={"file": ("d.csv", (ROOT / "use_cases" / "samples" / "demand-management-inputs.csv").read_bytes())})
    assert r.status_code == 200 and len(r.json()["items"]) == 3
    cid = client.post("/api/cases", json={"use_case_id": "demand-management", "items": r.json()["items"], "name": "t"}).json()["id"]
    for _ in range(100):
        d = client.get(f"/api/cases/{cid}").json()
        if d["phases"][0]["state"].get("status") == "review":
            break
        time.sleep(0.1)
    assert d["phases"][0]["state"]["status"] == "review"
    assert d["cells"]["screening"]["D-2026-001"]["Domain"]["display"] == "answered"
    assert any(e["kind"] == "phase_done" for e in d["events"]) and d["last_seq"] >= 1
    assert client.post(f"/api/cases/{cid}/phases/recommendation/approve").status_code == 409   # not ready for review
    api.set_engine(None)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
