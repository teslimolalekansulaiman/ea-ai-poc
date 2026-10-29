"""Step 1 of the retrieval merge: every embedded unit says which piece of its block it is (part of parts) and, for a table, which rows it
holds; the loaded vertex carries it; a search result carries it, with defaults for rows loaded before the tags existed."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eawiki import embed, load  # noqa: E402
from eawiki.blocks import Block  # noqa: E402
from eawiki.query import retrieve as rt  # noqa: E402


def block(btype, text, ordinal=5, desc="A description.", figure=None, table=None):
    return Block(block_id=f"D:{ordinal}", doc_id="D", source_file="x", ordinal=ordinal, type=btype, text=text, section_path=["4. S"],
                 description=desc, figure=figure, table=table)


def md_table(n):
    return "| **Name** | **Owner** |\n|---|---|\n" + "\n".join(f"| Capability {i:03d} with a long enough text to fill | OU-{i % 9} |" for i in range(n))


def test_a_paragraph_a_long_paragraph_and_a_figure_carry_their_part_of_parts():
    u = embed.embeddable_units([block("paragraph", "A short paragraph.")])[0]
    assert (u["part"], u["parts"]) == (1, 1) and "rows_total" not in u
    long = embed.embeddable_units([block("paragraph", "word " * 700)])
    assert len(long) > 1 and [x["part"] for x in long] == list(range(1, len(long) + 1)) and {x["parts"] for x in long} == {len(long)}
    fig = embed.embeddable_units([block("figure", "", figure={"caption": "", "image_path": "x.png"})])[0]
    assert (fig["part"], fig["parts"]) == (1, 1)


def test_a_short_table_is_part_1_of_1_with_its_row_count():
    u = embed.embeddable_units([block("table", md_table(8))])[0]
    assert (u["part"], u["parts"], u["rows_from"], u["rows_to"], u["rows_total"]) == (1, 1, 1, 8, 8)


def test_the_windows_of_a_long_table_say_which_rows_they_hold():
    units = embed.embeddable_units([block("table", md_table(60))])
    n = len(units)
    assert n > 2 and [u["part"] for u in units] == list(range(1, n + 1)) and {u["parts"] for u in units} == {n}
    assert units[0]["rows_from"] == 1 and units[-1]["rows_to"] == 60 and {u["rows_total"] for u in units} == {60}
    for a, b in zip(units, units[1:]):
        assert b["rows_from"] == a["rows_to"] + 1                                        # no gap, no overlap
    assert all(f"(rows {u['rows_from']} to {u['rows_to']} of 60)" in u["text"] for u in units)


def test_the_loaded_vertex_carries_the_tags_and_leaves_out_a_row_range_that_does_not_exist():
    u = embed.embeddable_units([block("table", md_table(60))])[2]
    doc = load.block_doc({**u, "embedding": [0.1]})
    assert doc["part"] == 3 and doc["parts"] == len(embed.embeddable_units([block("table", md_table(60))])) and doc["rows_total"] == 60
    assert doc["btype"] == "table" and doc["block_id"] == "D:5" and doc["embedding"] == [0.1]
    old = load.block_doc({"id": "D:1", "block_id": "D:1", "doc_id": "D", "type": "paragraph", "text": "x"})          # a record made before the tags
    assert old["part"] == 1 and old["parts"] == 1 and "rows_from" not in old


def test_a_search_result_carries_the_tags_with_defaults_for_old_rows():
    assert rt.tags({"part": 2, "parts": 4, "rows_from": "21", "rows_to": 40, "rows_total": 120}) == {"part": 2, "parts": 4, "rows_from": 21, "rows_to": 40, "rows_total": 120}
    assert rt.tags({"block_id": "D:1"}) == {"part": 1, "parts": 1}
    assert rt.tags({"part": None, "parts": None}) == {"part": 1, "parts": 1}


class FakeStore:
    def __init__(self, rows, fail_new=False):
        self.rows, self.fail_new, self.sql = rows, fail_new, []

    def query(self, sql, params=None):
        self.sql.append(sql)
        if self.fail_new and "part" in sql:
            raise RuntimeError("unknown property")                                      # an index loaded before the tags
        return [dict(r) for r in self.rows]


def retriever(store):
    r = rt.Retriever.__new__(rt.Retriever)
    r.store = store
    return r


def test_blocks_by_ids_and_expand_return_the_tags_and_fall_back_on_an_old_index():
    rows = [{"block_id": "D:5", "btype": "table", "section": "s", "text": "t", "ordinal": 5, "doc_id": "D", "part": 2, "parts": 4, "rows_from": 21, "rows_to": 40, "rows_total": 80}]
    got = retriever(FakeStore(rows)).blocks_by_ids(["D:5"])
    assert got[0]["part"] == 2 and got[0]["parts"] == 4 and got[0]["rows_total"] == 80
    old = retriever(FakeStore([{"block_id": "D:5", "btype": "paragraph", "section": "s", "text": "t", "ordinal": 5, "doc_id": "D"}], fail_new=True))
    got = old.blocks_by_ids(["D:5"])
    assert got == [{"block_id": "D:5", "btype": "paragraph", "section": "s", "text": "t", "ordinal": 5, "doc_id": "D", "part": 1, "parts": 1}]
    assert len(old.store.sql) == 2                                                      # the new query failed, the old one answered
    assert retriever(FakeStore(rows)).blocks_by_ids([]) == []
