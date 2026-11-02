"""The second stage reads the first: its answers, the passages they cited, and the stage's own instructions.
A grade for the recommendation is worked out in code, never said by a model."""
import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.cases import gather as gmod  # noqa: E402
from eawiki.cases import grade, solve as smod  # noqa: E402
from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import CaseStore  # noqa: E402

SPEC = base.SPEC
REC = SPEC["stages"][1]
S1 = SPEC["stages"][0]["name"]            # the first stage, as the second stage names it
ID = "D-2026-001"


def _run(llm=None, calls=None, spec=SPEC, items=None):
    """Both stages over the sample sheet; every prompt the model got is kept, and so is every id the passages were fetched by."""
    prompts, fetched = [], []

    def recording(prompt):
        prompts.append(prompt)
        return (llm or base.fake_llm)(prompt)

    def tools():
        t = base.fake_tools()
        t.llm_json = recording
        orig = t.blocks_by_ids
        t.blocks_by_ids = lambda ids: (fetched.append(list(ids)), orig(ids))[1]
        return t

    e = Engine(CaseStore(), tools, workers=2)
    cid = e.create(spec, items or base.ITEMS[:1], "rec")
    e.run_phase(cid, "screening")
    e.approve(cid, "screening", background=False)
    return e, cid, prompts, fetched


def _prompt_for(prompts, stage_marker, prop):
    return [p for p in prompts if f"PROPERTY: {prop}  [" in p and stage_marker(p)]


def test_the_second_stage_sees_what_the_first_decided_and_its_own_instructions():
    e, cid, prompts, _ = _run()
    mine = _prompt_for(prompts, lambda p: True, "Recommended owner")
    assert len(mine) == 1
    p = mine[0]
    # the screening's answers, under an id the answer can cite
    assert f"[decided:{S1} / Demand type] {S1} / Demand type: Digital" in p
    assert f"[decided:{S1} / Mandate / business or DT objective]" in p
    # an answer the architect still owes is shown as unknown, and cannot be cited
    assert f"{S1} / Linked initiative or project: (unknown: asked the architect)" in p
    assert f"[decided:{S1} / Linked initiative or project]" not in p
    # the stage's instructions reach the property
    assert "INSTRUCTIONS FOR THIS STAGE" in p and "Do NOT recommend new business capabilities" in p
    # the first stage's prompts are unchanged: its instructions describe the gate, which the gate enforces in code
    first = _prompt_for(prompts, lambda p: "INSTRUCTIONS FOR THIS STAGE" not in p, "Demand type")
    assert first and not any(f"{S1} / " in x for x in first)


def test_the_passages_the_screening_cited_are_read_again_by_the_second_stage():
    e, cid, prompts, fetched = _run()
    # the screening cited Strategy:1 for the mandate; stage two fetches exactly that, by id
    assert ["Strategy:1"] in fetched
    cells = {c["column"]: c for c in e.store.cells(cid, "recommendation")}
    c = cells["Recommended owner"]
    assert any("the earlier stages' cited passages: 1 of 1 read again" in h for h in c["how"])
    assert any(h.startswith("Looked at:") and "passages cited by the earlier stages" in h for h in c["how"])
    assert "[Strategy:1]" in _prompt_for(prompts, lambda p: True, "Recommended owner")[0]


def test_an_earlier_answer_can_be_cited_and_an_unknown_one_cannot():
    e, cid, _, _ = _run()
    decided = e._decided(cid, "recommendation", ID, SPEC)
    assert decided[f"{S1} / Demand type"] == "Digital"
    assert decided[f"{S1} / Linked initiative or project"].startswith("(unknown")
    col = {"name": "Recommended owner", "type": "text"}
    ev = {"allowed": set(), "used": [], "searched": []}
    ok = smod.verify(col, {"value": "HR Systems Lead", "status": "answered", "evidence": [f"decided:{S1} / Demand type"]}, ev, decided)
    assert ok["status"] == "answered" and ok["evidence"] == [f"decided:{S1} / Demand type"]
    bad = smod.verify(col, {"value": "HR", "status": "answered", "evidence": [f"decided:{S1} / Linked initiative or project"]}, ev, decided)
    assert bad["status"] == "needs_input" and bad["evidence"] == []


def test_a_lookup_can_start_from_an_answer_of_the_earlier_stage():
    e, cid, _, _ = _run()
    vals = e._decided_values(cid, "recommendation", ID, SPEC)
    assert vals["Demand type"] == "Digital" and vals["Domain"] == ["Application", "Security"]
    # this stage's own property of the same name wins over an earlier one
    st = e.store
    st.save_cell(cid, ID, "recommendation", "Demand type", value="Own", status="answered", source="model")
    assert e._decided_values(cid, "recommendation", ID, SPEC)["Demand type"] == "Own"


def test_carried_passages_stand_in_the_merge_even_when_no_document_was_searched():
    spec = {**SPEC, "merge": True}
    plan = {"sources": ["demand"], "lookups": [], "documents": [], "queries": ["{__text__}"]}
    ev = gmod.gather(base.fake_tools(), plan, spec, base.ITEMS[0], [], {}, None, None, {}, {}, ["Strategy:1"])
    assert "Strategy:1" in ev["allowed"]
    assert "[Strategy:1]" in gmod.render(ev)
    assert any("1 of 1 read again" in x for x in ev["searched"])
    # more than can be brought forward are named, not read
    many = [f"Strategy:{i}" for i in range(1, 12)]
    ev2 = gmod.gather(base.fake_tools(), plan, spec, base.ITEMS[0], [], {}, None, None, {}, {}, many)
    assert any("only the first 8 are brought forward" in x for x in ev2["searched"]) or any("read again" in x for x in ev2["searched"])


# ---- the grade ------------------------------------------------------------------------------------------------------

def _cell(status="answered", evidence=()):
    return {"status": status, "evidence": list(evidence)}


def test_the_grade_follows_what_the_recommendation_rests_on():
    head = _cell(evidence=["Strategy:1"])
    rests = [("Screening / Domain", _cell(evidence=["Strategy:1"])), ("Overlaps with", _cell())]
    g = grade.grade(head, rests)
    assert g["level"] == "High" and g["why"][-1] == "Nothing it rests on is open."
    open_two = rests + [("Screening / Data classification", _cell("needs_input")), ("Security fit", _cell("needs_source"))]
    g = grade.grade(head, open_two)
    assert g["level"] == "Medium" and "2 things it rests on are not confirmed: Screening / Data classification, Security fit." in g["why"]
    # open cells and no source of its own: Low
    assert grade.grade(_cell(evidence=["decided:Screening / Domain"]), open_two)["level"] == "Low"
    # the headline itself undecided: Low, whatever else is known
    assert grade.grade(_cell("needs_input"), rests)["level"] == "Low"
    assert grade.grade(None, rests)["level"] == "Low"
    # nothing open but nothing from the knowledge base cited anywhere: not High
    assert grade.grade(_cell(evidence=["decided:x"]), [("a", _cell(evidence=["demand:need"]))])["level"] == "Medium"


def test_the_pick_list_must_hold_the_three_words():
    assert grade.scale({"values": ["high", "Medium", "LOW"]}) == {"High": "high", "Medium": "Medium", "Low": "LOW"}
    assert grade.scale({"values": ["High", "Low"]}) is None


def _answers(valid_recommendation):
    def llm(prompt):
        m = re.search(r"PROPERTY: (.+?)  \[", prompt)
        if m and m.group(1) == "Recommendation" and valid_recommendation:
            return {"value": "Enhancement", "status": "answered", "evidence": ["Strategy:1"], "needs": "", "note": "n"}
        return base.fake_llm(prompt)
    return llm


def test_confidence_is_graded_in_code_and_no_model_is_asked_for_it():
    e, cid, prompts, _ = _run(_answers(True))
    assert not [p for p in prompts if "PROPERTY: Confidence  [" in p]
    cells = {c["column"]: c for c in e.store.cells(cid, "recommendation")}
    conf = cells["Confidence"]
    assert conf["source"] == "rule" and conf["status"] == "answered"
    # the linked initiative is still owed by the architect, so the grade says Medium and names it
    assert conf["value"] == "Medium"
    assert any("Linked initiative or project" in h and S1 not in h for h in conf["how"])
    assert conf["how"][0].startswith("Graded in code")
    # the recommendation undecided: Low
    e2, cid2, _, _ = _run(_answers(False))
    c2 = {c["column"]: c for c in e2.store.cells(cid2, "recommendation")}["Confidence"]
    assert c2["value"] == "Low" and "not decided" in " ".join(c2["how"])


def test_a_grade_the_architect_typed_is_left_alone_and_a_bad_setting_is_stated():
    e, cid, _, _ = _run(_answers(True))
    st = e.store
    st.save_cell(cid, ID, "recommendation", "Confidence", value="High", status="user", source="user", how=["mine"])
    e._grades(cid, "recommendation", next(c for c in REC["output"]["columns"] if c["name"] == "Confidence"),
              [{"_id": ID}], e.store.get_case(cid)["spec"], REC)
    assert {c["column"]: c for c in st.cells(cid, "recommendation")}["Confidence"]["value"] == "High"
    # a pick list without the three words cannot be graded: the cell says why instead of guessing
    spec = copy.deepcopy(SPEC)
    col = next(c for c in spec["stages"][1]["output"]["columns"] if c["name"] == "Confidence")
    col["values"] = ["High", "Low"]
    e._grades(cid, "recommendation", dict(col), [{"_id": "D-2026-003"}], spec, spec["stages"][1])
    bad = {c["column"]: c for c in st.cells(cid, "recommendation") if c["item_id"] == "D-2026-003"}["Confidence"]
    assert bad["status"] == "needs_input" and "High, Medium and Low" in bad["need"]


# ---- the settings -----------------------------------------------------------------------------------------------------

def test_the_graded_setting_is_checked():
    spec = copy.deepcopy(SPEC)
    assert usecases.validate(spec) == []
    col = next(c for c in spec["stages"][1]["output"]["columns"] if c["name"] == "Confidence")
    assert col["graded"] is True
    col["values"] = ["High", "Low"]
    assert any("holding High, Medium and Low" in e for e in usecases.validate(spec))
    col["values"] = ["High", "Medium", "Low"]
    spec["stages"][1]["result"].pop("row_tag")
    assert any("needs a row tag" in e for e in usecases.validate(spec))
    spec["stages"][1]["result"]["row_tag"] = "Recommendation"
    col["graded"] = "yes"
    assert any("graded must be true or false" in e for e in usecases.validate(spec))
    # an empty box in the form leaves no key behind
    col["graded"] = False
    usecases._tidy_descriptions(spec)
    assert "graded" not in col


def test_a_lookup_may_start_from_a_property_of_an_earlier_stage():
    spec = copy.deepcopy(SPEC)
    col = next(c for c in spec["stages"][1]["output"]["columns"] if c["name"] == "Overlaps with")
    col["lookups"] = [{"find": "what each application is", "from": "result:Impacted application", "match": "name", "in": ["Application Catalog"]}]
    assert usecases.validate(spec) == []
    col["lookups"][0]["from"] = "result:No such property"
    assert any("not another column of this stage, or of an earlier one" in e for e in usecases.validate(spec))
    # a property of THIS stage still has to be listed under 'builds on', so it is decided first
    col["lookups"][0]["from"] = "result:Security fit"
    assert any("'builds on' list" in e for e in usecases.validate(spec))
