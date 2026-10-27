"""The owner's closing points on how to read what was retrieved ('collate'): stored per property, validated, put in the prompt."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eawiki import usecases  # noqa: E402
from eawiki.cases import plan as pmod  # noqa: E402
from eawiki.cases import solve as smod  # noqa: E402

SPEC = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))
COLS = {c["name"]: c for st in SPEC["stages"] for c in st["output"]["columns"]}
EV = {"demand": {}, "blocks": [], "graph": None, "others": [], "allowed": set(), "used": [], "hint": None, "lookups": [], "searched": [], "wiki": []}


def test_the_production_use_case_carries_the_owners_points_for_the_properties_that_have_a_column():
    assert usecases.validate(SPEC) == []
    assert COLS["Domain"]["collate"].startswith("4. Add Security when the data is Confidential or Restricted") and COLS["Domain"]["uses"] == ["Data classification"]
    assert "Never link by department alone" in COLS["Impacted application"]["collate"] and COLS["Impacted application"]["collate"].count("\n1. Read") == 1
    assert "observation column" not in COLS["Impacted application"]["collate"] and "In your note" in COLS["Impacted application"]["collate"]
    assert "NORA framework" in COLS["Linked security capability"]["collate"] and COLS["Linked security capability"]["uses"] == ["Demand type"]
    assert "People demand: the answer is Not applicable" in COLS["Linked security capability"]["collate"]
    d = COLS["Domain"]
    assert d["rules"].startswith("Valid domains and what each covers (exactly five):") and d["rules"].count("\n• ") == 5
    assert d["values"] == ["Business", "Data", "Application", "Technology", "Security"]           # the five the rules list: the code enforces them
    assert "Pick list" not in COLS["Data classification"]["collate"]                           # the column's own values enforce the pick list
    assert "collate" not in COLS["Duplicate with existing artefact / artefact name"]            # held back: the text given is about duplicate demands


def test_everything_the_owner_gave_is_loaded_where_it_belongs():
    same = "Two demands are the same when they ask for the same outcome"
    assert COLS["Is duplicate"]["collate"].startswith(same) and "Use the ID format only" not in COLS["Is duplicate"]["collate"]
    assert COLS["Duplicate demand number (in the sheet)"]["collate"].endswith("Do not write titles or names here.")
    assert COLS["Domain"]["how_to_resolve"].startswith("1. Read the business need") and COLS["Domain"]["how_to_resolve"].rstrip().endswith("clearly needs them.")
    o = COLS["Owners"]
    assert o["uses"] == ["Impacted application", "Linked security capability"] and o["type"] == "list"
    assert "the platform owner decides on the platform" in o["rules"] and "The application owner decides on the application." in o["rules"]
    assert [l["from"] for l in o["lookups"]] == ["result:Impacted application", "systems", "data", "result:Linked security capability"]
    names = [c["name"] for st in SPEC["stages"] for c in st["output"]["columns"]]
    assert names.index("Owners") == names.index("Linked security capability") + 1


def test_a_lookup_may_start_from_an_earlier_answer_only_if_that_property_is_decided_first():
    col = {"name": "Owners", "type": "list", "uses": ["Impacted application"],
           "lookups": [{"find": "who owns each", "from": "result:Impacted application", "match": "name"}]}
    names = ["Impacted application", "Owners"]
    assert usecases._lookup_errors("P", col["lookups"], None, col, names) == []
    no_uses = dict(col, uses=[])
    assert "needs 'Impacted application' in this column's 'builds on' list" in usecases._lookup_errors("P", col["lookups"], None, no_uses, names)[0]
    ghost = dict(col, lookups=[{"find": "x", "from": "result:Nothing", "match": "name"}])
    assert "not another column of this stage" in usecases._lookup_errors("P", ghost["lookups"], None, ghost, names)[0]
    me = dict(col, lookups=[{"find": "x", "from": "result:Owners", "match": "name"}], uses=["Owners"])
    assert "not another column" in usecases._lookup_errors("P", me["lookups"], None, me, names)[0]
    assert "other_demands" in usecases._lookup_errors("P", [{"find": "x", "from": "bogus", "match": "name"}], None, col, names)[0]
    assert pmod._lookup({"find": "x", "from": "result:Impacted application", "match": "name"}, [])["from"] == "result:Impacted application"
    assert pmod._lookup({"find": "x", "from": "result:", "match": "name"}, []) is None


def test_the_names_inside_an_earlier_answer_become_the_next_lookups_names():
    from eawiki.cases import gather as gmod
    assert gmod.names_from_result(["Peoplex HR System (C-204)", "HR & Payroll Portal (C-207)", "None"]) == ["Peoplex HR System", "C-204", "HR & Payroll Portal", "C-207"]
    assert gmod.names_from_result("Not applicable") == [] and gmod.names_from_result("(unknown: asked the architect)") == [] and gmod.names_from_result(None) == []


def test_an_unanswered_decision_is_listed_but_cannot_be_cited():
    col = COLS["Linked security capability"]
    ev = dict(EV, allowed={"demand:title"})
    res = {"value": ["Not applicable"], "status": "answered", "evidence": ["decided:Demand type", "demand:title"]}
    cell = smod.verify(col, res, ev, {"Demand type": "(unknown: asked the architect)"})
    assert cell["evidence"] == ["demand:title"]
    assert "  Demand type: (unknown: asked the architect)" in smod._prompt(col, {}, SPEC, EV, {"Demand type": "(unknown: asked the architect)"})


def test_the_points_reach_the_model_after_the_steps_and_before_the_evidence():
    col = COLS["Domain"]
    p = smod._prompt(col, {}, SPEC, EV, {})
    assert "HOW TO COMBINE WHAT WAS RETRIEVED" in p and col["collate"] in p
    assert p.index("HOW TO DECIDE IT") < p.index("HOW TO COMBINE WHAT WAS RETRIEVED") < p.index("EVIDENCE:")
    bare = smod._prompt({k: v for k, v in col.items() if k != "collate"}, {}, SPEC, EV, {})
    assert "HOW TO COMBINE" not in bare


def test_an_answer_may_cite_an_earlier_decision_so_not_applicable_needs_no_document():
    col = COLS["Linked security capability"]
    res = {"value": ["Not applicable"], "status": "answered", "evidence": ["decided:Demand type", "decided:Urgency", "demand:title"]}
    ev = dict(EV, allowed={"demand:title"})
    cell = smod.verify(col, res, ev, {"Demand type": "People", "Urgency": ""})
    assert cell["status"] == "answered" and cell["evidence"] == ["decided:Demand type", "demand:title"]       # an empty decision is not citable
    assert smod.verify(col, res, ev, {})["evidence"] == ["demand:title"]                                      # nothing decided: nothing to cite
    only = smod.verify(col, dict(res, evidence=["decided:Demand type"]), EV, {"Demand type": "People"})
    assert only["status"] == "answered" and not only["need"]
    p = smod._prompt(col, {}, SPEC, EV, {"Demand type": "People", "Domain": ["Application", "Security"]})
    assert "[decided:Demand type] Demand type: People" in p and "[decided:Domain] Domain: Application; Security" in p


def test_a_property_without_points_is_unchanged_and_the_plan_notices_a_change():
    c = {"name": "P", "type": "text"}
    assert pmod.guidance_key(c) == pmod.guidance_key(dict(c)) != pmod.guidance_key(dict(c, collate="x"))


def test_the_points_are_bounded_and_an_empty_box_leaves_nothing_behind():
    bad = {"id": "t", "name": "T", "input": {"item_fields": []}, "stages": [{"name": "S", "id": "s", "output": {"columns": [{"name": "P", "type": "text", "collate": "x" * 2600}]}}]}
    assert any("collate" in e for e in usecases.validate(bad))
    ok = json.loads(json.dumps(bad))
    ok["stages"][0]["output"]["columns"][0]["collate"] = "   "
    usecases._tidy_descriptions(ok)
    assert "collate" not in ok["stages"][0]["output"]["columns"][0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  passed", name)
    print("ok")
