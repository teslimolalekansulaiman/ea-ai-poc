"""Ask in deep mode: the retrieval merge. Tables, figures and text are searched on their own, a table found as one part is completed, the image of
a diagram is read for the question, every section says how complete it is, and only what is shown may be cited. The default (fast) mode is
unchanged. No real model or index: the retriever, the page search and the image reader are fakes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ask_wiki import PAGE, PageKB, number  # noqa: E402

from eawiki.query import graph as qg  # noqa: E402

HEADER = "| Capability | Owner |\n|---|---|\n"


def part(n, rows):
    return {"block_id": "D:50", "doc_id": "D", "btype": "table", "section": "5", "ordinal": 5, "part": n, "parts": 3, "rows_from": 1 + (n - 1) * 2,
            "rows_to": n * 2, "rows_total": 6, "text": "D > 5\n" + HEADER + "\n".join(f"| {r} | team {r} |" for r in rows), "distance": 0.2}


TABLE_PARTS = {1: part(1, ["Alpha", "Beta"]), 2: part(2, ["Gamma", "Delta"]), 3: part(3, ["Epsilon", "Zeta"])}
FIGURE = {"block_id": "D:51", "doc_id": "D", "btype": "figure", "section": "7", "ordinal": 9, "text": "D > 7\n\nA heat map of capabilities.", "distance": 0.3}
PARA = {"block_id": "D:52", "doc_id": "D", "btype": "paragraph", "section": "7", "ordinal": 10, "text": "D > 7\nGamma is run by the platform team and was reviewed in March.", "distance": 0.25}


class DeepRetriever:
    def __init__(self, tables=None, figures=None, text=None):
        self.tables = [TABLE_PARTS[2]] if tables is None else tables
        self.figures = [FIGURE] if figures is None else figures
        self.text = [PARA] if text is None else text
        self.lanes_asked = []

    def lane_search(self, q, lane, k=5, kinds=None, docs=None):
        self.lanes_asked.append(lane)
        return [dict(b) for b in {"tables": self.tables, "figures": self.figures}[lane]][:k]

    def vector_search(self, q, k=8, kinds=None, docs=None, types=None):
        self.lanes_asked.append("text" if types else "all")
        return [dict(b) for b in self.text][:k]

    def expand(self, bid, window=1):
        return []

    def blocks_by_ids(self, ids):
        return [dict(p) for i in ids if i == "D:50" for p in TABLE_PARTS.values()]


def deep_state(**kw):
    return {"question": "Who owns Gamma?", "k": 8, "route": {"strategy": "vector"}, "use_llm": True, "deep": True, **kw}


def setup(monkeypatch, retriever, reader=None, picks=None):
    monkeypatch.setattr(qg, "_retriever", lambda: retriever)
    monkeypatch.setattr(qg, "_kb", lambda: PageKB())
    monkeypatch.setattr(qg.ew, "_pages_from_blocks", lambda ids, limit=2: "")
    monkeypatch.setattr(qg, "llm_text", lambda p, backend, model: picks or "PAGES: none")
    monkeypatch.setattr(qg, "_figure_reader", lambda: reader or (lambda bid, prompt: "Gamma is shown in the middle row."))


def test_each_lane_is_searched_on_its_own_and_a_table_found_as_one_part_is_completed(monkeypatch):
    r = DeepRetriever()
    setup(monkeypatch, r)
    out = qg.n_retrieve(deep_state())
    assert r.lanes_asked[:3] == ["tables", "figures", "text"]
    tables = next(sec for sec in out["_merged"].sections if sec.lane == "tables")
    assert [(i.id, i.part) for i in tables.items] == [("D:50", 1), ("D:50", 2), ("D:50", 3)]          # part 2 was found; the small table is whole
    assert "D:50" in out["blocks"] and out["blocks"].count("D:50") == 1
    assert [e["lane"] for e in out["evidence"]] == ["tables", "wiki", "graph", "figures", "text"]


def test_the_context_has_labelled_sections_and_the_image_reading(monkeypatch):
    setup(monkeypatch, DeepRetriever())
    out = qg.n_retrieve(deep_state())
    ctx = qg.n_relevance({**deep_state(), **out})["context"]
    assert ctx.index("TABLES") < ctx.index("WIKI PAGES") < ctx.index("GRAPH FACTS") < ctx.index("FIGURES") < ctx.index("TEXT")
    assert "Read from the image of this diagram" in ctx and "Gamma is shown in the middle row." in ctx
    assert "[D:50] part 2 of 3" in ctx and "Gamma" in ctx
    assert "not searched" in ctx.lower() or "none found" in ctx.lower()                         # the graph lane was not run: it says so


def test_a_failing_image_reader_leaves_the_description_and_does_not_stop_the_answer(monkeypatch):
    def boom(bid, prompt):
        raise RuntimeError("no vision")
    setup(monkeypatch, DeepRetriever(), reader=boom)
    out = qg.n_retrieve(deep_state())
    ctx = qg.n_relevance({**deep_state(), **out})["context"]
    assert "A heat map of capabilities." in ctx and "Read from the image" not in ctx


def test_a_lane_that_finds_nothing_says_so(monkeypatch):
    setup(monkeypatch, DeepRetriever(figures=[], text=[]))
    out = qg.n_retrieve(deep_state())
    ctx = qg.n_relevance({**deep_state(), **out})["context"]
    assert "FIGURES" in ctx and "none found" in ctx.lower()


def test_only_what_is_shown_may_be_cited(monkeypatch):
    setup(monkeypatch, DeepRetriever())
    out = qg.n_retrieve(deep_state())
    state = {**deep_state(), **out, "answer": "Gamma is run by the platform team [D:52] and listed [D:50].", "safety": False}
    assert qg.n_output_guard(state)["citation_check"]["grounded"]
    state["answer"] = "See [D:99]."
    assert not qg.n_output_guard(state)["citation_check"]["grounded"]


def test_a_wiki_page_joins_the_merge_and_may_be_cited(monkeypatch):
    n = number(PageKB().wiki_entries(), "Human Capital")
    setup(monkeypatch, DeepRetriever(), picks=f"PAGES: {n}")
    out = qg.n_retrieve(deep_state())
    ctx = qg.n_relevance({**deep_state(), **out})["context"]
    assert "WIKI PAGES" in ctx and "wiki:human-capital" in ctx
    assert "wiki:human-capital" in out["_merged"].allowed
    assert ctx.count("WIKI PAGES (picked by title") == 0                                       # not shown a second time by the fast path


def test_nothing_found_anywhere_abstains(monkeypatch):
    setup(monkeypatch, DeepRetriever(tables=[], figures=[], text=[]))
    out = qg.n_retrieve(deep_state())
    got = qg.n_relevance({**deep_state(), **out})
    assert got["status"] == "abstained"


def test_the_fast_mode_is_unchanged(monkeypatch):
    class Fast(DeepRetriever):
        def vector_search(self, q, k=8, kinds=None, docs=None, types=None):
            return [dict(PARA)]
    setup(monkeypatch, Fast())
    out = qg.n_retrieve({"question": "q", "k": 3, "route": {"strategy": "vector"}, "use_llm": True})
    assert "_merged" not in out and "evidence" not in out and [b["block_id"] for b in out["_block_objs"]] == ["D:52"]


def test_run_returns_the_evidence_summary_and_not_the_merge_object(monkeypatch):
    setup(monkeypatch, DeepRetriever())
    out = qg.run("Who owns Gamma?", use_llm=False, safety=False, deep=True)
    assert "_merged" not in out and [e["lane"] for e in out["evidence"]][0] == "tables" and "D:50" in out["blocks"]


def test_run_reports_what_the_model_was_given_block_by_block(monkeypatch):
    setup(monkeypatch, DeepRetriever())
    out = qg.run("Who owns Gamma?", use_llm=False, safety=False, deep=True)
    assert {b["block_id"] for b in out["context_blocks"]} >= {"D:50", "D:52"} and all(b["chars"] > 0 for b in out["context_blocks"])


def test_the_prompt_separates_stated_from_worked_out_from_not_found_and_trusts_the_completeness_lines():
    from eawiki.query import answer as ans
    p = ans.build_prompt("Who owns Gamma?", "TABLES (3 shown):\n  [D:50] x", [{"role": "user", "content": "hi"}])
    assert "STATED in the context" in p and "WORKED OUT from more than one piece" in p and "NOT in the context" in p
    assert 'do not say the context "does not explicitly"' in p and "not an apology" in p
    assert "believe it" in p and "could not be searched" in p and "make no statement you cannot cite" in p
    assert "Cite the block id in square brackets" in p and "wiki:payroll-portal" in p                  # the citation rule is kept
    assert p.index("Question: Who owns Gamma?") < p.index("Context:") < p.index("TABLES (3 shown)")
    assert "do not treat it as a source to cite" in p                                                   # the conversation is still not a source
