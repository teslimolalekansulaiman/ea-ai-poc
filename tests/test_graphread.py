"""Step 5 of the page finder: reading the graph around the candidates, for the relationships the lookup asks for."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.cases import graphread as gr  # noqa: E402
from eawiki.cases import plan as pmod  # noqa: E402
from eawiki.query import graphquery as gq  # noqa: E402

NODES, EDGES = kb.graph_parts()
G = gq._Graph(NODES, EDGES, {})
APP_FLOWS = [{"relation": "sends_data_to", "direction": "both"}, {"relation": "communicates_with", "direction": "both"},
             {"relation": "accesses", "direction": "out"}]


def cand(nid, graph=True):
    return {"id": nid, "name": kb.NODE_BY_ID[nid]["name"], "graph": graph}


def texts(r, cid):
    return {f["text"] for f in r["facts"][cid]}


def test_only_the_relationships_the_lookup_names_are_read_in_the_direction_asked():
    r = gr.read({"HR system": [cand("C-204")]}, APP_FLOWS, G)
    assert texts(r, "C-204") == {"Attendance System --sends_data_to--> Peoplex HR System", "Peoplex HR System --sends_data_to--> HR & Payroll Portal",
                                 "Peoplex HR System --accesses--> Employee Master Data", "Peoplex HR System --accesses--> Leave and Attendance Records"}
    assert not any(f["relation"] == "is_deployed_on" for f in r["facts"]["C-204"])          # not asked for
    assert r["status"]["HR system"]["C-204"] == "read" and r["skipped"] == ""


def test_direction_in_gives_the_applications_on_a_platform_and_out_gives_nothing_there():
    r = gr.read({"Oracle DB": [cand("T-01")]}, [{"relation": "is_deployed_on", "direction": "in"}], G)
    assert {f["other"]["id"] for f in r["facts"]["T-01"]} == {"C-204", "C-207", "C-201"} and {f["direction"] for f in r["facts"]["T-01"]} == {"in"}
    out = gr.read({"Oracle DB": [cand("T-01")]}, [{"relation": "is_deployed_on", "direction": "out"}], G)
    assert out["facts"]["T-01"] == [] and out["status"]["Oracle DB"]["T-01"] == "none found"


def test_a_lookup_that_names_no_relationships_reads_nothing_and_says_so():
    r = gr.read({"HR system": [cand("C-204")]}, [], G)
    assert r["facts"] == {} and r["status"]["HR system"]["C-204"] == "not asked" and "no graph relationships" in r["skipped"]


def test_each_fact_names_the_far_end_and_the_passage_the_edge_came_from():
    f = next(x for x in gr.read({"m": [cand("C-206")]}, APP_FLOWS, G)["facts"]["C-206"] if x["relation"] == "communicates_with")
    assert f["other"] == {"id": "C-210", "name": "Attendance Devices Gateway", "type": kb.APP} and f["direction"] == "out"
    assert f["block_ids"] == [kb.FIRST_BLOCK["C-206"]]
    assert gr.read({"m": [cand("C-206")]}, APP_FLOWS, G)["block_ids"] == [kb.FIRST_BLOCK["C-206"]]


def test_a_page_only_pick_an_unknown_id_and_the_limits():
    page_only = {"id": "page:catalogue-item", "name": "Catalogue Item", "graph": False}
    r = gr.read({"m": [page_only, cand("C-204"), cand("C-207"), cand("C-208"), cand("C-206")]}, APP_FLOWS, G)
    assert r["status"]["m"] == {"page:catalogue-item": "no entity", "C-204": "read", "C-207": "read", "C-208": "read", "C-206": "not read"}
    assert gr.read({"m": [{"id": "ghost", "name": "G", "graph": True}]}, APP_FLOWS, G)["status"]["m"]["ghost"] == "no entity"
    tiny = gr.read({"m": [cand("C-204")]}, APP_FLOWS, G, max_facts=2)
    assert len(tiny["facts"]["C-204"]) == 2 and tiny["more"]["C-204"] == 2
    capped = gr.read({"a": [cand("C-204")], "b": [cand("C-207")]}, APP_FLOWS, G, max_total=4)
    assert capped["status"]["b"]["C-207"] == "not read"


def test_a_candidate_shared_by_two_mentions_is_read_once():
    r = gr.read({"HR system": [cand("C-204")], "Peoplex": [cand("C-204")]}, APP_FLOWS, G)
    assert r["status"]["Peoplex"]["C-204"] == "read" and len(r["facts"]) == 1


def test_one_thing_recorded_under_two_nodes_is_read_as_one():
    nodes = NODES + [{"node_id": "dup", "name": "Peoplex HR System", "type": "logical_application_component", "aliases": []}]
    g = gq._Graph(nodes, EDGES + [{"source": "dup", "target": "T-01", "relation": "is_deployed_on", "block_ids": []}], {})
    r = gr.read({"m": [cand("C-204")]}, [{"relation": "is_deployed_on", "direction": "out"}], g)
    assert len(r["facts"]["C-204"]) == 2 and {f["other"]["id"] for f in r["facts"]["C-204"]} == {"T-01"}


def test_ownership_is_a_relationship_like_any_other():
    nodes = NODES + [{"node_id": "role1", "name": "HR Systems Lead", "type": "role", "aliases": []}]
    g = gq._Graph(nodes, EDGES + [{"source": "C-204", "target": "role1", "relation": "is_owned_by", "block_ids": ["x:1"]}], {})
    r = gr.read({"m": [cand("C-204")]}, [{"relation": "is_owned_by", "direction": "out"}], g)
    assert [f["other"]["name"] for f in r["facts"]["C-204"]] == ["HR Systems Lead"] and r["block_ids"] == ["x:1"]


def lookup(**kw):
    return dict({"find": "which applications exchange data", "from": "systems", "match": "name"}, **kw)


def col(lk):
    return {"name": "P", "type": "list", "lookups": [lk]}


def test_the_use_case_accepts_relations_and_types_and_refuses_the_rest():
    ok = lookup(types=["application"], relations=APP_FLOWS)
    assert usecases._lookup_errors("P", [ok], {"sends_data_to", "communicates_with", "accesses"}) == []
    bad = usecases._lookup_errors("P", [lookup(types=["people"], relations=[{"relation": "invented", "direction": "sideways"}, {"direction": "in"}])],
                                  {"sends_data_to"})
    assert any("'types' must be" in e for e in bad) and any("direction" in e for e in bad)
    assert any("not a relationship type of the metamodel" in e for e in bad) and any("needs a 'relation' name" in e for e in bad)
    many = [{"relation": f"r{i}", "direction": "in"} for i in range(13)]
    assert usecases._lookup_errors("P", [lookup(relations=many)], None) == ["P: lookup 1: relations must be a list of at most 12."]
    assert any("listed twice" in e for e in usecases._lookup_errors("P", [lookup(relations=APP_FLOWS + APP_FLOWS[:1])], None))
    assert usecases._lookup_errors("P", [lookup(relations=[{"relation": "anything", "direction": "in"}])], None) == []      # names unchecked when unknown


def test_the_plan_keeps_types_and_relations_and_drops_what_is_malformed():
    p = pmod._lookup(lookup(types=["application", "nonsense"], relations=APP_FLOWS + [{"relation": "x", "direction": "up"}, "junk"], **{"in": []}), [])
    assert p["types"] == ["application"] and p["relations"] == APP_FLOWS
    assert pmod._lookup(lookup(), [])["relations"] == [] and pmod.default_lookups({"name": "X"})[0]["relations"] == []


def test_empty_types_and_relations_leave_no_key_behind_when_a_use_case_is_saved():
    spec = {"id": "x", "name": "X", "input": {"item_fields": []}, "stages": [{"name": "S", "id": "s", "output": {"columns": [
        {"name": "P", "type": "list", "lookups": [lookup(types=[], relations=[])]}]}}]}
    usecases._tidy_descriptions(spec)
    assert "types" not in spec["stages"][0]["output"]["columns"][0]["lookups"][0] and "relations" not in spec["stages"][0]["output"]["columns"][0]["lookups"][0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  passed", name)
    print("ok")
