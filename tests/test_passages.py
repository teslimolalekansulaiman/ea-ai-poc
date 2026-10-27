"""Step 6 of the page finder: the question put to the passage search, where it looks, and how each passage is marked.
The search is the fixture's lexical stand-in: it tests the plumbing and the marking, not the quality of embeddings."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402
import names_spec  # noqa: E402

from eawiki.cases import namelookup as nl  # noqa: E402
from eawiki.cases import passages as ps  # noqa: E402
from eawiki.cases import plan as pmod  # noqa: E402

COLS = {c["name"]: c for c in names_spec.COLS}


def lookup(col, i=0):
    return pmod._lookup(COLS[col]["lookups"][i], kb.DOCS)


def block(doc, n):
    return next(b for b in kb.BLOCKS if b["block_id"] == f"{doc}:{n}")


def test_the_search_is_asked_the_lookups_question_then_what_it_is_about():
    lk = {"find": "who owns each data set the demand names"}
    assert ps.passage_query(lk, "employee records", "x") == "who owns each data set the demand names: employee records"
    q = ps.passage_query(lk, None, "Employees request leave. " * 100)
    assert q.startswith("who owns each data set the demand names. Employees") and len(q) <= len(lk["find"]) + 2 + ps.MAX_QUERY_TEXT
    assert ps.passage_query({"find": " "}, "payroll", "x") == "payroll" and ps.passage_query({}, None, "the demand") == "the demand"


def test_a_passage_is_an_entry_only_when_its_first_words_are_the_name():
    assert ps.names_head("C-214 Procurement Portal", "procurement system") is True            # kind words aside
    assert ps.names_head("C-207 HR & Payroll Portal", "payroll") is False                     # only part of a longer name
    assert ps.names_head("Training Portal | HR Training Lead | pages", "training portal") is True
    assert ps.names_head("anything", "system") is False                                       # a kind word alone names nothing


def test_passages_are_marked_entry_mentioned_or_closest_for_the_mention_they_were_searched_for():
    blocks = [block("Application_Catalog", 4), block("Application_Catalog", 7), block("Data_Catalog", 1)]
    m = ps.mark(blocks, "payroll")
    assert m == {"entry": [], "mentioned": ["Application_Catalog:4", "Application_Catalog:7"], "closest": ["Data_Catalog:1"]}
    m = ps.mark(blocks, "HR system", ["Peoplex HR System"])                                    # a candidate's name makes the row an entry
    assert m["entry"] == ["Application_Catalog:4"] and "Application_Catalog:7" not in m["entry"]
    assert ps.mark(blocks, "HR", [])["mentioned"] != []                                        # a two-letter name still has words
    assert "Data_Catalog:1" in ps.mark(blocks, "HR", [])["entry"]                              # the bare name 'HR' IS the data category's row
    assert "Data_Catalog:1" not in m["entry"] and ps.says_name("HR", "HR system") is False      # 'HR system' is not the row 'HR'
    assert ps.says_name("C-214 Procurement Portal", "procurement system") is False             # without a candidate, kind words must match too


def test_the_named_documents_are_searched_first_and_a_short_search_of_everything_follows():
    calls = []

    def fn(q, k, docs):
        calls.append((k, docs))
        return kb.search(q, k, docs)
    lk = lookup("Impacted application")
    r = ps.read(lk, ["Peoplex HR System"], "x", fn)
    assert calls[0] == (ps.PER_MENTION, lk["docs"]) and calls[1] == (ps.GLOBAL_EXTRA, None)
    assert {"Application_Catalog"} <= {b["doc_id"] for b in r["blocks"]}
    calls.clear()
    ps.read(lk, ["Peoplex HR System"], "x", fn, strict=True)
    assert calls == [(ps.PER_MENTION, lk["docs"])]                                             # strict: named documents only
    calls.clear()
    ps.read(dict(lk, docs=[]), ["Peoplex HR System"], "x", fn)
    assert calls == [(ps.PER_MENTION, None)]                                                   # no document named: search all, once


def test_a_passage_found_only_by_the_search_of_everything_says_so():
    named = {"block_id": "A:1", "doc_id": "A", "text": "x"}
    other = {"block_id": "B:1", "doc_id": "B", "text": "y"}
    out = ps.search(lambda q, k, docs: [named] if docs else [named, other], "q", 3, ["A"])
    assert [(b["block_id"], b.get("outside", False)) for b in out] == [("A:1", False), ("B:1", True)]


def test_a_search_that_finds_nothing_and_one_that_fails_are_told_apart():
    lk = lookup("Impacted application")
    none = ps.read(lk, ["zzzz unknownword"], "x", lambda q, k, d: [])["items"][0]
    assert none["state"] == "none" and none["entry"] == none["mentioned"] == none["closest"] == []

    def boom(q, k, d):
        raise OSError("vector store down")
    err = ps.read(lk, ["HR system"], "x", boom)
    assert err["items"][0]["state"] == "error" and err["blocks"] == []


def test_a_lookup_with_no_mention_searches_by_meaning_and_marks_nothing_as_an_entry():
    lk = lookup("Domain", 2)                                                                    # "from need", by meaning
    r = ps.read(lk, [None], "Employees need an app that signs in with MFA", kb.search)
    it = r["items"][0]
    assert it["by"] == "meaning" and it["mention"] is None and it["query"].startswith(lk["find"] + ". Employees need")
    assert it["entry"] == [] and it["mentioned"] == [] and it["state"] in ("found", "none")


def test_every_reference_application_is_found_as_an_entry_for_its_mention():
    """Over the 18 demands: the lookup's question, then the mention, finds the catalog row as an entry. (Lexical stand-in.)"""
    lk = lookup("Impacted application")
    miss = []
    for d in kb.DEMANDS:
        for m, gold in d["gold"]["mentions"].items():
            apps = [i for i in gold if i.startswith("C-")]
            if not apps:
                continue
            cands = nl.resolve_entities(m, kb.NODES, kinds=["app", "tech"])
            r = ps.read(lk, [m], "x", kb.search, {m: cands})
            want = {kb.FIRST_BLOCK[i] for i in apps}
            if not want <= set(r["items"][0]["entry"]):
                miss.append((d["item"]["demand_id"], m, sorted(want - set(r["items"][0]["entry"]))))
    assert not miss, miss


def test_an_abbreviation_is_also_searched_by_the_official_name_of_the_entity_found_for_it():
    lk = lookup("Impacted application")
    cands = {"CRM": nl.resolve_entities("CRM", kb.NODES, kinds=["app"])}
    asked = []
    r = ps.read(lk, ["CRM"], "x", lambda q, k, d: asked.append(q) or kb.search(q, k, d), cands, strict=True)
    it = r["items"][0]
    assert it["queries"] == [asked[0], "which application each name is: Customer Relationship Management System"] and asked == it["queries"]
    assert it["entry"] == ["Application_Catalog:13"]
    asked.clear()                                                                              # a partial match is not searched by name
    ps.read(lk, ["payroll"], "x", lambda q, k, d: asked.append(q) or [], {"payroll": nl.resolve_entities("payroll", kb.NODES, kinds=["app"])}, strict=True)
    assert asked == ["which application each name is: payroll"]
    asked.clear()                                                                              # the same name as the mention is not asked twice
    ps.read(lk, ["Peoplex HR System"], "x", lambda q, k, d: asked.append(q) or [], {"Peoplex HR System": nl.resolve_entities("Peoplex HR System", kb.NODES, kinds=["app"])}, strict=True)
    assert len(asked) == 1


def test_a_mention_the_documents_do_not_have_gets_no_entry():
    lk = lookup("Impacted application")
    for m in ("website forms", "inspection tablets", "field inspection app", "spreadsheets"):
        it = ps.read(lk, [m], "x", kb.search)["items"][0]
        assert it["entry"] == [], (m, it)


def test_the_blocks_are_the_union_without_repeats():
    lk = lookup("Impacted application")
    r = ps.read(lk, ["HR system", "Peoplex"], "x", kb.search, strict=True)
    ids = [b["block_id"] for b in r["blocks"]]
    assert len(ids) == len(set(ids)) and len(r["items"]) == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  passed", name)
    print("ok")
