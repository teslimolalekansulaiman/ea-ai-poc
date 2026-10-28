"""Ask reads wiki pages picked by title and summary for the question, sets bare labels aside, reads what follows a label, brings the
diagram of a caption, and accepts a wiki page as a citation. No real model or index: the retriever and the model are fakes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402
import kb_tools  # noqa: E402

from eawiki.cases import pagefinder as pf  # noqa: E402
from eawiki.query import answer as ans  # noqa: E402
from eawiki.query import graph as qg  # noqa: E402
from eawiki.query import guardrails as det  # noqa: E402
from eawiki.query import wikisearch as ws  # noqa: E402

PAGE = "# Human Capital\n\n## Summary\nThe capability group for staff.\n\n## Capabilities\n- Workforce Planning (O1.1)\n- Job Performance (O1.3)\n- Training (O1.4)\n"


class PageKB(kb_tools.FixtureKB):
    def wiki_entries(self):
        return super().wiki_entries() + [pf.page_item("human-capital", PAGE)]

    def page(self, slug):
        return PAGE if slug == "human-capital" else super().page(slug)


def number(entries, title):
    return next(i for i, p in enumerate(entries, 1) if p["title"] == title)


def test_wiki_pages_and_blocks_are_both_citations():
    got = det.cited_ids("It is O1.3 [wiki:human-capital] and the table says so [01_Biz-v0.2:733, wiki:2027-roadmap] [x y:5].")
    assert got == {"wiki:human-capital", "01_Biz-v0.2:733", "wiki:2027-roadmap", "x y:5"}
    ok = det.verify_citations("See [wiki:human-capital].", {"wiki:human-capital"})
    assert ok["grounded"] and ok["invalid"] == []
    bad = det.verify_citations("See [wiki:made-up].", {"wiki:human-capital"})
    assert not bad["grounded"] and bad["invalid"] == ["wiki:made-up"]


def test_the_page_search_is_asked_with_the_question_alone_and_reads_the_page_for_it():
    seen = []
    k = PageKB()
    n = number(k.wiki_entries(), "Human Capital")
    res = ws.pages_for("Which capability covers job performance?", lambda p: seen.append(p) or f"PAGES: {n}", k)
    assert "QUESTION: Which capability covers job performance?" in seen[0] and "THE DEMAND" not in seen[0] and "Someone asks a question" in seen[0]
    assert res["state"] == "picked" and res["pages"][0]["id"] == "wiki:human-capital"
    assert "Job Performance (O1.3)" in res["pages"][0]["digest"]["body"]
    assert ws.pages_for("q", lambda p: "no idea", k)["state"] == "unread"
    assert ws.pages_for("q", lambda p: "PAGES: none", k)["state"] == "none"


def test_the_parts_of_a_long_list_are_asked_together_and_their_order_is_kept():
    pages = [{"slug": f"p{i}", "title": f"Page {i}", "type": "", "summary": ""} for i in range(1, 13)]
    order = []
    def llm(p):
        order.append(1)
        return "PAGES: 1" if "Page 1\n" in p or "[1] Page 1" in p else "PAGES: none"
    got = pf.find_pages("q", "", pages, llm, max_items=4, workers=3)
    assert got["state"] == "picked" and [c["slug"] for c in got["picks"]] == ["p1"] and len(order) == 3


class FakeRetriever:
    BLOCKS = [
        {"block_id": "D:1", "doc_id": "D", "btype": "paragraph", "section": "7.2", "ordinal": 1, "text": "D > 7.2\nCapability", "distance": 0.2},
        {"block_id": "D:2", "doc_id": "D", "btype": "figure", "section": "7.2", "ordinal": 2, "text": "D > 7.2\n\nA heat map. Human Capital (Job Performance) is rated 2.", "distance": 0.4},
        {"block_id": "D:3", "doc_id": "D", "btype": "paragraph", "section": "7.2", "ordinal": 3, "text": "D > 7.2\nFigure 7: Capability map: supporting - operational", "distance": 0.3},
    ]

    def vector_search(self, q, k=8, kinds=None, docs=None):
        return [dict(self.BLOCKS[0]), dict(self.BLOCKS[2])][:k]                            # the label and the caption; the diagram itself is not a hit

    def expand(self, bid, window=1):
        n = int(bid.split(":")[1])
        return [dict(b) for b in self.BLOCKS if abs(b["ordinal"] - n) <= window]

    def blocks_by_ids(self, ids):
        return []


def run_retrieve(monkeypatch, llm_answer):
    monkeypatch.setattr(qg, "_retriever", lambda: FakeRetriever())
    monkeypatch.setattr(qg, "_kb", lambda: PageKB())
    monkeypatch.setattr(qg.ew, "_pages_from_blocks", lambda ids, limit=2: "")
    monkeypatch.setattr(qg, "llm_text", lambda p, backend, model: llm_answer)
    return qg.n_retrieve({"question": "Which capability covers job performance?", "k": 3, "route": {"strategy": "vector"}, "use_llm": True})


def test_ask_sets_the_label_aside_reads_what_follows_it_and_reads_the_picked_page(monkeypatch):
    n = number(PageKB().wiki_entries(), "Human Capital")
    out = run_retrieve(monkeypatch, f"PAGES: {n}")
    ids = [b["block_id"] for b in out["_block_objs"]]
    assert "D:1" not in ids and "D:3" in ids and "D:2" in ids                               # the label is out; the caption and the diagram after it are in
    assert [w["id"] for w in out["wiki_pages"]] == ["wiki:human-capital"] and out["wiki_search"]["state"] == "picked"
    ctx = ans.assemble_context(out["_block_objs"])
    assert "A heat map. Human Capital (Job Performance) is rated 2." in ctx                  # the diagram's description reaches the answer step
    assert "which was only a label" in ctx                                                    # what follows the label D:1 is read as one passage


def test_a_page_search_that_fails_does_not_stop_the_answer(monkeypatch):
    def boom(p, backend, model):
        raise RuntimeError("down")
    monkeypatch.setattr(qg, "_retriever", lambda: FakeRetriever())
    monkeypatch.setattr(qg, "_kb", lambda: PageKB())
    monkeypatch.setattr(qg.ew, "_pages_from_blocks", lambda ids, limit=2: "")
    monkeypatch.setattr(qg, "llm_text", boom)
    out = qg.n_retrieve({"question": "q", "k": 3, "route": {"strategy": "vector"}, "use_llm": True})
    assert out["wiki_pages"] == [] and out["blocks"]
    out = qg.n_retrieve({"question": "q", "k": 3, "route": {"strategy": "global"}, "use_llm": True})
    assert out["wiki_pages"] == []                                                              # a whole-landscape question uses the summaries


def test_the_context_names_the_wiki_pages_and_the_answer_may_cite_them():
    state = {"question": "q", "route": {"strategy": "vector"}, "_block_objs": [], "wiki_pages": [
        {"id": "wiki:human-capital", "name": "Human Capital", "digest": {"summary": "The capability group.", "body": "Job Performance (O1.3)"}}]}
    ctx = qg.n_relevance(state)
    assert "WIKI PAGES" in ctx["context"] and "[wiki:human-capital] Human Capital." in ctx["context"] and "Job Performance (O1.3)" in ctx["context"]
    state.update(context=ctx["context"], answer="It is Job Performance [wiki:human-capital].", use_llm=True, safety=False)
    out = qg.n_output_guard(state)
    assert out["citation_check"]["grounded"] and out["status"] == "answered"
