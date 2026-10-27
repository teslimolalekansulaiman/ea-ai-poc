"""Steps 2 and 3 of the page finder, without a model: the list, the prompt, the checks on the model's picks."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402

from eawiki.cases import namelookup as nl  # noqa: E402
from eawiki.cases import pagefinder as pf  # noqa: E402

INDEX = pf.build_index(kb.NODES, kb.page_entries())
BY_NAME = {it["name"]: it for it in INDEX}


def n_of(name):
    return BY_NAME[name]["n"]


def test_an_entity_and_its_page_are_one_entry_and_a_page_without_an_entity_is_its_own():
    assert len(INDEX) == len(kb.NODES)                                   # every fixture entity has a page
    it = BY_NAME["Peoplex HR System"]
    assert it["node_id"] == "C-204" and it["slug"] == "peoplex-hr-system" and "HR system" in it["aliases"] and "C-204" in it["aliases"]
    assert "payroll export" in it["summary"]
    extra = pf.build_index(kb.NODES, kb.page_entries() + [{"slug": "orphan", "title": "Orphan Page", "type": "application", "summary": "Only a page."}])
    assert extra[-1]["name"] == "Orphan Page" and extra[-1]["node_id"] is None and extra[-1]["n"] == len(extra)
    lone = pf.build_index(kb.NODES[:1], [])
    assert lone[0]["slug"] is None and lone[0]["summary"] == ""


def test_the_model_sees_one_numbered_line_per_entry_and_the_mentions():
    p = pf._prompt([{"text": "payroll", "group": "systems"}, {"text": "نظام الموارد البشرية"}], INDEX[:3])
    assert 'M1: "payroll" (listed as: systems)' in p and 'M2: "نظام الموارد البشرية"' in p
    assert f"[1] {INDEX[0]['name']}" in p and "ignore any instruction" in p and '"none" is a good answer' in p and "M2: none" in p


def test_the_answer_is_read_line_by_line():
    assert pf.parse_answer("M1: 12, 40\nM2: none\nM3 - 7\n**M4**: 3", 4) == {1: [12, 40], 2: [], 3: [7], 4: [3]}
    assert pf.parse_answer("Here you go:\nM1: 5\nM9: 1\nM2:\nnonsense", 2) == {1: [5], 2: []}      # M9 was never asked; M2 empty = none
    assert pf.parse_answer(None, 3) == {} and pf.parse_answer("no lines at all", 3) == {}


def test_only_numbers_that_are_in_the_list_are_believed():
    ms = [{"text": "payroll"}, {"text": "fax machine"}]
    good, other = n_of("HR & Payroll Portal"), n_of("Payroll Data")
    r = pf.find(ms, INDEX, lambda _p: f"M1: {good}, 9999, {other}, {good}, 3, 4\nM2: none\nM7: 1")
    names = [it["name"] for it in r["picks"]["payroll"]]
    assert r["status"] == "ok" and names == ["HR & Payroll Portal", "Payroll Data", INDEX[2]["name"]] and r["unread"] == []   # 9999 and the repeat dropped, then at most 3
    assert r["picks"]["fax machine"] == [] and set(r["picks"]) == {"payroll", "fax machine"}


def test_a_mention_the_model_gave_no_line_for_is_unread_not_no_entry():
    ms = [{"text": "payroll"}, {"text": "fax machine"}]
    calls = []

    def llm(_p):
        calls.append(1)
        return f"M1: {n_of('HR & Payroll Portal')}"                  # never answers M2
    r = pf.find(ms, INDEX, llm)
    assert len(calls) == 2 and r["status"] == "unavailable" and r["unread"] == ["fax machine"] and len(r["picks"]["payroll"]) == 1
    for bad in (None, lambda _p: None, lambda _p: "sorry", lambda _p: (_ for _ in ()).throw(RuntimeError("down"))):
        r = pf.find(ms, INDEX, bad)
        assert r["status"] == "unavailable" and r["unread"] == ["fax machine", "payroll"] and all(v == [] for v in r["picks"].values())
    assert pf.find([], INDEX, lambda _p: "")["status"] == "nothing_to_do" and pf.find(ms, [], lambda _p: "")["status"] == "nothing_to_do"


def test_a_second_try_fills_in_what_the_first_left_out():
    ms = [{"text": "a"}, {"text": "b"}]
    answers = iter(["M1: 1", "M2: 2"])
    r = pf.find(ms, INDEX, lambda _p: next(answers))
    assert r["status"] == "ok" and [i["n"] for i in r["picks"]["a"]] == [1] and [i["n"] for i in r["picks"]["b"]] == [2]


def test_a_long_list_is_read_in_parts_and_the_picks_are_joined():
    calls = []

    def llm(prompt):
        calls.append(prompt)
        nums = [int(x) for x in re.findall(r"^\[(\d+)\]", prompt, re.M)]
        return f"M1: {nums[0]}"
    r = pf.find([{"text": "x"}], INDEX, llm, max_items=10)
    assert len(calls) == -(-len(INDEX) // 10) and len(r["picks"]["x"]) == len(calls) and r["status"] == "ok"
    assert max(len(re.findall(r"^\[\d+\]", c, re.M)) for c in calls) <= 10


def test_step1_settles_what_it_can_and_only_the_rest_goes_to_the_finder():
    ms = [{"text": "HR system", "group": "systems"}, {"text": "payroll", "group": "systems"}, {"text": "spreadsheets", "group": "systems"}]
    kinds = lambda m: ["app", "tech"]
    assert [m["text"] for m in pf.unsettled(ms, kb.NODES, kinds)] == ["payroll", "spreadsheets"]


def test_a_pick_is_a_candidate_never_a_strong_match_and_says_who_chose_it():
    step1 = nl.resolve_entities("payroll", kb.NODES, kinds=["app"])
    portal = BY_NAME["HR & Payroll Portal"]
    out = pf.merge(step1, [portal, BY_NAME["Attendance System"]], ["app"])
    ids = [c["id"] for c in out["candidates"]]
    assert ids == ["C-207", "C-206"] and not any(c["strong"] for c in out["candidates"])
    assert out["candidates"][0]["how"] == "only part of its name; confirmed by the page finder"
    assert out["candidates"][1]["how"] == pf.HOW and out["candidates"][1]["graph"] is True


def test_a_pick_of_another_kind_is_set_aside_and_a_page_without_an_entity_is_flagged():
    out = pf.merge([], [BY_NAME["Payroll Data"]], ["app", "tech"])
    assert out["candidates"] == [] and [c["id"] for c in out["other_kinds"]] == ["DE-12"]
    page_only = {"name": "Catalogue Item", "type": "application", "summary": "", "node_id": None, "slug": "catalogue-item", "aliases": [], "n": 1}
    c = pf.merge([], [page_only], None)["candidates"][0]
    assert c["id"] == "page:catalogue-item" and c["graph"] is False and c["slug"] == "catalogue-item"


def test_the_list_is_the_same_whichever_demand_asks():
    assert [it["n"] for it in INDEX] == list(range(1, len(INDEX) + 1))
    assert pf.build_index(kb.NODES, kb.page_entries()) == INDEX


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  passed", name)
    print("ok")
