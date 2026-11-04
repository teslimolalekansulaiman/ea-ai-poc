"""A stage that works once for the whole request: the groups the items form (worked out in code), a property written once from every
item's answers, and what the rest of the engine does and does not do with them."""
import copy
import io
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
from eawiki.cases import engine as eng  # noqa: E402
from eawiki.cases import groups  # noqa: E402
from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import REQUEST_ID, CaseStore  # noqa: E402

PID = "recommendation"
OVERVIEW = "One overview of the whole request."


@pytest.fixture(autouse=True)
def _use_cases(monkeypatch):
    monkeypatch.setattr(usecases, "DIR", base.ROOT / "use_cases")


# ---- the groups -----------------------------------------------------------------------------------------------------

def test_items_linked_in_either_direction_form_a_group_led_by_the_earliest():
    ids = ["A", "B", "C", "D", "E"]
    links = {"A": ["B"], "B": [], "C": ["B"], "D": [], "E": ["E", "Z"]}              # A and C name B; B names nobody; E names itself and a stranger
    got = groups.form(ids, links, {"A": "2026-08-14", "B": "2026-08-03", "C": "2026-08-19", "D": "2026-01-01", "E": "2026-01-01"})
    assert [(g["lead"], g["members"]) for g in got] == [("B", ["B", "A", "C"])]      # D and E are alone; B is the earliest, the others in the order they came
    assert got[0]["disagree"] == [("A", "B"), ("C", "B")]                             # they named B, B did not name them
    assert groups.describe(got, "B") == "Combined with A, C; lead: B (A named B but B did not name A; C named B but B did not name C)"
    assert groups.describe(got, "A") == "Combined with B, C; lead: B (A named B but B did not name A)"
    assert groups.describe(got, "D") == groups.ALONE == "Alone"


def test_the_lead_falls_back_to_the_order_the_items_came_in_when_there_is_nothing_to_choose_by():
    ids = ["X", "Y", "Z"]
    both = {"X": ["Y"], "Y": ["X"], "Z": []}
    assert groups.form(ids, both)[0]["lead"] == "X" and groups.form(ids, both)[0]["disagree"] == []
    assert groups.form(ids, both, {"X": "12/02", "Y": "2026-01-01"})[0]["lead"] == "Y"      # a date that is not year-month-day has no order: the dated one leads
    assert groups.form(ids, both, {"X": "2026-05-01", "Y": "2026-05-01"})[0]["lead"] == "X"  # a tie keeps the order
    two = groups.form(["P", "Q", "R", "S"], {"P": ["Q"], "R": ["S"]})
    assert [g["members"] for g in two] == [["P", "Q"], ["R", "S"]]


# ---- a run of the stage ------------------------------------------------------------------------------------------------

def _spec():
    spec = copy.deepcopy(base.SPEC_P2)
    cols = spec["stages"][1]["output"]["columns"]
    by = {c["name"]: c for c in cols}
    by["Justification"]["sees_others"] = ["Recommended owner", "Handled with"]                      # the summary property: this stage's answers, for the others
    cols.insert(-2, {"name": "Handled with", "type": "text", "derive": {"kind": "groups", "from": "Consolidate with demand(s)", "lead_by": "date_submitted"}})
    cols.insert(-2, {"name": "Overview", "type": "text", "scope": "request", "evidence_required": False, "activity": "Writing the overview",
                     "sees_others": ["Recommended owner", "Handled with", "Justification"]})
    spec["stages"][1]["output"]["document"] = {"scope": "request", "statement": "Overview", "item_text": "Justification", "internal": ["Overlaps with", "Handled with"]}
    assert usecases.validate(spec) == []
    return spec


def _run(spec=None, items=2):
    prompts = []

    def llm(prompt):
        m = re.search(r"PROPERTY: (.+?)  \[", prompt)
        name = m.group(1) if m else ""
        if name in ("Consolidate with demand(s)", "Overview", "Justification", "Recommended owner") and "INSTRUCTIONS FOR THIS STAGE" in prompt:
            prompts.append((name, prompt))
            ids = re.findall(r"\[([^\]\s]+:\d+)\]", prompt)
            mine = re.search(r"\[demand:demand_id\] Demand ID: (\S+)", prompt)
            if name == "Consolidate with demand(s)":
                value = ["D-2026-003"] if mine and mine.group(1) == "D-2026-001" else ["None"]     # 001 names 003; 003 names nobody
                return {"value": value, "status": "answered", "evidence": ids[:1], "needs": "", "note": "n"}
            value = OVERVIEW if name == "Overview" else "HR Systems Lead" if name == "Recommended owner" else f"Section for {mine.group(1) if mine else '?'}."
            return {"value": value, "status": "answered", "evidence": [] if name == "Overview" else ids[:1], "needs": "", "note": "n"}
        return base.fake_llm(prompt)

    def tools():
        t = base.fake_tools()
        t.llm_json = llm
        return t

    e = Engine(CaseStore(), tools, workers=2)
    cid = e.create(spec or _spec(), base.ITEMS[:items], "request")
    e.run_phase(cid, "screening")
    e.approve(cid, "screening", background=False)
    return e, cid, prompts


def test_the_groups_are_written_in_code_and_the_request_text_is_written_once_from_every_demand():
    e, cid, prompts = _run()
    cells = {(c["item_id"], c["column"]): c for c in e.store.cells(cid, PID)}
    assert cells[("D-2026-001", "Handled with")]["value"] == "Combined with D-2026-003; lead: D-2026-001 (D-2026-001 named D-2026-003 but D-2026-003 did not name D-2026-001)"
    assert cells[("D-2026-003", "Handled with")]["value"].startswith("Combined with D-2026-001; lead: D-2026-001")
    assert cells[("D-2026-001", "Handled with")]["source"] == "rule"                                   # no model said it
    # the request's text has no item: it is kept apart, and no demand has a cell for it
    req = e.store.request_cells(cid, PID)
    assert req["Overview"]["value"] == OVERVIEW and req["Overview"]["status"] == "answered"
    assert not any(c["column"] == "Overview" or c["item_id"] == REQUEST_ID for c in e.store.cells(cid, PID))
    # it was written once, after every demand's own section, and it read all of them
    names = [n for n, _p in prompts]
    assert names.count("Overview") == 1 and names.index("Overview") > max(i for i, n in enumerate(names) if n == "Justification")
    p = next(p for n, p in prompts if n == "Overview")
    assert "ONE request, which holds several demands" in p and "THE DEMANDS IN THIS REQUEST, and what has been decided for each" in p
    assert "ALREADY DECIDED FOR THIS DEMAND" not in p
    assert re.findall(r"^- (D-2026-\d+) \(", p.split("THE DEMANDS IN THIS REQUEST")[1], re.M) == ["D-2026-001", "D-2026-003"]
    assert "Handled with: Combined with D-2026-003; lead: D-2026-001" in p and "Justification: Section for D-2026-003." in p       # their own sections, written before it
    assert "Recommended owner: HR Systems Lead" in p
    # a demand's own section was shown the OTHER demands' answers of this stage, and not its own
    mine = next(p for n, p in prompts if n == "Justification" and "Demand ID: D-2026-001" in p)
    assert "THE OTHER DEMANDS IN THIS REQUEST" in mine and "- D-2026-001 (" not in mine and "- D-2026-003 (" in mine and "Handled with:" in mine.split("THE OTHER DEMANDS")[1]


def test_a_demand_with_no_link_is_alone_and_a_single_demand_is_a_request_of_one():
    e, cid, _ = _run(items=1)
    cells = {c["column"]: c for c in e.store.cells(cid, PID)}
    assert cells["Handled with"]["value"] == "Alone"
    assert e.store.request_cells(cid, PID)["Overview"]["value"] == OVERVIEW


def test_an_answer_or_a_resume_runs_the_request_text_when_it_should():
    e, cid, prompts = _run()
    n = sum(1 for name, _ in prompts if name == "Overview")
    # a resume keeps what was written
    e.run_phase(cid, PID, resume=True)
    assert sum(1 for name, _ in prompts if name == "Overview") == n
    # an answer to any property of the stage writes the derived and the request-wide properties again
    spec = e.store.get_case(cid)["spec"]
    stage = spec["stages"][1]
    assert {"Handled with", "Overview", "Justification"} <= eng.Engine._dependants(stage, "Security fit")
    e.run_phase(cid, PID, only_item="D-2026-001", only_cols=eng.Engine._dependants(stage, "Security fit"))
    assert sum(1 for name, _ in prompts if name == "Overview") == n + 1
    # and the one-item run still lets the property that compares see the other demands
    last = [p for name, p in prompts if name == "Consolidate with demand(s)"][-1] if any(name == "Consolidate with demand(s)" for name, _ in prompts) else ""
    assert last == "" or "demand_id: D-2026-001" not in last


def test_the_request_text_is_not_a_column_of_the_demands_and_is_in_the_export():
    e, cid, _ = _run()
    app = FastAPI()
    app.include_router(api.router)
    api.set_engine(e)
    c = TestClient(app)
    got = c.get(f"/api/cases/{cid}").json()
    cols = [x["name"] for x in got["phases"][1]["columns"]]
    assert "Overview" not in cols and "Handled with" in cols and "Justification" in cols
    steps = [s["label"] for s in got["phases"][1]["steps"]]
    assert steps[-1] == "Writing the overview"                                              # its own last step on the live card
    sheet = c.get(f"/api/cases/{cid}/export?phase={PID}")
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(sheet.content))
    assert wb.sheetnames[-1] == "Request" and [r[1].value for r in wb["Request"].iter_rows(min_row=2)] == [OVERVIEW]
    head = [x.value for x in next(wb[wb.sheetnames[0]].iter_rows(max_row=1))]
    assert "Overview" not in head and "Handled with" in head


def test_the_architects_own_words_for_a_derived_property_stay():
    e, cid, _ = _run()
    e.store.save_cell(cid, "D-2026-003", PID, "Handled with", value="Alone, I confirmed it", status="user", source="user")
    spec = e.store.get_case(cid)["spec"]
    e.run_phase(cid, PID, only_item="D-2026-001", only_cols={"Handled with"})
    cells = {(c["item_id"], c["column"]): c for c in e.store.cells(cid, PID)}
    assert cells[("D-2026-003", "Handled with")]["value"] == "Alone, I confirmed it"       # not written over
    assert cells[("D-2026-001", "Handled with")]["source"] == "rule"
    assert spec["stages"][1]["name"] == "Recommendation"


def test_each_demand_is_one_line_however_many_paragraphs_its_answers_have():
    e = Engine(CaseStore(), base.fake_tools, workers=1)
    cid = e.create(copy.deepcopy(base.SPEC), base.ITEMS[:2], "lines")
    e.store.save_cell(cid, "D-2026-003", "screening", "Domain", value="First paragraph.\n\nSecond paragraph.\n1. A step\n2. Another", status="answered", source="model")
    out = e._peers(cid, e.store.get_case(cid)["spec"], "recommendation", [{"_id": "D-2026-003", "title": "Second"}, {"_id": "D-2026-004", "title": "Third"}], ["Domain"])
    assert out.split("\n")[0] == "- D-2026-003 (Second): Domain: First paragraph. Second paragraph. 1. A step 2. Another"
    assert len(out.split("\n")) == 2 and out.split("\n")[1].startswith("- D-2026-004 (Third)")
