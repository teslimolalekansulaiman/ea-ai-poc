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
    assert COLS["Domain"]["collate"].startswith("Add Securit statement when the data is Confidential or Restricted")
    assert "Never link by department alone" in COLS["Impacted application"]["collate"] and COLS["Impacted application"]["collate"].count("\n1. Read") == 1
    assert "NORA framework" in COLS["Linked security capability"]["collate"] and COLS["Data classification"]["collate"].startswith("Pick list:")
    assert "collate" not in COLS["Duplicate with existing artefact / artefact name"]            # held back: the text given is about duplicate demands


def test_the_points_reach_the_model_after_the_steps_and_before_the_evidence():
    col = COLS["Domain"]
    p = smod._prompt(col, {}, SPEC, EV, {})
    assert "HOW TO COMBINE WHAT WAS RETRIEVED" in p and col["collate"] in p
    assert p.index("HOW TO DECIDE IT") < p.index("HOW TO COMBINE WHAT WAS RETRIEVED") < p.index("EVIDENCE:")
    bare = smod._prompt({k: v for k, v in col.items() if k != "collate"}, {}, SPEC, EV, {})
    assert "HOW TO COMBINE" not in bare


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
