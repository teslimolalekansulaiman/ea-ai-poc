"""Step 1 of the page finder: matching a mention to graph entities. No model, no knowledge base beyond the fixture."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402

from eawiki.cases import namelookup as nl  # noqa: E402

NODES = kb.NODES
SYSTEM_KINDS, DATA_KINDS = ["app", "tech"], ["data"]


def kinds_for(gold_ids):
    return DATA_KINDS if any(i.startswith("DE-") for i in gold_ids) else SYSTEM_KINDS


def test_every_reference_mention_of_the_18_demands_resolves_to_the_right_entity():
    bad = []
    for d in kb.DEMANDS:
        for m, gold in d["gold"]["mentions"].items():
            c = nl.resolve_entities(m, NODES, kinds=kinds_for(gold))
            if gold and (not c or c[0]["id"] not in gold):
                bad.append((d["item"]["demand_id"], m, gold, [x["id"] for x in c]))
            if not gold and any(x["strong"] for x in c):
                bad.append((d["item"]["demand_id"], m, "no entry", [x["id"] for x in c]))
    assert not bad, bad


def test_a_partial_match_is_never_strong():
    c = nl.resolve_entities("payroll", NODES, kinds=["app"])
    assert [x["id"] for x in c] == ["C-207"] and not c[0]["strong"] and c[0]["how"] == "only part of its name"
    c = nl.resolve_entities("Peoplex payroll module", NODES, kinds=["app"])
    assert c[0]["id"] == "C-204" and not c[0]["strong"]


def test_how_a_mention_matched_is_named():
    how = lambda m, **kw: nl.resolve_entities(m, NODES, **kw)[0]["how"]
    assert how("Peoplex HR System") == "exact"
    assert how("HR system", kinds=["app"]) == "alias"
    assert how("C-204") == "id"
    assert how("Callwav contact centre", kinds=["app"]) == "same words, spelling corrected"


def test_another_kind_with_the_same_name_is_reported_not_offered():
    r = nl.resolve_entities("HR system", NODES, kinds=["app"])
    assert r[0]["id"] == "C-204" and all(c["family"] == "app" for c in r)
    assert [c["id"] for c in nl.other_kinds("HR system", NODES, ["app"])] == ["DE-01"]
    assert [c["id"] for c in nl.other_kinds("HR data", NODES, ["data"])] == ["C-204"]


def test_a_name_of_two_kinds_is_flagged_and_a_clear_winner_is_not():
    assert nl.ambiguous(nl.resolve_entities("HR", NODES))
    for m in ("HR system", "Finance system", "data warehouse", "Oracle DB", "customer data"):
        assert not nl.ambiguous(nl.resolve_entities(m, NODES)), m


def test_one_typo_is_read_as_the_word_the_knowledge_base_has_and_says_so():
    c = nl.resolve_entities("Peoplx HR", NODES, kinds=["app"])[0]
    assert c["id"] == "C-204" and "spelling corrected" in c["how"] and c["strong"]
    assert nl.correct_spelling("HR", NODES) == ("hr", False)             # a short word is left alone
    assert not nl.correct_spelling("zeppelin", NODES)[1]                  # nothing one typo away
    assert nl._within_one("peoplx", "peoplex") and nl._within_one("finvera", "finvrea") and not nl._within_one("oracle", "orange")


def test_nothing_is_offered_for_a_name_the_knowledge_base_does_not_have():
    for m in ("website forms", "inspection tablets", "field inspection app", "att. devices", "spreadsheets"):
        assert not any(c["strong"] for c in nl.resolve_entities(m, NODES, kinds=SYSTEM_KINDS)), m


def test_the_match_is_the_same_for_the_same_name_in_any_demand():
    """No taxpayer, file or language in the matcher: the same mention gives the same answer wherever it appears."""
    a = nl.resolve_entities("HR system", NODES, kinds=["app"])
    b = nl.resolve_entities("  The HR System ", NODES, kinds=["app"])
    assert [c["id"] for c in a] == [c["id"] for c in b]


def test_graph_nodes_become_matcher_entities_with_ids_and_page_slugs():
    from eawiki.cases.tools import graph_entities
    from eawiki.query import graphquery as gq
    g = gq._Graph([{"node_id": "n1", "name": "Peoplex HR System", "type": "physical_application_component", "aliases": ["HR system", "C-204"]},
                   {"node_id": "n2", "name": "Oracle Database Platform", "type": "logical_technology_component", "aliases": ["Oracle DB"]},
                   {"node_id": "n3", "name": "HR", "type": "data_entity"}], [], {})
    nodes = graph_entities(g)
    by = {n["node_id"]: n for n in nodes}
    assert by["n1"]["ids"] == ["C-204"] and by["n1"]["aliases"] == ["HR system"] and by["n1"]["slug"] == "peoplex-hr-system"
    assert nl.resolve_entities("HR system", nodes, kinds=["app"])[0]["id"] == "n1"
    assert nl.resolve_entities("C-204", nodes)[0]["id"] == "n1"
    assert nl.resolve_entities("Oracle DB", nodes, kinds=["tech"])[0]["id"] == "n2"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  passed", name)
    print("ok")
