"""The six steps for one lookup, inside gather, on the test knowledge base (lexical search stand-in). No model."""
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

SPEC = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))
COLS = {c["name"]: c for st in SPEC["stages"] for c in st["output"]["columns"]}


def gather(col, mentions, llm_text=None, decided=None, group="systems"):
    d = kb.DEMANDS[0]
    item = dict(d["item"], _id=d["item"]["demand_id"])
    prof = {g: [] for g in gmod.PROFILE_GROUPS}
    prof[group] = [{"text": m, "field": "x"} for m in mentions]
    prof["origin"] = "model"
    plan = pmod.default_plan(COLS[col], kb.DOCS)
    return gmod.gather(kb_tools.make_tools(llm_text=llm_text), plan, SPEC, item, [], {}, None, prof, decided or {}, {})


def test_a_name_with_an_entry_shows_its_entity_its_wiki_page_its_graph_links_and_its_catalog_row():
    ev = gather("Impacted application", ["HR system"])
    text = gmod.render(ev)
    assert '"HR system": HAS AN ENTRY: [wiki:peoplex-hr-system] Peoplex HR System (application; alias "HR system")' in text
    assert "wiki:peoplex-hr-system" in ev["allowed"] and "Application_Catalog:4" in ev["allowed"]
    assert "WIKI PAGES" in text and "[wiki:peoplex-hr-system] Peoplex HR System." in text and "catalogued as C-204" in text
    assert "WHAT THE GRAPH LINKS THEM TO" in text and "Peoplex HR System --sends_data_to--> HR & Payroll Portal" in text
    assert "Peoplex HR System --is_deployed_on--> Oracle Database Platform" not in text         # not a relationship this lookup asks about
    assert "Also exists as another kind of thing (not offered as a candidate): HR (data set)" in text


def test_a_partial_name_is_not_an_entry_and_a_name_with_nothing_says_so_with_its_reason():
    text = gmod.render(gather("Impacted application", ["payroll", "website forms", "spreadsheets"], lambda p: "M1: none\nM2: none\nM3: none"))
    assert '"payroll": NO entry of its own. Closest, not confirmed: [wiki:hr-payroll-portal] HR & Payroll Portal (application; only part of its name)' in text
    assert '"website forms": NO entry of its own. It is only mentioned inside: [Initiative_Portfolio:5]' in text       # a project's text, not an entry
    assert '"spreadsheets": NO entry and no passage names it' in text and "could not be asked" not in text


def test_a_name_no_word_settles_goes_to_the_page_finder_whose_pick_is_never_called_an_entry():
    asked = []

    def llm_text(p):
        asked.append(p)
        n = next(int(ln[1:ln.index("]")]) for ln in p.splitlines() if ln.startswith("[") and "Attendance Devices Gateway" in ln)
        return f"M1: {n}"
    ev = gather("Impacted application", ["staff clock-in machines"], llm_text)
    text = gmod.render(ev)
    assert len(asked) == 1 and 'M1: "staff clock-in machines"' in asked[0].replace('M1: "', 'M1: "')
    assert '"staff clock-in machines": NO entry of its own. Closest, not confirmed: [wiki:attendance-devices-gateway] Attendance Devices Gateway (application; chosen by the page finder)' in text
    assert "wiki:attendance-devices-gateway" in ev["allowed"]
    gather("Impacted application", ["staff clock-in machines"], llm_text)                       # a new gather, a new cache: asks again
    assert len(asked) == 2


def test_the_page_finder_is_asked_once_for_a_name_that_two_lookups_share():
    asked = []
    d = kb.DEMANDS[0]
    item = dict(d["item"], _id=d["item"]["demand_id"])
    prof = {g: [] for g in gmod.PROFILE_GROUPS}
    prof["systems"] = [{"text": "staff clock-in machines", "field": "x"}]
    prof["origin"] = "model"
    plan = pmod.default_plan(COLS["Impacted application"], kb.DOCS)
    assert len([lk for lk in plan["lookups"] if lk["from"] == "systems"]) == 2
    tools = kb_tools.make_tools(llm_text=lambda p: asked.append(p) or "M1: none")
    gmod.gather(tools, plan, SPEC, item, [], {}, None, prof, {}, {})
    assert len(asked) == 1                         # one question: the picks do not depend on the kind a lookup accepts, which is applied afterwards


def test_when_the_page_finder_cannot_answer_the_text_says_so_instead_of_claiming_there_is_no_entry():
    text = gmod.render(gather("Impacted application", ["staff clock-in machines"], lambda p: None))
    assert "The page finder could not be asked about this name" in text


def test_a_lookup_that_starts_from_an_earlier_answer_looks_up_the_names_in_it():
    ev = gather("Owners", [], decided={"Impacted application": ["Peoplex HR System (C-204)"], "Linked security capability": ["Data Protection"]})
    text = gmod.render(ev)
    assert '"Peoplex HR System": HAS AN ENTRY' in text and '"C-204": HAS AN ENTRY' in text and '"Data Protection": HAS AN ENTRY' in text
    assert "HR Systems Lead" in text and "Lead Security Architect" in text


def test_a_meaning_lookup_reports_closest_passages_and_never_an_entry():
    text = gmod.render(gather("Domain", [], group="systems"))
    assert "closest passages" in text or "no passage came back" in text
    assert "HAS AN ENTRY" not in text.split("closest passages")[-1] if "closest passages" in text else True


def test_a_search_that_fails_is_reported_as_failed_not_as_nothing():
    d = kb.DEMANDS[0]
    item = dict(d["item"], _id=d["item"]["demand_id"])
    prof = {g: [] for g in gmod.PROFILE_GROUPS}
    prof["systems"] = [{"text": "HR system", "field": "x"}]
    prof["origin"] = "model"
    tools = kb_tools.make_tools()
    tools.search = lambda q, k, docs: (_ for _ in ()).throw(OSError("vector store down"))
    ev = gmod.gather(tools, pmod.default_plan(COLS["Impacted application"], kb.DOCS), SPEC, item, [], {}, None, prof, {}, {})
    assert "THE DOCUMENT SEARCH FAILED for this name" in gmod.render(ev)


def test_without_a_knowledge_base_gather_behaves_as_before():
    d = kb.DEMANDS[0]
    item = dict(d["item"], _id=d["item"]["demand_id"])
    tools = kb_tools.make_tools()
    tools.kb = None
    prof = {g: [] for g in gmod.PROFILE_GROUPS}
    prof["systems"] = [{"text": "HR system", "field": "x"}]
    prof["origin"] = "model"
    ev = gmod.gather(tools, pmod.default_plan(COLS["Impacted application"], kb.DOCS), SPEC, item, [], {}, None, prof, {}, {})
    assert ev["wiki"] == [] and ev["graph_reads"] == [] and ev["lookups"] and "new" not in ev["lookups"][0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  passed", name)
    print("ok")
