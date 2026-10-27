"""Step 4 of the page finder: reading the wiki page of each candidate. No model."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402

from eawiki.cases import namelookup as nl  # noqa: E402
from eawiki.cases import wikiread as wr  # noqa: E402


def test_a_model_written_page_gives_its_opening_prose_and_its_bullets_without_citations():
    d = wr.digest_page(kb.page("peoplex-hr-system"))
    assert d["title"] == "Peoplex HR System" and d["type"] == ""                 # a model page states no type: the graph does
    assert d["summary"].startswith("Core HR records, leave and the monthly payroll export.") and d["summary_from"] == "first paragraph"
    assert "[Application_Catalog" not in d["summary"] and "catalogued as C-204" in d["lead"] and "HR Systems Lead" in d["lead"]
    assert "Peoplex HR System is deployed on Oracle Database Platform" in d["facts"] and "[" not in d["facts"]
    assert not d["empty"]


def test_a_page_built_from_a_table_gives_its_type_attributes_and_relationships():
    d = wr.digest_page(kb.page("leave-and-attendance-records"))
    assert d["type"] == "data entity" and d["summary"] == "" and d["summary_from"] == "" and "listed in" not in d["lead"]
    assert "Classification: Confidential" in d["facts"] and "Owner role: HR Data Steward" in d["facts"]
    assert "Peoplex HR System accesses Leave and Attendance Records" in d["facts"]


def test_an_item_listed_only_on_a_catalogue_page_is_read_from_its_own_section():
    md = kb.page("security-audit-logs")
    assert md.startswith("# Security Audit Logs") and "Published Policies" not in md                  # not the neighbour's section
    d = wr.digest_page(md)
    assert d["type"] == "data entity" and "Classification: Restricted" in d["facts"]
    assert kb.page("no-such-page") is None


def test_a_real_page_from_the_wiki_gives_what_it_is_first_and_its_relationships_in_full():
    """tests/fixtures/real_page_hr_portal.md: a page shown by the owner; its markup is reconstructed from the rendered text."""
    d = wr.digest_page((ROOT / "tests" / "fixtures" / "real_page_hr_portal.md").read_text(encoding="utf-8"))
    assert d["title"] == "HR & Payroll Portal" and d["type"] == ""
    assert d["summary_from"] == "page" and d["summary"].startswith("The HR & Payroll Portal is an internal application")     # its own Summary
    assert d["lead"].startswith("The portal handles HR and payroll. It took over from the older HR Legacy System")       # then "What it is"
    assert "Applications_As-Is" not in d["summary"] + d["lead"] + d["facts"] and "[" not in d["summary"] + d["lead"] + d["facts"]
    assert len(d["summary"]) <= wr.SUMMARY_CHARS and len(d["lead"]) <= wr.LEAD_CHARS
    for neighbour in ("Evaluate:", "Attendance:", "HR Legacy System:"):
        assert neighbour in d["facts"]
    assert "through API or Excel files" in d["facts"]
    assert wr.digest_page("# T\n\n## T\n\nbody")["summary"] == "body"                                                # the repeated name is not prose


def test_a_bare_block_id_is_a_citation_and_a_time_is_not():
    assert wr.strip_citations("It hosts it [Doc_A-B:39][Doc_A-B:84]. Also Doc_A-B:81Doc_A-B:84 here at 10:30, ratio 3:1.") == "It hosts it. Also here at 10:30, ratio 3:1."


def test_the_digest_does_not_depend_on_any_heading_and_survives_odd_pages():
    assert wr.digest_page("")["empty"] and wr.digest_page("# Only a title")["empty"]
    d = wr.digest_page("# X\n\nType: application\n\nOne line of prose.\n\n## Whatever the model called it\n\n1. first\n2. second")
    assert d["type"] == "application" and d["summary"] == "One line of prose." and d["summary_from"] == "first paragraph" and d["facts"] == "first; second"
    long = wr.digest_page("# X\n\n" + ("A sentence that goes on. " * 100) + "\n\n" + "\n".join(f"- fact {i}" for i in range(40)))
    assert len(d["lead"]) <= wr.LEAD_CHARS and len(long["lead"]) <= wr.LEAD_CHARS and len(long["facts"]) <= wr.FACT_CHARS
    assert long["facts"].count(";") + 1 == wr.MAX_FACTS or len(long["facts"]) == wr.FACT_CHARS


def test_a_page_with_a_summary_section_uses_it_and_one_without_is_marked():
    with_s = wr.digest_page("# X\n\n## Summary\n\nX is a thing.\n\n## What it is\n\nIt does stuff.")
    assert with_s["summary"] == "X is a thing." and with_s["summary_from"] == "page" and with_s["lead"] == "It does stuff."
    without = wr.digest_page("# X\n\nX is a thing.\n\n## What it is\n\nIt does stuff.")
    assert without["summary"] == "It does stuff." and without["summary_from"] == "first paragraph"      # the preferred prose stands in
    none = wr.digest_page("# X\n\n## Relationships\n\n- a\n- b")
    assert none["summary"] == "" and none["summary_from"] == "" and none["facts"] == "a; b" and not none["empty"]


def test_the_page_writer_always_asks_for_a_summary_and_pages_built_in_code_have_one():
    from eawiki import pages
    assert "ALWAYS a '## Summary' section" in pages._page_prompt({"name": "X", "type": "application", "kind": "entity", "block_ids": []}, {}, {"edges": [], "attributes": []}, json.loads((ROOT / "data" / "togaf92_metamodel.json").read_text(encoding="utf-8")))
    sub = {"name": "Leave Data", "type": "data_entity", "block_ids": []}
    facts = {"edges": [], "attributes": [{"subject": "Leave Data", "name": "Owner", "value": "HR"}]}
    stub = pages._stub_page(sub, {}, facts)["page_markdown"]
    d = wr.digest_page(stub)
    assert "## Summary" in stub and d["summary_from"] == "page" and d["summary"].startswith("Leave Data is a data_entity listed in the source tables.")
    assert "1 attribute and 0 relationships" in d["summary"]
    item = "\n".join(pages._item_section(sub, "Data_Catalog:3", facts))
    assert wr.digest_page("# Leave Data\n\n" + item.split("\n", 1)[1])["summary"].startswith("Leave Data is a data_entity listed in the catalogue")


def test_inline_citations_are_removed_so_the_answer_cannot_cite_what_it_was_not_shown():
    assert wr.strip_citations("It is a system [03-data:5] and holds data [A_B:1, C:22].") == "It is a system and holds data."
    assert wr.strip_citations("A [note] stays [x]") == "A [note] stays [x]"


def cand(node_id, how="alias"):
    n = kb.NODE_BY_ID[node_id]
    return {"id": node_id, "name": n["name"], "type": n["type"], "how": how, "slug": n["slug"]}


def test_only_the_best_candidates_of_a_mention_are_read_and_the_rest_are_marked_not_read():
    r = wr.read({"HR system": [cand("C-204"), cand("C-207", "only part of its name"), cand("C-208", "x"), cand("C-206", "x")]}, kb.page)
    assert [p["slug"] for p in r["pages"]] == ["peoplex-hr-system", "hr-payroll-portal", "hr-legacy-system"]
    assert r["status"]["HR system"] == {"C-204": "read", "C-207": "read", "C-208": "read", "C-206": "not read"}
    assert r["pages"][0]["id"] == "wiki:peoplex-hr-system" and r["pages"][0]["how"] == "alias"


def test_a_page_shared_by_two_mentions_is_kept_once_and_the_total_is_capped():
    r = wr.read({"HR system": [cand("C-204")], "Peoplex": [cand("C-204")]}, kb.page)
    assert len(r["pages"]) == 1 and r["status"]["Peoplex"] == {"C-204": "read"}
    many = {f"m{i}": [cand(nid)] for i, nid in enumerate(["C-201", "C-202", "C-203", "C-204", "C-205", "C-206", "C-207", "C-208", "C-209", "C-210"])}
    r = wr.read(many, kb.page, total=8)
    assert len(r["pages"]) == 8 and [s for m in r["status"].values() for s in m.values()].count("not read") == 2


def test_no_page_and_an_unreadable_page_are_told_apart():
    no_slug = {"id": "x", "name": "X", "type": "", "how": "chosen by the page finder", "slug": None}
    gone = {"id": "y", "name": "Y", "type": "", "how": "alias", "slug": "gone"}
    broken = {"id": "z", "name": "Z", "type": "", "how": "alias", "slug": "broken"}

    def fn(slug):
        if slug == "broken":
            raise OSError("bucket down")
        return kb.page(slug)
    r = wr.read({"m": [no_slug, gone, broken]}, fn)
    assert r["pages"] == [] and r["status"]["m"] == {"x": "no page", "y": "no page", "z": "error"}


def test_step1_candidates_carry_the_page_slug():
    c = nl.resolve_entities("HR system", kb.NODES, kinds=["app"])[0]
    assert c["slug"] == "peoplex-hr-system" and wr.read({"HR system": [c]}, kb.page)["pages"][0]["digest"]["title"] == "Peoplex HR System"


class FakeStore:
    """The file store's two calls, over the fixture's pages."""
    def __init__(self):
        import json
        self.files = {f"pages/{slug}.md": md for slug, md in kb.PAGES.items()}
        self.files["graph/page_redirects.json"] = json.dumps(kb.PAGE_REDIRECTS)

    def read_text(self, key):
        return self.files.get(key)

    def list(self, prefix, ext):
        return sorted(k for k in self.files if k.startswith(prefix + "/") and k.endswith(ext))


def test_the_real_page_reader_returns_own_pages_and_catalogue_sections_alike():
    from eawiki.cases.tools import wiki_entries_from, wiki_page_from
    fs = FakeStore()
    assert wiki_page_from(fs, "peoplex-hr-system") == kb.page("peoplex-hr-system")
    assert wiki_page_from(fs, "security-audit-logs") == kb.page("security-audit-logs") and wiki_page_from(fs, "nope") is None
    assert wiki_page_from(fs, "../peoplex-hr-system") == kb.page("peoplex-hr-system")                       # a slug is a name, not a path
    entries = wiki_entries_from(fs)
    assert len(entries) == len(kb.NODES) and not any(e["slug"].startswith("catalogue-") for e in entries)
    assert {e["title"] for e in entries} == {n["name"] for n in kb.NODES}
    assert next(e for e in entries if e["slug"] == "published-policies")["type"] == "data entity"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  passed", name)
    print("ok")
