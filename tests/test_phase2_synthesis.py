"""The pieces a closing recommendation needs: a property that is shown what the earlier stage decided for the OTHER items, a
document that keeps the architect's findings apart from the message that is sent, and the checks that keep both settings honest."""
import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import pytest  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import CaseStore  # noqa: E402

SPEC = base.SPEC_P2


@pytest.fixture(autouse=True)
def _use_cases(monkeypatch):
    monkeypatch.setattr(usecases, "DIR", base.ROOT / "use_cases")


def _col(spec, stage, name):
    return next(c for c in spec["stages"][stage]["output"]["columns"] if c["name"] == name)


# ---- the settings are checked --------------------------------------------------------------------------------------

def test_a_property_may_only_be_shown_properties_of_earlier_stages():
    spec = copy.deepcopy(SPEC)
    _col(spec, 1, "Overlaps with")["sees_others"] = ["Is duplicate"]
    assert usecases.validate(spec) == []
    _col(spec, 1, "Overlaps with")["sees_others"] = ["Security fit"]                # a property of its own stage
    assert any("not a property of an earlier stage" in e for e in usecases.validate(spec))
    _col(spec, 1, "Overlaps with")["sees_others"] = "Is duplicate"                   # not a list
    assert any("must be a list" in e for e in usecases.validate(spec))
    _col(spec, 1, "Overlaps with")["sees_others"] = [f"p{i}" for i in range(usecases.MAX_SEES_OTHERS + 1)]
    assert any("at most" in e for e in usecases.validate(spec))
    first = copy.deepcopy(SPEC)
    _col(first, 0, "Domain")["sees_others"] = ["Urgency"]                            # the first stage has nothing before it
    assert any("not a property of an earlier stage" in e for e in usecases.validate(first))


def test_the_properties_kept_for_the_architect_must_be_properties_of_the_stage_other_than_the_headline():
    spec = copy.deepcopy(SPEC)
    doc = spec["stages"][1]["output"]["document"]
    doc["internal"] = ["Overlaps with", "Security fit"]
    assert usecases.validate(spec) == []
    doc["internal"] = ["Nope"]
    assert any("kept for the architect" in e for e in usecases.validate(spec))
    doc["internal"] = [doc["statement"]]
    assert any("kept for the architect" in e for e in usecases.validate(spec))
    doc["internal"] = []                                                              # an empty list leaves no key behind
    saved = copy.deepcopy(spec)
    usecases._tidy_descriptions(saved)
    assert "internal" not in saved["stages"][1]["output"]["document"]


# ---- the other demands' earlier answers reach the property that asks for them ----------------------------------------

def test_a_property_is_shown_what_the_earlier_stage_decided_for_the_other_demands_and_the_others_are_not():
    spec = copy.deepcopy(SPEC)
    _col(spec, 1, "Overlaps with")["sees_others"] = ["Is duplicate", "Domain"]
    prompts = []

    def tools():
        t = base.fake_tools()
        inner = t.llm_json

        def llm(prompt):
            prompts.append(prompt)
            return inner(prompt)
        t.llm_json = llm
        return t

    e = Engine(CaseStore(), tools, workers=2)
    cid = e.create(spec, base.ITEMS[:3], "peers")
    e.run_phase(cid, "screening")
    e.approve(cid, "screening", background=False)
    mine = [p for p in prompts if "PROPERTY: Overlaps with" in p]
    assert len(mine) == 3
    for p in mine:
        block = p.split("THE OTHER DEMANDS IN THIS REQUEST")[1].split("\n\n")[0]
        lines = re.findall(r"^- (D-2026-\d+) \(.*?\): (.*)$", block, re.M)
        assert len(lines) == 2 and all("Is duplicate:" in rest and "Domain:" in rest for _id, rest in lines)       # the other two, with the named answers
    assert not any("THE OTHER DEMANDS IN THIS REQUEST" in p for p in prompts if "PROPERTY: Security fit" in p)       # only a property that asked for them


def test_the_other_demands_are_capped_and_an_open_answer_says_so():
    e = Engine(CaseStore(), base.fake_tools, workers=1)
    spec = copy.deepcopy(SPEC)
    cid = e.create(spec, base.ITEMS[:2], "caps")
    st = e.store
    st.save_cell(cid, "D-2026-003", "screening", "Is duplicate", value="", status="needs_input", source="model")
    st.save_cell(cid, "D-2026-003", "screening", "Domain", value=["Application"], status="answered", source="model")
    others = [{"_id": "D-2026-003", "title": "Second"}]
    text = e._peers(cid, st.get_case(cid)["spec"], "recommendation", others, ["Is duplicate", "Domain", "Not a property"])
    assert text == "- D-2026-003 (Second): Is duplicate: (not decided); Domain: Application"
    many = [{"_id": f"X-{i}", "title": ""} for i in range(e.MAX_PEERS + 5)]
    out = e._peers(cid, st.get_case(cid)["spec"], "recommendation", many, ["Domain"])
    assert out.count("\n") == e.MAX_PEERS and out.endswith("- and 5 more, not shown")
    assert e._peers(cid, st.get_case(cid)["spec"], "recommendation", [], ["Domain"]) == "" and e._peers(cid, st.get_case(cid)["spec"], "recommendation", others, []) == ""


# ---- the message and the architect's part of the draft ---------------------------------------------------------------

from eawiki.cases import document  # noqa: E402


def _cell(value, status="answered", need=""):
    return {"value": value, "status": status, "need": need, "evidence": []}


def _stage_with(internal):
    stage = copy.deepcopy(SPEC["stages"][1])
    stage["output"]["document"] = {"statement": "Recommended action", "facts": ["Recommended owner"], **({"internal": internal} if internal is not None else {})}
    return stage


CELLS = {"Recommendation": _cell("Enhancement"), "Recommended action": _cell("Extend the existing link."), "Recommended owner": _cell("HR Lead"),
         "Overlaps with": _cell(["HR Portal"]), "Security fit": _cell("", "needs_input", "Which controls apply?"), "Contract / licence match": _cell("None found"),
         "Justification": _cell("It exists."), "Evidence": _cell(["Applications:3"])}


def test_the_architects_findings_are_kept_after_the_message_and_marked():
    d = document.compose(SPEC, _stage_with(["Overlaps with", "Contract / licence match"]), {"_id": "D-1", "title": "T"}, CELLS)
    titles = [(x["title"], bool(x.get("internal"))) for x in d["sections"]]
    # the message's own sections first, then the architect's, in the use case's order; what is open and the sources are the architect's too
    assert titles == [("Justification", False), ("Overlaps with", True), ("Contract / licence match", True), (document.TO_CONFIRM, True), (document.EVIDENCE, True)]
    # without the setting nothing changes: every section is part of the one document
    plain = document.compose(SPEC, _stage_with(None), {"_id": "D-1", "title": "T"}, CELLS)
    assert not any(x.get("internal") for x in plain["sections"]) and [x["title"] for x in plain["sections"]][:3] == ["Overlaps with", "Contract / licence match", "Justification"]


def test_an_edit_keeps_what_is_for_the_architect_and_the_download_leaves_it_out():
    d = document.compose(SPEC, _stage_with(["Overlaps with"]), {"_id": "D-1", "title": "T"}, CELLS)
    again = document.clean(d)
    assert [bool(x.get("internal")) for x in again["sections"]] == [bool(x.get("internal")) for x in d["sections"]] and any(x.get("internal") for x in again["sections"])
    forged = document.clean({"title": "T", "rec": {}, "sections": [{"title": "A", "body": "b", "internal": "yes"}, {"title": "B", "body": "c", "internal": True}]})
    assert [bool(x.get("internal")) for x in forged["sections"]] == [False, True]            # only a real true counts
    page = document.render_html({"doc": d, "status": "draft"})
    assert "Extend the existing link." in page and "It exists." in page
    assert "HR Portal" not in page and "Which controls apply?" not in page and "Applications:3" not in page and "To confirm" not in page
    full = document.render_html({"doc": d, "status": "draft"}, include_internal=True)
    assert "HR Portal" in full and "Applications:3" in full
