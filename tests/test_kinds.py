"""A kind of source ("Application to Security Control Matrix") names a section of a document as often as a document: the lookup
searches the documents that have a heading of that name, and says so; a kind nothing matches is said so too."""
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
HEADS = {"Security_Architecture": ["1. Purpose", "4.2 Application to Security Control Matrix", "5. Security Control Catalog"],
         "Standards_Catalogue": ["Data Classification Standard"], "Applications_As-Is": ["Application Catalog"]}


class HeadingKB(kb_tools.FixtureKB):
    def headings(self):
        return HEADS


def run(kinds, docs=None):
    d = kb.DEMANDS[0]
    item = dict(d["item"], _id=d["item"]["demand_id"])
    prof = {g: [] for g in gmod.PROFILE_GROUPS}
    prof["origin"] = "model"
    plan = pmod.default_plan(COLS["Domain"], kb.DOCS)
    plan["lookups"] = [{"find": "controls", "from": "need", "match": "meaning", "in": kinds, "docs": docs or [], "extract": "", "types": [], "relations": [], "pages": False}]
    tools = kb_tools.make_tools()
    tools.kb = HeadingKB()
    tools.doc_ids = lambda: ["Security_Architecture", "Standards_Catalogue", "Applications_As-Is"]
    asked = []
    tools.search = lambda q, k, docs: asked.append(list(docs or [])) or []
    ev = gmod.gather(tools, plan, {**SPEC, "wiki_pages": False}, item, [], {}, None, prof, {}, {})
    return ev, asked, gmod.render(ev)


def test_a_kind_that_is_a_section_name_searches_the_documents_that_have_that_section():
    ev, asked, text = run(["Application to Security Control Matrix"])
    assert asked[0] == ["Security_Architecture"]
    assert "Where to look: “Application to Security Control Matrix”: no document has this name; a section of this name is in Security_Architecture." in text
    assert any(s.startswith("where: “Application to Security Control Matrix”") for s in ev["searched"])


def test_a_kind_nothing_matches_is_said_and_every_document_is_searched():
    ev, asked, text = run(["Contract Register"])
    assert asked[0] == [] and "“Contract Register”: no document or section has this name, so every document is searched." in text


def test_a_kind_that_is_a_document_name_is_left_to_the_name_match():
    ev, asked, text = run(["Standards"], docs=["Standards_Catalogue"])
    assert asked[0] == ["Standards_Catalogue"] and "Where to look" not in text
    ev, asked, text = run(["Standards", "Security Control Catalog"], docs=["Standards_Catalogue"])
    assert sorted(asked[0]) == ["Security_Architecture", "Standards_Catalogue"]                # the name match, plus the section
