"""A question that starts from no name (a mandate, an objective) can be answered from a wiki page the finder picks by title and summary.
Off unless the lookup says `pages`. No real model: the model's answer is a function."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402
import kb_tools  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.cases import gather as gmod  # noqa: E402
from eawiki.cases import lookup as lkmod  # noqa: E402
from eawiki.cases import pagefinder as pf  # noqa: E402
from eawiki.cases import plan as pmod  # noqa: E402

SPEC = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))
COLS = {c["name"]: c for st in SPEC["stages"] for c in st["output"]["columns"]}

THEMES = {
    "digital-workplace-roadmap": "# Digital Workplace Roadmap\n\n## Summary\nSets the order in which staff-facing services move to self-service channels by 2027.\n\n## Objectives\n- OBJ-7 Self-service for staff requests.\n",
    "records-retention-strategy": "# Records Retention Strategy\n\n## Summary\nSays how long records are kept and who may delete them.\n",
}


class ThemeKB(kb_tools.FixtureKB):
    def wiki_entries(self):
        return super().wiki_entries() + [pf.page_item(s, md) for s, md in THEMES.items()]

    def page(self, slug):
        return THEMES.get(slug) or super().page(slug)


def pages_of(kbx=None):
    return (kbx or ThemeKB()).wiki_entries()


def number(entries, title):
    return next(i for i, p in enumerate(entries, 1) if p["title"] == title)


def lookup(**kw):
    return {"find": "Which strategy or roadmap does this demand serve?", "from": "mandates", "match": "meaning", "in": [], "docs": [],
            "extract": "", "types": [], "relations": [], "pages": True, **kw}


def run(lk, llm, cache=None, mentions=()):
    return lkmod.run(lk, list(mentions), "Staff must queue to ask for leave; they want to ask from a phone.", ThemeKB(), kb.search, llm,
                     cache if cache is not None else {}, "mandates")


def test_the_answer_line_is_read_and_a_missing_line_is_not_a_none():
    assert pf.parse_pages_answer("PAGES: 12, 40") == [12, 40]
    assert pf.parse_pages_answer("noise\n**PAGES:** none") == []
    assert pf.parse_pages_answer("I think page 3.") is None and pf.parse_pages_answer("") is None


def test_picks_are_checked_in_code_kept_once_and_capped():
    pages = pages_of()
    got = pf.find_pages("q", "d", pages, lambda p: "PAGES: 9999, 1, 1, 2, 3, 4, 5")
    assert [c["slug"] for c in got["picks"]] == [pages[0]["slug"], pages[1]["slug"], pages[2]["slug"]]
    assert got["state"] == "picked" and got["offered"] == len(pages) and not any(c["strong"] for c in got["picks"])


def test_none_is_an_answer_and_no_answer_is_not():
    pages = pages_of()
    assert pf.find_pages("q", "d", pages, lambda p: "PAGES: none")["state"] == "none"
    asked = []
    assert pf.find_pages("q", "d", pages, lambda p: asked.append(p) or "no idea")["state"] == "unread" and len(asked) == 2     # one more try
    assert pf.find_pages("q", "d", pages, None)["state"] == "unread"
    assert pf.find_pages("q", "d", [], lambda p: "PAGES: 1")["state"] == "no pages"
    def boom(p):
        raise RuntimeError("down")
    assert pf.find_pages("q", "d", pages, boom)["state"] == "unread"


def test_a_long_list_is_asked_in_parts_and_a_part_that_did_not_answer_is_reported():
    pages = pages_of()
    calls = []
    def llm(p):
        calls.append(p)
        return "PAGES: 1" if len(calls) == 1 else "garbled"
    got = pf.find_pages("q", "d", pages, llm, max_items=5)
    assert got["state"] == "picked" and got["unread_part"] and len(got["picks"]) == 1


def test_the_prompt_carries_the_question_the_demand_and_titles_with_summaries():
    seen = []
    pf.find_pages("Which roadmap does this serve?", "Staff queue for leave", pages_of(), lambda p: seen.append(p) or "PAGES: none")
    t = seen[0]
    assert "QUESTION: Which roadmap does this serve?" in t and "Staff queue for leave" in t
    assert "Digital Workplace Roadmap" in t and "Sets the order in which staff-facing services move" in t


def test_a_lookup_with_pages_reads_the_picked_page_and_says_which():
    entries = pages_of()
    n = number(entries, "Digital Workplace Roadmap")
    res = run(lookup(), lambda p: f"PAGES: {n}")
    ps = res["page_search"]
    assert ps["state"] == "picked" and ps["picked"] == [{"name": "Digital Workplace Roadmap", "slug": "digital-workplace-roadmap", "state": "read"}]
    pg = next(p for p in res["wiki"] if p["slug"] == "digital-workplace-roadmap")
    assert pg["id"] == "wiki:digital-workplace-roadmap" and "OBJ-7" in json.dumps(pg["digest"])


def test_without_the_setting_nothing_changes_and_the_model_is_not_asked():
    asked = []
    res = run(lookup(pages=False), lambda p: asked.append(p) or "PAGES: 1")
    assert res["page_search"] is None and asked == [] and res["wiki"] == []


def test_the_question_is_asked_once_for_a_demand():
    asked, cache = [], {}
    llm = lambda p: asked.append(p) or "PAGES: none"      # noqa: E731
    run(lookup(), llm, cache)
    run(lookup(), llm, cache)
    assert len(asked) == 1


def test_a_lookup_that_names_nothing_still_asks_for_pages():
    res = run(lookup(), lambda p: "PAGES: none", mentions=[])      # the demand mentions no mandate: nothing is searched by name
    assert res["items"] == [] and res["page_search"]["state"] == "none"


def gather_with(lk, llm, spec_flag=None):
    d = kb.DEMANDS[0]
    item = dict(d["item"], _id=d["item"]["demand_id"])
    prof = {g: [] for g in gmod.PROFILE_GROUPS}
    prof["origin"] = "model"
    plan = pmod.default_plan(COLS["Domain"], kb.DOCS)
    plan["lookups"] = [{**lk, "docs": []}]
    tools = kb_tools.make_tools(llm_text=llm)
    tools.kb = ThemeKB()
    spec = {k: v for k, v in SPEC.items() if k != "wiki_pages"}          # the file turns it on; these tests set it themselves
    if spec_flag is not None:
        spec["wiki_pages"] = spec_flag
    return gmod.gather(tools, plan, spec, item, [], {}, None, prof, {}, {})


def test_the_evidence_names_the_pages_and_makes_them_citable():
    n = number(pages_of(), "Digital Workplace Roadmap")
    ev = gather_with(lookup(), lambda p: f"PAGES: {n}")
    text = gmod.render(ev)
    assert "Wiki pages: of " in text and "picked from title and first sentence: Digital Workplace Roadmap." in text
    assert "wiki:digital-workplace-roadmap" in ev["allowed"] and "[wiki:digital-workplace-roadmap] Digital Workplace Roadmap" in text
    assert any(s.startswith("wiki pages for") and "Digital Workplace Roadmap" in s for s in ev["searched"])


def test_a_page_search_that_could_not_run_is_never_reported_as_no_page_fits():
    text = gmod.render(gather_with(lookup(), lambda p: "no idea"))
    assert "THE PAGE FINDER COULD NOT BE ASKED" in text and "no page fits" not in text
    none_text = gmod.render(gather_with(lookup(), lambda p: "PAGES: none"))
    assert "none of the" in none_text and "could answer this" in none_text


def test_the_setting_is_validated_and_kept():
    assert usecases._lookup_errors("P", [{**lookup(), "pages": "yes"}], None) == ["P: lookup 1: 'pages' must be true or false."]
    assert usecases._lookup_errors("P", [lookup()], None) == []
    assert pmod._lookup(lookup(), [])["pages"] is True and pmod._lookup(lookup(pages=False), [])["pages"] is False
    assert pmod._lookup({k: v for k, v in lookup().items() if k != "pages"}, [])["pages"] is None      # absent: the use case decides


def _without_pages(**kw):
    return {k: v for k, v in lookup(**kw).items() if k != "pages"}


def test_the_use_case_can_turn_the_wiki_search_on_for_every_lookup_and_a_lookup_can_say_off():
    asked = []
    llm = lambda p: asked.append(p) or "PAGES: none"      # noqa: E731
    gather_with(_without_pages(), llm)                                        # nothing says: off
    assert asked == []
    ev = gather_with(_without_pages(), llm, spec_flag=True)                   # the use case says: on
    assert len(asked) == 1 and ev["lookups"][0]["page_search"]["state"] == "none"
    asked.clear()
    ev = gather_with(lookup(pages=False), llm, spec_flag=True)                # the lookup says: off, whatever the use case says
    assert asked == [] and "page_search" not in ev["lookups"][0]


def test_the_use_case_flag_is_validated_and_an_explicit_false_survives_saving():
    spec = json.loads(json.dumps(SPEC))
    spec["wiki_pages"] = "yes"
    assert "wiki_pages must be true or false." in usecases.validate(spec)
    spec["wiki_pages"] = True
    assert "wiki_pages must be true or false." not in usecases.validate(spec)
    col = spec["stages"][0]["output"]["columns"][0]
    col["lookups"] = [lookup(pages=False), _without_pages()]
    usecases._tidy_descriptions(spec)
    assert col["lookups"][0]["pages"] is False and "pages" not in col["lookups"][1]
