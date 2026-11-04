"""Drafting the questions a property needs put to the knowledge base: the model proposes, code checks every choice, the owner decides. And the
runtime planner, which may now start a search from the answer of a property decided before it."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.api import cases as cases_api  # noqa: E402
from eawiki.api.app import app  # noqa: E402
from eawiki.cases import lookupdraft as ld  # noqa: E402
from eawiki.cases import plan as pmod  # noqa: E402
from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import CaseStore  # noqa: E402

SPEC = base.SPEC_P2
DOCS = ["Application Catalog", "Contract Register", "Strategy", "Security Control Catalog"]


@pytest.fixture(autouse=True)
def _use_cases(monkeypatch):
    monkeypatch.setattr(usecases, "DIR", base.ROOT / "use_cases")


def _at(name, stage=1):
    cols = SPEC["stages"][stage]["output"]["columns"]
    return next(i for i, c in enumerate(cols) if c["name"] == name)


def _col(name, **over):
    c = copy.deepcopy(SPEC["stages"][1]["output"]["columns"][_at(name)])
    c.update(over)
    return c


# ---- where a search may start --------------------------------------------------------------------------------------

def test_a_property_may_start_from_every_earlier_answer_and_from_those_of_its_stage_that_do_not_build_on_it():
    menu = ld.starts(SPEC, 1, _at("Contract / licence match"))
    first = [c["name"] for c in SPEC["stages"][0]["output"]["columns"] if c["type"] != "citations"]
    assert all(n in menu for n in first)                                                 # every property of the stage before
    assert "Overlaps with" in menu and "Security fit" in menu                           # its own stage's, when they do not build on it
    assert "Contract / licence match" not in menu                                        # never itself
    assert "Recommended action" not in menu and "Justification" not in menu            # they build on it (through "uses"): a loop
    assert "Evidence" not in menu                                                         # a list of sources is not an answer to start from
    assert "Recommended owner" in ld.starts(SPEC, 1, _at("Security fit"))                                   # it builds only on "Overlaps with"
    assert "Recommended owner" not in ld.starts(SPEC, 1, _at("Overlaps with"))                              # it builds on this one: a loop
    assert "Overlaps with" in ld.starts(SPEC, 1, _at("Recommended owner"))                                  # what it builds on is, of course, a start


def test_the_first_stage_has_nothing_before_it_and_a_request_wide_property_is_not_a_start():
    first = ld.starts(SPEC, 0, _at("Domain", 0))
    assert "Urgency" in first and "Domain" not in first and not any(n in first for n in ("Recommendation", "Overlaps with"))
    spec = copy.deepcopy(SPEC)
    spec["stages"][1]["output"]["columns"].append({"name": "Overview", "type": "text", "scope": "request"})
    assert "Overview" not in ld.starts(spec, 1, _at("Overlaps with"))


# ---- what is kept of the model's draft ----------------------------------------------------------------------------

def _clean(lookups, col=None, have=()):
    col = col or _col("Contract / licence match")
    return ld.clean({"lookups": lookups}, col, DOCS, ld.starts(SPEC, 1, _at(col["name"])), {c["name"] for c in SPEC["stages"][1]["output"]["columns"]}, list(have))


def test_a_good_question_is_kept_and_says_what_it_must_build_on():
    out, notes = _clean([{"find": "which contract covers each overlapping solution", "from": "result:Overlaps with", "match": "name", "in": ["Contract Register"],
                          "types": ["application", "bogus"], "extract": "the contract and its end date", "why": "the contract depends on what overlaps"}])
    assert notes == [] and out == [{"find": "which contract covers each overlapping solution", "from": "result:Overlaps with", "match": "name",
                                    "in": ["Contract Register"], "types": ["application"], "extract": "the contract and its end date",
                                    "why": "the contract depends on what overlaps", "needs_uses": "Overlaps with"}]        # the property must build on it, so it is decided first
    done, _ = _clean([{"find": "x", "from": "result:Overlaps with", "match": "name"}], _col("Contract / licence match", uses=["Overlaps with"]))
    assert "needs_uses" not in done[0]
    earlier, _ = _clean([{"find": "x", "from": "result:Impacted application", "match": "name"}])                       # an earlier stage needs no "builds on"
    assert "needs_uses" not in earlier[0]


def test_what_cannot_be_used_is_left_out_and_said():
    out, notes = _clean([
        {"find": "from a property that builds on this one", "from": "result:Recommended action", "match": "name"},
        {"find": "from a property that does not exist", "from": "result:Nonsense", "match": "name"},
        {"find": "compare, but not with the other demands", "from": "need", "match": "compare"},
        {"find": "other demands, but matched by name", "from": "other_demands", "match": "name"},
        {"find": "no start", "match": "name"},
        "not even an object",
        {"find": "kept, but one place is not a document here", "from": "need", "match": "meaning", "in": ["Strategy", "Imaginary Register"]}])
    assert [o["find"] for o in out] == ["kept, but one place is not a document here"] and out[0]["in"] == ["Strategy"]
    assert len(notes) == 7                                                                   # one for each thing left out, and the lost place
    text = " ".join(notes)
    assert text.count("is not decided before this property") == 2 and "builds on this one" in text and "from a property that does not exist" in text
    assert text.count("compares with other demands only when it starts from them") == 2 and "“no start”" in text and "Imaginary Register" in text


def test_a_repeat_and_anything_past_the_limit_is_dropped_and_a_comparison_goes_with_the_other_demands():
    have = ["Which contract covers each overlapping solution?"]
    out, _ = _clean([{"find": "which contract covers each overlapping solution", "from": "need", "match": "meaning"},        # the same, in other words and case
                     {"find": "who is it with", "from": "other_demands", "match": "compare"}] +
                    [{"find": f"question {i}", "from": "need", "match": "meaning"} for i in range(10)], have=have)
    assert [o["find"] for o in out][:2] == ["who is it with", "question 0"] and len(out) + len(have) == usecases.MAX_LOOKUPS


# ---- the draft as a whole -----------------------------------------------------------------------------------------

GOOD = {"lookups": [{"find": "who owns each overlapping solution", "from": "result:Overlaps with", "match": "name", "in": ["Application Catalog"], "types": ["application"],
                     "extract": "the owner role", "why": "the owner of what already exists"},
                    {"find": "what the need corresponds to", "from": "need", "match": "meaning", "in": ["Strategy"]}]}


def _draft(raw, col=None, **kw):
    col = col or _col("Recommended owner", uses=[])
    return ld.draft(col, SPEC, 1, _at(col["name"]), DOCS, (lambda p: raw) if not callable(raw) else raw, **kw)


def test_no_model_or_no_answer_is_not_a_finding_that_no_question_is_needed():
    assert ld.draft(_col("Recommended owner"), SPEC, 1, _at("Recommended owner"), DOCS, None)["status"] == "unavailable"
    assert _draft(None)["status"] == "unavailable"
    boom = ld.draft(_col("Recommended owner"), SPEC, 1, _at("Recommended owner"), DOCS, lambda p: 1 / 0)
    assert boom["status"] == "unavailable" and boom["lookups"] == [] and "not \"no question needed\"" in boom["notes"][0]
    none = _draft({"lookups": []})
    assert none["status"] == "none" and "decided from the demand or from earlier answers" in none["notes"][0]


def test_the_prompt_gives_the_properties_text_the_documents_and_where_a_search_may_start():
    seen = []
    _draft(lambda p: (seen.append(p), GOOD)[1], _col("Recommended owner", uses=["Overlaps with"], where_to_look="• Application Catalog: the owner role of each application"))
    p = seen[0]
    assert "PROPERTY: Recommended owner" in p and "WHERE THE OWNER SAYS TO LOOK: • Application Catalog" in p
    assert "The ingested documents: Application Catalog, Contract Register, Strategy, Security Control Catalog" in p
    assert "The properties you may start from:" in p and "Overlaps with" in p.split("The properties you may start from:")[1].split("\n")[0]
    assert "Recommended owner" not in p.split("The properties you may start from:")[1].split("\n")[0]
    assert "Recommended owner" not in p.split("The properties you may start from:")[1].split("\n")[0] and "Justification" in p.split("The properties you may start from:")[1].split("\n")[0]


EDGES = [{"key": "is_owned_by", "name": "is owned by", "definition": "x", "source_types": ["application"], "target_types": ["role"]},
         {"key": "supports", "name": "supports", "definition": "y", "source_types": ["application"], "target_types": ["process"]}]


def test_graph_relationships_are_drafted_for_a_name_match_and_kept_only_where_the_graph_holds_edges():
    counts = {"edges": 9, "relations": {"is_owned_by": {"total": 5, "out": {"application": 5}, "in": {}}, "supports": {"total": 0, "out": {}, "in": {}}}}
    asked = []

    def text(p):
        asked.append(p)
        return "is_owned_by | out | the owner is recorded as a link\nsupports | out | a link to what it supports"
    out = _draft(GOOD, edge_types=EDGES, counts=counts, llm_text=text)
    names, meaning = out["lookups"]
    assert names["relations"] == [{"relation": "is_owned_by", "direction": "out"}] and "5 edges" in names["relations_why"][0]       # "supports" holds none here: left out
    assert "relations" not in meaning and len(asked) == 1                                                                           # a meaning match reads no graph
    no_graph = _draft(GOOD, edge_types=EDGES, counts={"edges": 0, "relations": {}}, llm_text=text)
    assert all("relations" not in d for d in no_graph["lookups"]) and "No graph is loaded" in " ".join(no_graph["notes"])
    down = _draft(GOOD, edge_types=EDGES, counts=counts, llm_text=lambda p: 1 / 0)
    assert down["status"] == "ok" and all("relations" not in d for d in down["lookups"])                                          # the questions still stand


def test_a_property_with_all_its_questions_is_told_so():
    full = _col("Recommended owner", lookups=[{"find": f"q{i}", "from": "need", "match": "meaning"} for i in range(usecases.MAX_LOOKUPS)])
    out = _draft(GOOD, full)
    assert out["status"] == "none" and "most questions allowed" in out["notes"][0]


# ---- the route -----------------------------------------------------------------------------------------------------

def test_the_route_drafts_for_the_property_as_the_editor_holds_it_and_refuses_what_it_cannot_draft(monkeypatch):
    prompts = []

    def tools():
        t = base.fake_tools()
        t.llm_json = lambda p: (prompts.append(p), GOOD)[1]
        t.doc_ids = lambda: DOCS
        return t
    engine = Engine(CaseStore(), tools, workers=1)
    monkeypatch.setattr(cases_api, "get_engine", lambda: engine)       # two other tests leave get_engine replaced for good: say which engine this one means
    c = TestClient(app)
    spec = copy.deepcopy(SPEC)
    edited = spec["stages"][1]["output"]["columns"][_at("Recommended owner")]
    edited["description"] = "AN UNSAVED DESCRIPTION"
    edited.pop("uses", None)
    edited.pop("lookups", None)                                                    # other tests share this fixture
    ok = c.post("/api/usecases/draft-lookups", json={"use_case": spec, "stage": 1, "column": _at("Recommended owner")}).json()
    assert ok["status"] == "ok" and [d["find"] for d in ok["lookups"]] == ["who owns each overlapping solution", "what the need corresponds to"]
    assert ok["lookups"][0]["needs_uses"] == "Overlaps with" and "AN UNSAVED DESCRIPTION" in prompts[0]          # what is on the screen, saved or not
    for bad in ({}, {"use_case": spec, "stage": 9, "column": 0}, {"use_case": spec, "stage": 1, "column": 99}, {"use_case": "no", "stage": 0, "column": 0}):
        assert c.post("/api/usecases/draft-lookups", json=bad).status_code == 400
    spec["stages"][1]["output"]["columns"][0]["name"] = ""
    assert c.post("/api/usecases/draft-lookups", json={"use_case": spec, "stage": 1, "column": 0}).status_code == 400


# ---- the runtime planner ------------------------------------------------------------------------------------------

def test_the_planner_is_told_it_may_start_from_an_earlier_answer_and_a_start_it_may_not_use_is_dropped():
    seen = []
    plan_answer = {"sources": ["demand", "documents"], "lookups": [
        {"find": "who owns each overlapping solution", "from": "result:Overlaps with", "match": "name", "in": ["Application Catalog"]},
        {"find": "from something decided later", "from": "result:Recommended action", "match": "name"},
        {"find": "from the need", "from": "need", "match": "meaning"}]}
    col = {"name": "Recommended owner", "type": "text", "description": "d", "how_to_resolve": "h"}
    plan = pmod.build_plan(col, ["title"], DOCS, lambda p: (seen.append(p), plan_answer)[1], {}, results=["Impacted application", "Overlaps with"])
    assert "The properties you may start from: Impacted application; Overlaps with" in seen[0]
    assert [l["find"] for l in plan["lookups"]] == ["who owns each overlapping solution", "from the need"] and plan["origin"] == "model"
    seen.clear()
    pmod.build_plan(col, ["title"], DOCS, lambda p: (seen.append(p), None)[1], {})
    assert "may start from" not in seen[0] and "result:<property>" not in seen[0]                                      # nothing decided before: nothing offered


def test_a_plan_is_made_again_when_what_it_may_start_from_changes():
    cache, calls = {}, []
    col = {"name": "P", "type": "text", "description": "d"}
    llm = lambda p: (calls.append(1), {"sources": ["demand"], "lookups": []})[1]
    pmod.build_plan(col, [], DOCS, llm, cache, results=["A"])
    pmod.build_plan(col, [], DOCS, llm, cache, results=["A"])
    assert len(calls) == 1
    pmod.build_plan(col, [], DOCS, llm, cache, results=["A", "B"])
    assert len(calls) == 2


# ---- the whole stage ----------------------------------------------------------------------------------------------------

def _stage_spec():
    spec = copy.deepcopy(SPEC)
    cols = spec["stages"][1]["output"]["columns"]
    for c in cols:
        c.pop("lookups", None)
        if c["name"] in ("Overlaps with", "Contract / licence match", "Security fit"):
            c.pop("uses", None)
    by = {c["name"]: c for c in cols}
    by["Security fit"]["lookups"] = [{"find": "my own", "from": "need", "match": "meaning", "in": []}]            # has questions already
    by["Recommended owner"]["how_to_resolve"] = "Take the role from the answer of Overlaps with, and say so when Security fit is open."    # names two
    cols.append({"name": "Worked out", "type": "text", "derive": {"kind": "groups", "from": "Consolidate with demand(s)", "lead_by": "date_submitted"}})
    cols.append({"name": "Whole request", "type": "text", "scope": "request"})
    return spec


def _by_name(raw_by_name):
    def llm(p):
        name = p.split("PROPERTY: ", 1)[1].split("  [", 1)[0]
        return {"lookups": raw_by_name.get(name, [])}
    return llm


def _q(find, frm, match="name", kinds=("Application Catalog",)):
    return {"find": find, "from": frm, "match": match, "in": list(kinds), "why": "w"}


def test_a_stage_is_drafted_for_the_properties_that_have_no_questions_and_the_others_are_named_with_a_reason():
    spec = _stage_spec()
    got = ld.draft_stage(spec, 1, DOCS, _by_name({"Overlaps with": [_q("what overlaps", "result:Impacted application")],
                                                  "Contract / licence match": [_q("which contract covers it", "result:Overlaps with", kinds=("Contract Register",))]}))
    names = [p["name"] for p in got["properties"]]
    assert "Security fit" not in names and "Worked out" not in names and "Whole request" not in names and "Evidence" not in names
    skipped = {s["name"]: s["reason"] for s in got["skipped"]}
    assert "already has questions" in skipped["Security fit"] and "in code" in skipped["Worked out"] and "once for the whole request" in skipped["Whole request"]
    assert "Evidence" not in skipped                                                                   # a list of sources is not a property to look anything up for
    by = {p["name"]: p for p in got["properties"]}
    assert [d["find"] for d in by["Overlaps with"]["lookups"]] == ["what overlaps"] and by["Overlaps with"]["status"] == "ok"
    assert by["Contract / licence match"]["lookups"][0]["needs_uses"] == "Overlaps with"
    assert by["Recommended action"]["status"] == "none" and by["Recommended action"]["lookups"] == []      # a real answer: nothing to look up
    assert [p["name"] for p in got["properties"]].index("Overlaps with") < [p["name"] for p in got["properties"]].index("Contract / licence match")


def test_two_properties_that_would_each_build_on_the_other_cannot_both_keep_the_question():
    spec = _stage_spec()
    spec["stages"][1]["output"]["columns"] = [c for c in spec["stages"][1]["output"]["columns"] if c["name"] != "Security fit"]
    spec["stages"][1]["output"]["columns"].append({"name": "Security fit", "type": "text"})
    got = ld.draft_stage(spec, 1, DOCS, _by_name({"Overlaps with": [_q("what is secure", "result:Security fit")],
                                                  "Security fit": [_q("what overlaps, for security", "result:Overlaps with")]}))
    by = {p["name"]: p for p in got["properties"]}
    firstname = "Overlaps with"                                                                       # decided first (by the order they are decided, then as listed)
    assert [d["find"] for d in by[firstname]["lookups"]] == ["what is secure"]
    assert by["Security fit"]["lookups"] == [] and "already builds on this property" in " ".join(by["Security fit"]["notes"])


def test_a_property_whose_wording_names_another_is_offered_to_build_on_it_and_only_as_written():
    spec = _stage_spec()
    for c in spec["stages"][1]["output"]["columns"]:
        if c["name"] == "Security fit":
            c.pop("lookups")
    got = ld.draft_stage(spec, 1, DOCS, _by_name({}))
    owner = next(p for p in got["properties"] if p["name"] == "Recommended owner")
    assert [u["name"] for u in owner["uses_text"]] == ["Security fit"]                                  # it already builds on Overlaps with
    assert "names 'Security fit'" in owner["uses_text"][0]["why"]
    assert ld._mentions({"description": "the overlaps with answer"}, "Overlaps with") is False           # not as written: left to the owner
    assert ld._mentions({"how_to_resolve": "Use Overlaps with."}, "Overlaps with") is True
    assert ld._mentions({"how_to_resolve": "Use Overlaps within."}, "Overlaps with") is False            # a whole phrase


def test_the_stage_route_drafts_for_the_stage_as_the_editor_holds_it(monkeypatch):
    def tools():
        t = base.fake_tools()
        t.llm_json = _by_name({"Overlaps with": [_q("what overlaps", "result:Impacted application")]})
        t.doc_ids = lambda: DOCS
        return t
    engine = Engine(CaseStore(), tools, workers=1)
    monkeypatch.setattr(cases_api, "get_engine", lambda: engine)
    c = TestClient(app)
    got = c.post("/api/usecases/draft-stage-lookups", json={"use_case": _stage_spec(), "stage": 1}).json()
    assert [d["find"] for d in next(p for p in got["properties"] if p["name"] == "Overlaps with")["lookups"]] == ["what overlaps"] and got["skipped"]
    for bad in ({}, {"use_case": _stage_spec(), "stage": 9}, {"use_case": "no", "stage": 0}):
        assert c.post("/api/usecases/draft-stage-lookups", json=bad).status_code == 400


def test_every_drafted_question_says_what_became_of_the_graph():
    counts = {"edges": 9, "relations": {"is_owned_by": {"total": 5, "out": {"application": 5}, "in": {}}, "supports": {"total": 0, "out": {}, "in": {}}}}
    by = lambda out: {d["find"]: d for d in out["lookups"]}
    # a meaning match is never read through the graph, and says so
    got = by(_draft(GOOD, edge_types=EDGES, counts=counts, llm_text=lambda p: "none"))
    assert "Not read" in got["what the need corresponds to"]["graph_note"]
    # the model judged no relationship needed: a stated answer, not a silence
    assert "No relationship judged needed" in got["who owns each overlapping solution"]["graph_note"]
    # suggested, but the graph holds no edges of them
    only_supports = by(_draft(GOOD, edge_types=EDGES, counts=counts, llm_text=lambda p: "supports | out | a link to what it supports"))
    assert "holds no edges" in only_supports["who owns each overlapping solution"]["graph_note"] and "supports (out)" in only_supports["who owns each overlapping solution"]["graph_note"]
    assert "relations" not in only_supports["who owns each overlapping solution"]
    # the model did not answer for the relationships: said, with the way to try again
    down = by(_draft(GOOD, edge_types=EDGES, counts=counts, llm_text=lambda p: 1 / 0))
    assert "did not answer" in down["who owns each overlapping solution"]["graph_note"]
    # a graph that cannot be read here: said once, and on each name question
    nothing = _draft(GOOD)
    assert "could not be read here" in " ".join(nothing["notes"]) and "could not be read" in by(nothing)["who owns each overlapping solution"]["graph_note"]
    # where relationships are kept there is no note to contradict them
    kept = by(_draft(GOOD, edge_types=EDGES, counts=counts, llm_text=lambda p: "is_owned_by | out | recorded as a link"))
    assert "graph_note" not in kept["who owns each overlapping solution"] and kept["who owns each overlapping solution"]["relations"]
