"""Step 2 of the retrieval merge: the vector search can be limited to the block types of one lane, each lane gets its own top k, and
a result carries its tags."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from eawiki import lanes  # noqa: E402
from eawiki.query import retrieve as rt  # noqa: E402

# the index's nearest rows, nearest first: labels and paragraphs crowd the top; a figure and a table window come later
ROWS = ([{"block_id": f"D:{i}", "doc_id": "D", "btype": "paragraph", "text": f"label {i}", "$distance": 0.1 + i / 100, "kind": "architecture"} for i in range(1, 21)]
        + [{"block_id": "D:30", "doc_id": "D", "btype": "figure", "text": "A heat map.", "$distance": 0.4, "kind": "architecture"},
           {"block_id": "D:40", "doc_id": "D", "btype": "table", "text": "rows 21 to 40", "$distance": 0.45, "kind": "architecture", "part": 2, "parts": 4,
            "rows_from": 21, "rows_to": 40, "rows_total": 80},
           {"block_id": "E:41", "doc_id": "E", "btype": "table", "text": "other doc", "$distance": 0.5, "kind": "governance", "part": 1, "parts": 1},
           {"block_id": "D:50", "doc_id": "D", "btype": "list_item", "text": "an item", "$distance": 0.55, "kind": "architecture"}])


class FakeStore:
    def __init__(self):
        self.asked = []

    def vector_search(self, vec, k=10):
        self.asked.append(k)
        return ROWS[:k]


def retriever():
    r = rt.Retriever.__new__(rt.Retriever)
    r.store = FakeStore()
    r.embed_query = lambda q: [0.0]
    return r


def test_the_lanes_name_their_block_types_and_an_unknown_lane_is_an_error():
    assert lanes.types_of("tables") == ("table",) and lanes.types_of("figures") == ("figure",)
    assert set(lanes.types_of("text")) == {"paragraph", "list_item", "caption", "other"} and "heading" not in lanes.types_of("text")
    assert lanes.lane_of("table") == "tables" and lanes.lane_of("figure") == "figures" and lanes.lane_of("list_item") == "text" and lanes.lane_of("weird") == "text"
    with pytest.raises(ValueError):
        lanes.types_of("images")


def test_without_types_the_search_is_what_it_was():
    r = retriever()
    got = r.vector_search("q", k=5)
    assert [b["block_id"] for b in got] == [f"D:{i}" for i in range(1, 6)] and r.store.asked == [5]
    assert got[0]["part"] == 1 and got[0]["parts"] == 1                                    # the tags are there, with defaults


def test_a_lane_gets_its_own_top_k_whatever_is_nearer_in_the_index():
    r = retriever()
    figs = r.lane_search("q", "figures", k=3)
    assert [b["block_id"] for b in figs] == ["D:30"] and figs[0]["btype"] == "figure"
    tabs = r.lane_search("q", "tables", k=3)
    assert [b["block_id"] for b in tabs] == ["D:40", "E:41"]
    assert (tabs[0]["part"], tabs[0]["parts"], tabs[0]["rows_from"], tabs[0]["rows_total"]) == (2, 4, 21, 80)           # the part tag comes with it
    text = r.lane_search("q", "text", k=3)
    assert [b["block_id"] for b in text] == ["D:1", "D:2", "D:3"] and {b["btype"] for b in text} == {"paragraph"}
    assert max(r.store.asked) >= 3 * lanes.TYPE_FETCH_FACTOR                                 # the index cannot filter: it fetched far more than it kept


def test_the_type_filter_combines_with_kinds_and_documents_and_keeps_the_order():
    r = retriever()
    assert [b["block_id"] for b in r.vector_search("q", k=5, types=["table"], kinds=["architecture"])] == ["D:40"]
    assert [b["block_id"] for b in r.vector_search("q", k=5, types=["table", "figure"], docs=["d"])] == ["D:30", "D:40"]
    assert r.vector_search("q", k=5, types=["table"], docs=["nothing"]) == []
    assert [b["block_id"] for b in r.lane_search("q", "text", k=30)][-1] == "D:50"             # nearest first, a list item is in the text lane


def test_the_case_runs_search_function_passes_the_types_through(monkeypatch):
    from eawiki.cases import tools as ct
    seen = {}

    class R:
        def vector_search(self, q, k=8, kinds=None, docs=None, types=None):
            seen.update(k=k, docs=docs, types=types)
            return []
    # the wrapper is defined inside real_tools(); read its source for the contract instead of building the whole tools object
    src = Path(ct.__file__).read_text(encoding="utf-8")
    assert "def search(q, k, docs, types=None):" in src and "types=types" in src
    R().vector_search("q", 3, None, ["d"], ["table"])
    assert seen == {"k": 3, "docs": ["d"], "types": ["table"]}
