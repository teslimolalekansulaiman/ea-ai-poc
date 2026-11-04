"""The Demand use case's second stage as it ships: the message to the requester is the last property, written from everything
before it, and the draft keeps the architect's findings apart from it. These tests read the shipped file, not a fixture, so a change
to its design is a change to a test."""
import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import pytest  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.cases import document, engine as eng  # noqa: E402
from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import CaseStore  # noqa: E402

SPEC = base.SPEC                                   # the shipped use case
REC = SPEC["stages"][1]
COLS = {c["name"]: c for c in REC["output"]["columns"]}
FINDINGS = ["Overlaps with", "Consolidate with demand(s)", "Contract / licence match", "Security fit"]
MESSAGE = "Please do not raise a new demand. We recommend extending the existing link.\n\nWhat you asked for\nA way to send results.\n\nNext steps\n1. The owner confirms."


@pytest.fixture(autouse=True)
def _use_cases(monkeypatch):
    monkeypatch.setattr(usecases, "DIR", base.ROOT / "use_cases")


def test_the_shipped_stage_is_valid_and_is_the_design_that_was_agreed():
    assert usecases.validate(SPEC) == []
    assert REC["summary_columns"] == ["Recommendation"] and REC["result"]["row_tag"] == "Recommendation type"
    assert [c["name"] for c in REC["output"]["columns"]] == ["Recommendation type", *FINDINGS[:1], "Consolidate with demand(s)", "Contract / licence match",
                                                              "Security fit", "Recommended owner", "Risks and conditions", "Next steps", "Recommendation",
                                                              "Confidence", "Evidence"]
    assert "Recommended action" not in COLS and "Justification" not in COLS              # they became paragraphs of the message
    msg = COLS["Recommendation"]
    assert msg["type"] == "text" and msg["evidence_required"] is False
    assert set(msg["uses"]) == {"Overlaps with", "Consolidate with demand(s)", "Contract / licence match", "Security fit", "Recommendation type",
                                "Recommended owner", "Risks and conditions", "Next steps"}                  # every other property of the stage
    text = msg["how_to_resolve"]
    for must in ("senior enterprise architect", "to the requester", "about 300 words", "roles, never personal names", "Do not state a grade"):
        assert must.lower() in text.lower()
    assert REC["output"]["document"] == {"statement": "Recommendation", "facts": ["Recommended owner"],
                                         "internal": [*FINDINGS, "Risks and conditions", "Next steps"]}
    assert COLS["Consolidate with demand(s)"]["sees_others"] == ["Is duplicate", "Duplicate demand number (in the sheet)", "Impacted application", "Impacted business capability"]


def test_the_message_is_written_last_and_from_everything_before_it():
    order, seen = [], {}

    def llm(prompt):
        m = re.search(r"PROPERTY: (.+?)  \[", prompt)
        name = m.group(1) if m else ""
        if name in COLS and "INSTRUCTIONS FOR THIS STAGE" in prompt:
            order.append(name)
            seen[name] = prompt
            canned = {"Recommendation type": "Enhancement", "Recommendation": MESSAGE, "Risks and conditions": ["Security fit not confirmed"],
                      "Next steps": ["The owner confirms the status"], "Overlaps with": ["HR Portal"], "Consolidate with demand(s)": ["None"],
                      "Contract / licence match": "None found", "Security fit": "Open", "Recommended owner": "HR Systems Lead"}
            if name in canned:
                return {"value": canned[name], "status": "answered", "evidence": re.findall(r"\[([^\]\s]+:\d+)\]", prompt)[:1], "needs": "", "note": "n"}
        return base.fake_llm(prompt)

    def tools():
        t = base.fake_tools()
        t.llm_json = llm
        return t

    e = Engine(CaseStore(), tools, workers=2)
    cid = e.create(SPEC, base.ITEMS[:2], "shipped")
    e.run_phase(cid, "screening")
    e.approve(cid, "screening", background=False)
    first = {n: order.index(n) for n in order}
    # the message is solved after every other property it builds on, once per demand
    assert order.count("Recommendation") == 2
    last_other = max(i for i, n in enumerate(order) if n != "Recommendation")
    assert min(i for i, n in enumerate(order) if n == "Recommendation") > last_other, first
    # ...and in the order the dependencies set: findings, then the type and owner, then risks, then the steps
    assert max(order.index(n) for n in FINDINGS) < min(order.index("Recommendation type"), order.index("Recommended owner")) \
        < order.index("Risks and conditions") < order.index("Next steps")
    p = seen["Recommendation"]
    assert "senior enterprise architect" in p
    assert "Recommendation type: Enhancement" in p and "Risks and conditions: Security fit not confirmed" in p and "Next steps: The owner confirms the status" in p
    assert "Recommended owner: HR Systems Lead" in p and re.search(r"Screening & Impact Assessment / Demand type: ", p)            # this phase, and the screening
    # a property that compares with the rest was shown the other demands; the message was not
    assert "THE OTHER DEMANDS IN THIS REQUEST" in seen["Consolidate with demand(s)"] and "THE OTHER DEMANDS IN THIS REQUEST" not in p
    assert re.search(r"^- D-2026-\d+ \(.*?\): Is duplicate: ", seen["Consolidate with demand(s)"].split("THE OTHER DEMANDS IN THIS REQUEST")[1], re.M)


def test_the_draft_is_the_message_with_the_findings_kept_apart_and_left_out_of_the_download():
    def llm(prompt):
        m = re.search(r"PROPERTY: (.+?)  \[", prompt)
        canned = {"Recommendation": MESSAGE, "Recommendation type": "Enhancement", "Recommended owner": "HR Systems Lead"}
        if m and m.group(1) in canned and "INSTRUCTIONS FOR THIS STAGE" in prompt:
            return {"value": canned[m.group(1)], "status": "answered", "evidence": re.findall(r"\[([^\]\s]+:\d+)\]", prompt)[:1], "needs": "", "note": "n"}
        return base.fake_llm(prompt)

    def tools():
        t = base.fake_tools()
        t.llm_json = llm
        return t

    e = Engine(CaseStore(), tools, workers=2)
    cid = e.create(copy.deepcopy(SPEC), base.ITEMS[:1], "draft")
    e.run_phase(cid, "screening")
    e.approve(cid, "screening", background=False)
    case = e.store.get_case(cid)
    d = document.listing(e.store, case, "recommendation")[0]["doc"]
    assert d["rec"]["body"] == MESSAGE and d["rec"]["column"] == "Recommendation"
    kinds = {s["title"]: bool(s.get("internal")) for s in d["sections"]}
    assert all(kinds[t] for t in FINDINGS if t in kinds) and kinds.get("Risks and conditions") and kinds.get("Next steps")
    assert [f["label"] for f in d["facts"]][:1] == ["Recommendation type"] and "Recommended owner" in [f["label"] for f in d["facts"]]
    assert "Confidence" not in kinds                                                      # graded in code, for the table
    page = document.render_html({"doc": d, "status": "draft"})
    assert "Please do not raise a new demand" in page                                       # the message is what is downloaded
    assert all(t not in page for t in [*FINDINGS, "Risks and conditions", document.TO_CONFIRM, document.EVIDENCE])


def test_answering_a_property_of_the_stage_writes_the_message_again():
    stage = REC
    assert "Recommendation" in eng.Engine._dependants(stage, "Security fit")             # the engine reruns the summary after any answer in the stage
    assert {"Recommendation type", "Risks and conditions", "Next steps", "Recommendation"} <= eng.Engine._dependants(stage, "Overlaps with")
