"""A property that only compares the demand with the other demands of the sheet looks at the sheet and nothing else, and 'None' is an answer
when it is told that none is."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402
import kb_tools  # noqa: E402

from eawiki.cases import gather as gmod  # noqa: E402
from eawiki.cases import plan as pmod  # noqa: E402
from eawiki.cases import solve  # noqa: E402

SPEC = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))
COLS = {c["name"]: c for st in SPEC["stages"] for c in st["output"]["columns"]}
NUMBER = COLS["Duplicate demand number (in the sheet)"]
CMP = {"find": "same outcome", "from": "other_demands", "match": "compare", "in": [], "docs": [], "types": [], "relations": []}


def test_the_sources_of_a_property_that_only_compares_are_the_demand_and_the_sheet():
    plan = pmod.default_plan(NUMBER, kb.DOCS)
    assert plan["sources"] == ["demand", "other_demands"]
    assert pmod.sources_for([CMP, dict(CMP, **{"from": "systems"})], ["demand", "documents", "graph"]) == ["demand", "documents", "graph"]
    assert pmod.sources_for([], ["demand", "documents"]) == ["demand", "documents"]


def test_a_plan_made_before_the_rule_is_held_to_it_and_no_document_or_graph_is_read():
    d = kb.DEMANDS[0]
    item = dict(d["item"], _id=d["item"]["demand_id"])
    prof = {g: [] for g in gmod.PROFILE_GROUPS}
    prof["origin"] = "model"
    old_plan = {"sources": ["demand", "documents", "graph"], "queries": ["{__text__}"], "lookups": [CMP], "documents": ["Application_Catalog"], "origin": "model"}
    tools = kb_tools.make_tools(llm_text=lambda p: "")
    tools.search = lambda q, k, docs: (_ for _ in ()).throw(AssertionError("a document was searched"))
    tools.link = lambda t: (_ for _ in ()).throw(AssertionError("the graph was read"))
    ev = gmod.gather(tools, old_plan, SPEC, item, [], {}, None, prof, {}, {})
    assert ev["blocks"] == [] and ev["graph"] is None


def ev_with(items):
    return {"allowed": set(), "used": ["the demand's own fields"], "searched": [], "demand": {}, "lookups": [], "wiki": [], "graph_reads": [], "graph": None,
            "others": [], "blocks": [], "compared": {"items": items, "status": "ok", "question": "q"}}


def test_with_no_other_demand_in_common_the_answer_is_none_and_no_model_is_asked():
    called = []
    cell = solve.solve(NUMBER, {}, SPEC, ev_with([]), {}, lambda p: called.append(p) or {})
    assert called == [] and cell["value"] == "None" and cell["status"] == "answered"


def test_with_candidates_the_model_decides_and_a_blank_answer_becomes_none():
    called = []
    items = [{"id": "D-2", "verdict": "different", "reason": "other users", "title": "x"}]
    cell = solve.solve(NUMBER, {}, SPEC, ev_with(items), {}, lambda p: called.append(p) or {"value": "", "status": "answered", "evidence": [], "note": "none of them"})
    assert len(called) == 1 and "\"None\" is a complete answer" in called[0] and cell["value"] == "None" and cell["status"] == "answered"
    cell = solve.solve(NUMBER, {}, SPEC, ev_with(items), {}, lambda p: {"value": "D-2", "status": "answered", "evidence": [], "note": "same"})
    assert cell["value"] == "D-2"


def test_the_shortcut_is_only_for_a_property_that_says_so():
    col = {k: v for k, v in NUMBER.items() if k != "blank_ok"}
    cell = solve.solve(col, {}, SPEC, ev_with([]), {}, lambda p: {"value": "", "status": "answered", "evidence": [], "note": ""})
    assert cell["status"] == "needs_input"                                              # blank is not an answer unless the property says it is
