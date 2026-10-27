"""A search by meaning set behind real passages the hits that are only a label (a column name, a header with no row), and
follows each of the first few with the passages next to it in its document."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eawiki.cases import gather as gmod  # noqa: E402
from eawiki.cases import passages as ps  # noqa: E402

DOC = "Biz_Arch"
HEADER_ONLY = f"{DOC} > Capability map\n\n| Capability | Group |\n|---|---|"
WITH_ROWS = f"{DOC} > Capability map\n\n| Capability | Group |\n|---|---|\n| Workforce Planning | Human Capital Management |\n| Strategic Planning | Planning |"
SENTENCE = "The payroll interface sends each approved evaluation to the payroll system every month."


def blk(n, text, btype="paragraph"):
    return {"block_id": f"{DOC}:{n}", "doc_id": DOC, "btype": btype, "section": "s", "text": text, "ordinal": n}


STORE = [blk(1, f"{DOC} > Capability map\nCapability"), blk(2, WITH_ROWS, "table"), blk(3, "Owner set"), blk(4, SENTENCE),
         blk(5, HEADER_ONLY, "table"), blk(6, f"{DOC} > Strategy\nObjective"), blk(7, WITH_ROWS, "table")]


def expand(block_id, window=1):
    n = int(block_id.split(":")[1])
    return [dict(b) for b in STORE if abs(b["ordinal"] - n) <= window]


def test_what_counts_as_a_fragment():
    assert ps.is_fragment(STORE[0]) and ps.is_fragment(STORE[2])                      # a label
    assert ps.is_fragment(STORE[4])                                                    # a table with a header and no row
    assert not ps.is_fragment(STORE[1]) and not ps.is_fragment(STORE[3])               # rows; a sentence
    assert not ps.is_fragment(blk(9, "A short sentence, with a verb."))
    assert not ps.is_fragment(blk(9, "x " * 40))                                       # long


def test_real_passages_come_first_and_fragments_only_fill_a_short_list():
    hits = [STORE[0], STORE[2], STORE[3], STORE[1]]
    out, frag, added = ps.reshape(hits, 2)
    assert [b["block_id"] for b in out] == [f"{DOC}:4", f"{DOC}:2"] and frag == 2 and added == 0
    out, _, _ = ps.reshape([STORE[0], STORE[2], STORE[3]], 3)
    assert [b["block_id"] for b in out] == [f"{DOC}:4", f"{DOC}:1", f"{DOC}:3"]       # too few real ones: labels fill the list


def test_a_label_is_followed_by_what_comes_after_it_not_what_comes_before():
    out, frag, added = ps.reshape([STORE[4]], 3, expand)
    ids = [b["block_id"] for b in out]
    assert frag == 1 and added == 1 and ids[0] == f"{DOC}:5"
    assert f"{DOC}:6" not in ids                                                       # a label (Objective) is no help; it is skipped
    assert f"{DOC}:7" in ids and next(b for b in out if b["block_id"] == f"{DOC}:7")["via"] == f"{DOC}:5"
    assert f"{DOC}:3" not in ids                                                       # before the label: not taken


def test_a_neighbour_is_never_added_twice_and_the_outside_hits_are_kept():
    out, _, added = ps.reshape([STORE[0], dict(STORE[3], outside=True)], 3, expand)
    assert [b["block_id"] for b in out].count(f"{DOC}:2") == 1 and added == 1 and any(b.get("outside") for b in out)


def test_a_failing_expand_changes_nothing():
    def boom(*_):
        raise RuntimeError("down")
    out, frag, added = ps.reshape([STORE[0], STORE[3]], 3, boom)
    assert added == 0 and frag == 1


def lookup(match):
    return {"find": "the capabilities this belongs to", "from": "need", "match": match, "in": [], "docs": [], "types": [], "relations": []}


def test_read_by_meaning_reshapes_and_reports_it():
    search = lambda q, k, docs: [dict(STORE[0]), dict(STORE[4]), dict(STORE[3])][:k]      # noqa: E731
    res = ps.read(lookup("meaning"), [None], "payroll evaluation", search, None, False, expand)
    it = res["items"][0]
    assert it["fragments"] == 2 and it["expanded"] >= 1 and it["state"] == "found"
    ids = [b["block_id"] for b in res["blocks"]]
    assert ids[0] == f"{DOC}:4" and f"{DOC}:7" in ids


def test_read_by_name_is_untouched():
    search = lambda q, k, docs: [dict(STORE[0]), dict(STORE[3])]                           # noqa: E731
    res = ps.read(lookup("name"), ["Evaluate"], "x", search, None, False, expand)
    it = res["items"][0]
    assert it["fragments"] == 0 and it["expanded"] == 0 and [b["block_id"] for b in res["blocks"]] == [f"{DOC}:1", f"{DOC}:4"]


def test_the_answer_step_is_told_which_passage_followed_a_label():
    ev = {"demand": {}, "lookups": [], "wiki": [], "graph_reads": [], "graph": None, "others": [], "used": [],
          "blocks": [dict(STORE[6], via=f"{DOC}:5"), STORE[3]]}
    text = gmod.render(ev)
    assert f"[{DOC}:7] (the passage after [{DOC}:5], which was only a label)" in text and f"[{DOC}:4] The payroll interface" in text
