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


def test_real_passages_are_kept_and_bare_labels_are_not_used_to_fill_the_list():
    hits = [STORE[0], STORE[2], STORE[3], STORE[1]]
    out, frag, added = ps.reshape(hits, 2)
    assert [b["block_id"] for b in out] == [f"{DOC}:4", f"{DOC}:2"] and frag == 2 and added == 0
    out, frag, _ = ps.reshape([STORE[0], STORE[2], STORE[3]], 3)
    assert [b["block_id"] for b in out] == [f"{DOC}:4"] and frag == 2                 # too few real ones: the list is short, not padded with labels
    out, frag, _ = ps.reshape([STORE[0], STORE[2]], 3)
    assert out == [] and frag == 2


def test_a_label_is_followed_by_what_comes_after_it_not_what_comes_before():
    out, frag, added = ps.reshape([STORE[4]], 3, expand)
    assert frag == 1 and added == 1 and f"{DOC}:5" not in [b["block_id"] for b in out]      # the label itself goes: its run says more
    run = next(b for b in out if b.get("via"))
    assert run["via"] == f"{DOC}:5" and run["block_id"] == f"{DOC}:6" and run["run_to"] == f"{DOC}:7"
    assert "Objective" in run["text"] and "Workforce Planning | Human Capital Management" in run["text"]
    assert "The payroll interface" not in run["text"]                                  # block 4 comes before the label: not taken


def test_a_neighbour_is_never_added_twice_and_the_outside_hits_are_kept():
    out, _, added = ps.reshape([STORE[0], dict(STORE[3], outside=True)], 3, expand)
    assert added == 1 and any(b.get("outside") for b in out) and any(b.get("via") for b in out)


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
    assert ids[0] == f"{DOC}:4" and any(b.get("via") for b in res["blocks"])


def test_read_by_name_does_not_expand_and_keeps_what_names_or_mentions_it():
    search = lambda q, k, docs: [dict(STORE[0]), dict(STORE[3])]                           # noqa: E731
    res = ps.read(lookup("name"), ["Evaluate"], "x", search, None, False, expand)
    it = res["items"][0]
    assert it["fragments"] == 1 and it["expanded"] == 0 and [b["block_id"] for b in res["blocks"]] == [f"{DOC}:4"]      # the bare label is dropped; nothing is expanded


def test_the_answer_step_is_told_which_passage_followed_a_label():
    ev = {"demand": {}, "lookups": [], "wiki": [], "graph_reads": [], "graph": None, "others": [], "used": [],
          "blocks": [dict(STORE[6], via=f"{DOC}:5"), STORE[3]]}
    text = gmod.render(ev)
    assert f"[{DOC}:7] (what follows [{DOC}:5] in its document, which was only a label)" in text and f"[{DOC}:4] The payroll interface" in text


# A table the document stored one cell per block, as the strategy list was: 5 column names, then the rows' cells, then a heading.
CELLS = ["Objective", "Code", "Intent", "Strategy", "Digital Transformation",
         "Improve staff services", "OBJ-7", "Make requests self-service", "Digital workplace", "Yes",
         "Cut manual payroll work", "OBJ-9", "Pay on approved results", "Finance automation", "Yes"]


def cell_store():
    rows = [{"block_id": f"S:{i}", "doc_id": "S", "btype": "paragraph", "section": "5.2 Strategic objectives", "ordinal": i,
             "text": f"S > 5.2 Strategic objectives\n{c}"} for i, c in enumerate(CELLS, 1)]
    rows.append({"block_id": "S:99", "doc_id": "S", "btype": "heading", "section": "5. Strategic Context", "ordinal": 99, "text": "5.3 Next"})
    rows.append({"block_id": "S:100", "doc_id": "S", "btype": "paragraph", "section": "5.3 Next", "ordinal": 100, "text": "S > 5.3 Next\nUnrelated."})
    return rows


def test_a_table_stored_one_cell_per_block_comes_back_as_its_cells_in_order():
    store = cell_store()
    near = lambda bid, w: [r for r in store if abs(r["ordinal"] - int(bid.split(":")[1])) <= w]      # noqa: E731
    out, frag, added = ps.reshape([store[0]], 3, near)
    run = next(b for b in out if b.get("via"))
    assert frag == 1 and added == 1 and run["via"] == "S:1" and run["block_id"] == "S:2" and run["run_to"] == "S:15"
    assert run["text"].endswith("Code | Intent | Strategy | Digital Transformation | Improve staff services | OBJ-7 | Make requests self-service"
                                " | Digital workplace | Yes | Cut manual payroll work | OBJ-9 | Pay on approved results | Finance automation | Yes")
    assert "Unrelated" not in run["text"]                                              # the next section is not part of it


def test_two_labels_of_the_same_table_are_read_once_and_a_long_run_is_cut():
    store = cell_store()
    near = lambda bid, w: [r for r in store if abs(r["ordinal"] - int(bid.split(":")[1])) <= w]      # noqa: E731
    out, frag, added = ps.reshape([store[0], store[1]], 3, near)
    assert frag == 2 and added == 1                                                    # the second label lies inside the first one's run
    long = [dict(r, text=f"S > 5.2 Strategic objectives\n" + ("word " * 12 + str(i))) for i, r in enumerate(store[:15], 1)]
    long[0]["text"] = "S > 5.2 Strategic objectives\nObjective"
    near2 = lambda bid, w: [r for r in long if abs(r["ordinal"] - int(bid.split(":")[1])) <= w]      # noqa: E731
    out, _, _ = ps.reshape([long[0]], 3, near2)
    assert len(next(b for b in out if b.get("via"))["text"]) < ps.RUN_CHARS + 200


# Appendix A as the index holds it: Capability | Services | Maturity, a block per cell, 114 capabilities; the one asked about is far down.
def appendix_store():
    names = [(f"Capability {i:03d}", f"Services of {i:03d}", "3 Evidenced") for i in range(1, 115)]
    names[96] = ("Workforce Performance", "Evaluation forms and bonus results", "2 Documented")
    cells = ["Capability", "Services", "Maturity"] + [c for row in names for c in row]
    rows = [{"block_id": f"A:{i}", "doc_id": "A", "btype": "paragraph", "section": "Appendix A / Supporting", "ordinal": i,
             "text": f"A > Appendix A / Supporting\n{c}"} for i, c in enumerate(cells, 1)]
    return rows


def test_a_long_table_of_cells_keeps_the_header_and_the_row_that_matches_the_question():
    store = appendix_store()
    asked = []

    def near(bid, w):
        asked.append(w)
        return [r for r in store if abs(r["ordinal"] - int(bid.split(":")[1])) <= w]
    out, frag, added = ps.reshape([store[0]], 3, near, "which capability covers evaluation forms and bonus performance")
    run = next(b for b in out if b.get("via"))
    assert asked[0] == ps.RUN_WINDOW and len(run["text"]) < ps.RUN_CHARS + 300
    assert "Services | Maturity" in run["text"]                                        # the column names stay
    assert "Workforce Performance | Evaluation forms and bonus results | 2 Documented" in run["text"]
    assert "…" in run["text"] and "the rest follows" in run["text"]
    assert "Capability 050" not in run["text"]                                         # the middle of the table is left out


def test_a_long_run_with_no_matching_cell_gives_its_start():
    store = appendix_store()
    near = lambda bid, w: [r for r in store if abs(r["ordinal"] - int(bid.split(":")[1])) <= w]      # noqa: E731
    out, _, _ = ps.reshape([store[0]], 3, near, "zebra quartz")
    run = next(b for b in out if b.get("via"))
    assert "Capability 001" in run["text"] and "Workforce Performance" not in run["text"] and "the rest follows" in run["text"]


# A diagram and its caption as the document stores them: the figure block (its text is the description), then the caption paragraph.
def fig_store():
    return [
        {"block_id": "F:1", "doc_id": "F", "btype": "paragraph", "section": "7.2 Capability model", "ordinal": 1, "text": "F > 7.2 Capability model\nThe model has 27 level-1 capabilities in four groups."},
        {"block_id": "F:2", "doc_id": "F", "btype": "figure", "section": "7.2 Capability model", "ordinal": 2,
         "text": "F > 7.2 Capability model\n\nA heat map. Human Capital (Workforce Planning, Job Performance, Training) is rated 2 Documented."},
        {"block_id": "F:3", "doc_id": "F", "btype": "paragraph", "section": "7.2 Capability model", "ordinal": 3, "text": "F > 7.2 Capability model\nFigure 7: Capability map: supporting - operational"},
        {"block_id": "F:4", "doc_id": "F", "btype": "figure", "section": "7.2 Capability model", "ordinal": 4, "text": "F > 7.2 Capability model\n\nAnother heat map."},
    ]


def test_what_counts_as_a_caption():
    st = fig_store()
    assert ps.is_caption(st[2]) and not ps.is_caption(st[0])                            # a sentence is not
    assert not ps.is_caption(st[1]) and not ps.is_caption(blk(9, "Objective"))          # a figure; a bare label


def test_a_caption_that_is_a_hit_brings_the_diagram_it_belongs_to():
    st = fig_store()
    near = lambda bid, w: [r for r in st if abs(r["ordinal"] - int(bid.split(":")[1])) <= w]      # noqa: E731
    out, _, added = ps.reshape([st[2]], 3, near)
    figs = [b for b in out if b.get("figure")]
    assert added == 1 and [b["block_id"] for b in figs] == ["F:2"] and figs[0]["via"] == "F:3"      # the figure before it, not the next one
    assert "Job Performance" in next(b for b in figs if b["block_id"] == "F:2")["text"]
    out, _, added = ps.reshape([st[2], st[1]], 3, near)                                  # the figure is already a hit: not added twice
    assert [b["block_id"] for b in out].count("F:2") == 1
    above = [dict(st[3], ordinal=1, block_id="G:1"), dict(st[2], ordinal=2, block_id="G:2")]       # a caption above its figure: the one after it
    near2 = lambda bid, w: [r for r in above if abs(r["ordinal"] - int(bid.split(":")[1])) <= w]   # noqa: E731
    out, _, _ = ps.reshape([above[1]], 3, near2)
    assert [b["block_id"] for b in out if b.get("figure")] == ["G:1"]


def test_the_answer_step_is_told_it_is_reading_a_diagram_description():
    st = fig_store()
    ev = {"demand": {}, "lookups": [], "wiki": [], "graph_reads": [], "graph": None, "others": [], "used": [],
          "blocks": [dict(st[1], via="F:3", figure=True)]}
    assert "[F:2] (the diagram that the caption [F:3] belongs to; this is its description)" in gmod.render(ev)


def test_a_diagram_description_is_read_whole_and_a_paragraph_keeps_its_limit():
    desc = "F > S\n\n" + ("Human Capital names. " * 55) + "Costs and Finance is the only one rated 4 Measured."
    para = "F > S\n" + ("word " * 400)
    ev = {"demand": {}, "lookups": [], "wiki": [], "graph_reads": [], "graph": None, "others": [], "used": [],
          "blocks": [{"block_id": "F:2", "btype": "figure", "text": desc}, {"block_id": "F:9", "btype": "paragraph", "text": para}]}
    text = gmod.render(ev)
    assert len(desc) > gmod.BLOCK_CHARS and "rated 4 Measured." in text                  # the end of the description is there
    assert text.count("word word") < 400 and len(text) < len(desc) + gmod.BLOCK_CHARS + 200   # a long paragraph is still cut at its limit


def test_the_passages_the_model_was_given_are_listed_with_what_they_are_and_where_they_came_from():
    from eawiki.cases import solve
    ev = {"used": ["x"], "searched": [f"s{i}" for i in range(30)], "allowed": set(),
          "blocks": [dict(STORE[6], via=f"{DOC}:5"), dict(STORE[1], figure=True, via="F:3"), STORE[3]]}
    how = solve.verify({"name": "P", "type": "text"}, None, ev)["how"]
    assert sum(1 for h in how if h.startswith("Searched ")) == 30                      # the searches are not cut at 8 any more
    lines = [h for h in how if h.startswith("Passage [")]
    assert len(lines) == 3 and lines[0].startswith(f"Passage [{DOC}:7] · {DOC} · table ·") and f"follows [{DOC}:5]" in lines[0]
    assert "belongs to [F:3]" in lines[1] and "The payroll interface sends each approved" in lines[2] and "Biz_Arch >" not in lines[2]


def test_a_label_with_nothing_after_it_is_dropped_and_a_figure_caption_stays():
    out, _, added = ps.reshape([STORE[2]], 3, lambda bid, w: [])                       # nothing follows: a label is not kept
    assert added == 0 and out == []
    st = fig_store()
    near = lambda bid, w: [r for r in st if abs(r["ordinal"] - int(bid.split(":")[1])) <= w]      # noqa: E731
    out, _, _ = ps.reshape([st[2]], 3, near)
    assert "F:3" in [b["block_id"] for b in out]                                         # a caption is a real passage: it stays with its diagram


def test_a_search_by_name_drops_the_labels_that_are_neither_the_entry_nor_a_mention():
    rows = [blk(20, "A > S\nHosting"), blk(21, "A > S\nSupplier name"), blk(22, "A > S\nEvaluate | Application | Retired"),
            blk(23, "A > S\nThe Evaluate service creates the evaluation forms for HR."), blk(24, "A > S\nHR Department")]
    search = lambda q, k, docs: [dict(b) for b in rows][:k]                              # noqa: E731
    res = ps.read(lookup("name"), ["Evaluate"], "x", search, None, False, None)
    it = res["items"][0]
    ids = [b["block_id"] for b in res["blocks"]]
    assert ids == [f"{DOC}:22", f"{DOC}:23"] and it["entry"] == [f"{DOC}:22"] and it["mentioned"] == [f"{DOC}:23"] and it["closest"] == []
    assert it["fragments"] == 3 and it["state"] == "found"
    only = lambda q, k, docs: [dict(rows[0]), dict(rows[1])]                             # noqa: E731
    it = ps.read(lookup("name"), ["Evaluate"], "x", only, None, False, None)["items"][0]
    assert it["state"] == "none"                                                         # nothing but labels: no entry, said as such


def test_the_section_line_in_front_of_a_passage_is_not_what_it_says():
    prefix = "Apps > Table of Contents / 29 Evaluate\n"
    rows = [blk(30, prefix + "Hosting"), blk(31, prefix + "Evaluate | Application | Retired"), blk(32, prefix + "It is run by the Facilities Office."),
            blk(33, "Apps > Table of Contents / 12 Rota Hub\nRota Hub | Application | Live")]
    search = lambda q, k, docs: [dict(b) for b in rows]                                  # noqa: E731
    it = ps.read(lookup("name"), ["Evaluate"], "x", search, None, False, None)["items"][0]
    assert it["entry"] == [f"{DOC}:31"]                                                  # the row that starts with the name, not every block under its heading
    assert it["mentioned"] == [] and f"{DOC}:30" not in it["closest"]                    # a passage is not about Evaluate because it sits in Evaluate's section
