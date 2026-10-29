"""Step 4: the case runs use the retrieval merge only when the use case says merge: true. Off, nothing changes; on, a meaning lookup searches tables,
figures and text each on its own, a table found as one part is completed, the evidence is in labelled sections, only what is shown can be cited,
and the result lists the passages by lane and part. Fakes for the index, the model and the table-part fetch."""
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
from eawiki.cases import plan as pmod  # noqa: E402
from eawiki.cases import solve  # noqa: E402

SPEC = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))
COLS = {c["name"]: c for st in SPEC["stages"] for c in st["output"]["columns"]}


def row(bid, btype, text, part=1, parts=1, rf=None, rt=None, total=None, dist=0.3, ordinal=1):
    return {"block_id": bid, "doc_id": "D", "btype": btype, "section": "s", "text": f"D > s\n{text}", "distance": dist, "ordinal": ordinal,
            "part": part, "parts": parts, **({"rows_from": rf, "rows_to": rt, "rows_total": total} if rf else {})}


INDEX = [row("D:1", "paragraph", "Capability", dist=0.1), row("D:2", "paragraph", "The capability model covers HR performance in a group of its own.", dist=0.2),
         row("D:3", "paragraph", "Owner", dist=0.15), row("D:30", "figure", "A heat map. Human Capital (Job Performance) is rated 2.", dist=0.4),
         row("D:40", "table", "Capability | Owner\nJob Performance | OU-11", part=2, parts=3, rf=21, rt=40, total=60, dist=0.45)]


def search_fn(calls):
    def fn(q, k, docs, types=None):
        calls.append((k, tuple(types) if types else None))
        return [dict(r) for r in INDEX if not types or r["btype"] in types][:k]
    return fn


def fetch_parts(block_id, parts):
    return [row(block_id, "table", f"Capability | Owner\nrows of part {p}", part=p, parts=3, rf=(p - 1) * 20 + 1, rt=p * 20, total=60) for p in parts]


def run(merge, calls=None, fetch=fetch_parts, whole=False):
    d = kb.DEMANDS[0]
    item = dict(d["item"], _id=d["item"]["demand_id"])
    prof = {g: [] for g in gmod.PROFILE_GROUPS}
    prof["origin"] = "model"
    plan = pmod.default_plan(COLS["Domain"], kb.DOCS)
    plan["lookups"] = [{"find": "which capability covers HR performance", "from": "need", "match": "meaning", "in": [], "docs": [], "extract": "",
                        "types": [], "relations": [], "pages": False}]
    plan["whole_tables"] = whole
    tools = kb_tools.make_tools()
    tools.search = search_fn(calls if calls is not None else [])
    tools.expand = None
    tools.fetch_parts = fetch
    spec = {**{k: v for k, v in SPEC.items() if k != "wiki_pages"}, "merge": merge}
    return gmod.gather(tools, plan, spec, item, [], {}, None, prof, {}, {})


def test_off_nothing_changes():
    ev = run(False)
    assert "merged" not in ev
    text = gmod.render(ev)
    assert "SOURCE BLOCKS:" in text and "TABLES (" not in text


def test_on_a_meaning_lookup_searches_text_tables_and_figures_each_on_its_own():
    calls = []
    run(True, calls)
    kinds = {t for _, t in calls if t}
    assert ("table",) in kinds and ("figure",) in kinds and ("paragraph", "list_item", "caption", "other") in kinds
    assert not any(t is None for _, t in calls[:3])                                       # no unfiltered search for the lookup itself


def test_on_the_evidence_is_in_labelled_sections_in_priority_order_and_a_table_part_is_completed():
    ev = run(True)
    text = gmod.render(ev)
    assert "SOURCE BLOCKS:" not in text
    heads = [text.index(h) for h in ("TABLES (", "WIKI PAGES (", "GRAPH FACTS (", "FIGURES (", "TEXT (")]
    assert heads == sorted(heads)
    assert "[D:40] part 2 of 3, rows 21 to 40 of 60" in text and "[D:40] part 1 of 3" in text and "[D:40] part 3 of 3" in text      # a small table: all its parts
    assert "[D:30]" in text and "Job Performance" in text
    assert "GRAPH FACTS (not searched for this question)" in text
    assert "Cite a source by the id in brackets" in text


def test_bare_labels_are_set_aside_and_counted_and_only_what_is_shown_can_be_cited():
    ev = run(True)
    text = gmod.render(ev)
    assert "[D:1]" not in text and "[D:3]" not in text and "2 labels set aside" in text
    assert "D:2" in ev["allowed"] and "D:30" in ev["allowed"] and "D:40" in ev["allowed"] and "D:1" not in ev["allowed"]
    assert any(a.startswith("demand:") for a in ev["allowed"])                           # the demand's own fields stay citable


def test_a_table_whose_parts_cannot_be_fetched_is_said_to_be_partial():
    ev = run(True, fetch=None)
    text = gmod.render(ev)
    assert "table [D:40]: parts 2 of 3 shown; rows 21 to 40 of 60 (the other parts could not be fetched)" in text


def test_the_result_lists_the_passages_by_lane_and_part_and_the_evidence_headings():
    ev = run(True)
    how = solve.verify({"name": "P", "type": "text"}, None, ev)["how"]
    lines = [h for h in how if h.startswith("Passage [")]
    assert any("D:40] · tables · part 2 of 3, rows 21 to 40 of 60" in h for h in lines)
    assert any("D:30] · figures ·" in h for h in lines) and any("D:2] · text ·" in h for h in lines)
    assert any(h.startswith("Searched evidence shown: tables (") for h in how)


def test_whole_tables_is_a_property_setting_that_reaches_the_plan_and_the_flags_are_validated():
    col = dict(COLS["Domain"], whole_tables=True)
    assert pmod.default_plan(col, kb.DOCS)["whole_tables"] is True and pmod.default_plan(COLS["Domain"], kb.DOCS)["whole_tables"] is False
    spec = json.loads(json.dumps(SPEC))
    spec["merge"] = "yes"
    assert "merge must be true or false." in usecases.validate(spec)
    spec["merge"] = True
    spec["stages"][0]["output"]["columns"][0]["whole_tables"] = "x"
    assert any("whole_tables must be true or false." in e for e in usecases.validate(spec))
