"""The retrieval merge (docs/RETRIEVAL_MERGE_SPEC.md, section 9): table completion, the part key, duplicates across lanes, the budget and who
gives way first, the completeness lines, the order and the citation set. Fake lanes and a fake fetch: no model, no index."""
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eawiki.retrieval.merge import Budget, Item, LaneResult, merge, render  # noqa: E402


def part(bid, p, n, size=500, rows_per=20, total=None):
    total = total or n * rows_per
    return Item("tables", bid, ("row " * (size // 4))[:size], part=p, parts=n, rows_from=(p - 1) * rows_per + 1, rows_to=p * rows_per, rows_total=total)


def fetcher(n, size=500, calls=None):
    def fetch(bid, want):
        if calls is not None:
            calls.append((bid, list(want)))
        return [part(bid, p, n, size) for p in want]
    return fetch


def text(i, size=100):
    return Item("text", f"T:{i}", "t" * size)


def sec(m, lane):
    return next(s for s in m.sections if s.lane == lane)


def test_a_small_table_found_as_part_2_of_3_arrives_complete():
    calls = []
    m = merge([LaneResult("tables", [part("D:36", 2, 3)])], fetch_parts=fetcher(3, calls=calls))
    assert calls == [("D:36", [1, 3])]
    assert [(i.part) for i in sec(m, "tables").items] == [1, 2, 3] and sec(m, "tables").complete
    assert sec(m, "tables").completeness == "1 shown"                                     # one table, all of it


def test_a_large_table_gets_the_parts_next_to_the_one_found_and_says_what_is_missing():
    calls = []
    m = merge([LaneResult("tables", [part("D:36", 5, 8, total=160)])], fetch_parts=fetcher(8, calls=calls))
    assert calls == [("D:36", [4, 6])] and [i.part for i in sec(m, "tables").items] == [4, 5, 6]
    s = sec(m, "tables")
    assert not s.complete and "table [D:36]: parts 4 to 6 of 8 shown; rows 61 to 120 of 160" in s.completeness


def test_a_part_at_the_edge_of_a_large_table_has_one_neighbour_only():
    calls = []
    merge([LaneResult("tables", [part("D:36", 1, 8)])], fetch_parts=fetcher(8, calls=calls))
    assert calls == [("D:36", [2])]


def test_whole_tables_completes_a_large_table_to_its_budget_and_reports_it_when_the_budget_stops_it():
    calls = []
    big = Budget(table_chars=10000)
    m = merge([LaneResult("tables", [part("D:36", 5, 8)])], budget=big, fetch_parts=fetcher(8, calls=calls), whole_tables=True)
    assert calls == [("D:36", [1, 2, 3, 4, 6, 7, 8])] and len(sec(m, "tables").items) == 8 and sec(m, "tables").complete
    small = replace(big, table_chars=2000)                                                 # four parts fit, eight do not
    m = merge([LaneResult("tables", [part("D:36", 5, 8)])], budget=small, fetch_parts=fetcher(8), whole_tables=True)
    s = sec(m, "tables")
    assert len(s.items) == 4 and not s.complete and "the table budget stopped it" in s.completeness and "of 8 shown" in s.completeness


def test_a_table_whose_other_parts_cannot_be_fetched_says_so():
    m = merge([LaneResult("tables", [part("D:36", 2, 3)])], fetch_parts=None)
    assert "parts 2 of 3 shown" in sec(m, "tables").completeness and "could not be fetched" in sec(m, "tables").completeness
    def boom(*_):
        raise RuntimeError("down")
    m = merge([LaneResult("tables", [part("D:36", 2, 3)])], fetch_parts=boom)
    assert "could not be fetched (error)" in sec(m, "tables").completeness and [i.part for i in sec(m, "tables").items] == [2]


def test_parts_2_and_3_of_one_table_are_both_kept_and_a_table_of_one_part_needs_no_fetch():
    calls = []
    m = merge([LaneResult("tables", [part("D:36", 2, 8), part("D:36", 3, 8), part("D:9", 1, 1)])], fetch_parts=fetcher(8, calls=calls))
    ids = [(i.id, i.part) for i in sec(m, "tables").items]
    assert ("D:36", 2) in ids and ("D:36", 3) in ids and ("D:36", 1) in ids and ("D:36", 4) in ids and ("D:9", 1) in ids
    assert calls == [("D:36", [1, 4])]                                                     # the neighbours of both parts, once each


def test_the_same_piece_found_by_two_lanes_is_shown_once_in_the_higher_lane():
    tab = part("D:36", 1, 1)
    m = merge([LaneResult("tables", [tab]), LaneResult("text", [Item("text", "D:36", "same block as text", part=1), text(2)]),
               LaneResult("graph", [Item("graph", "g:evaluate", "Evaluate --sends_data_to--> Portal", cites=("D:36", "D:7"))])])
    assert [i.id for i in sec(m, "tables").items] == ["D:36"] and sec(m, "tables").items[0].meta["also_found_in"] == ["text"]
    assert [i.id for i in sec(m, "text").items] == ["T:2"]
    assert m.allowed == {"D:36", "T:2", "g:evaluate", "D:7"}                              # a graph item may cite the blocks it rests on


def test_each_lane_keeps_its_own_default_number_and_says_how_many_it_searched():
    m = merge([LaneResult("text", [text(i) for i in range(10)], searched=10), LaneResult("figures", [Item("figures", f"F:{i}", "d") for i in range(5)])])
    assert len(sec(m, "text").items) == 5 and "10 searched; 5 shown" in sec(m, "text").completeness
    assert len(sec(m, "figures").items) == 3 and "5 searched; 3 shown" in sec(m, "figures").completeness


def test_over_budget_text_goes_first_then_graph_then_wiki_then_tables_and_a_table_goes_whole():
    b = Budget(total_chars=1500, table_chars=2000)
    lanes = [LaneResult("tables", [part("D:1", 1, 1, 600), part("D:2", 1, 1, 600)]),
             LaneResult("wiki", [Item("wiki", "wiki:a", "w" * 300)]),
             LaneResult("graph", [Item("graph", "g:1", "g" * 200)]),
             LaneResult("text", [text(i, 100) for i in range(5)])]
    m = merge(lanes, budget=b)
    assert m.dropped.get("text") == 5 and m.dropped.get("graph") == 1                    # 1200 + 300 + 200 + 500 = 2200 > 1500: all the text (500), then the graph (200)
    assert "wiki" not in m.dropped and "tables" not in m.dropped
    assert "5 not shown (budget)" in sec(m, "text").completeness and not sec(m, "text").complete
    tighter = merge(lanes, budget=replace(b, total_chars=900))
    assert tighter.dropped["tables"] == 1 and [i.id for i in sec(tighter, "tables").items] == ["D:1"]      # the last table goes, whole; the first stays


def test_an_empty_a_failed_and_an_unsearched_lane_each_say_so_in_their_own_words():
    m = merge([LaneResult("tables", [], "none"), LaneResult("wiki", [], "error"), LaneResult("text", [text(1)], extra={"labels_set_aside": 2})])
    assert sec(m, "tables").heading == "TABLES (none found)"
    assert sec(m, "wiki").completeness.startswith("could not be searched (error)") and not sec(m, "wiki").complete
    assert sec(m, "figures").heading == "FIGURES (not searched for this question)" and sec(m, "graph").completeness == "not searched for this question"
    assert "2 labels set aside" in sec(m, "text").completeness


def test_the_sections_are_in_priority_order_with_their_headings_and_the_question_last():
    m = merge([LaneResult("text", [text(1)]), LaneResult("tables", [part("D:9", 1, 1)]), LaneResult("figures", [Item("figures", "F:1", "A heat map.")]),
               LaneResult("wiki", [Item("wiki", "wiki:human-capital", "Human Capital page")]), LaneResult("graph", [])])
    assert [s.lane for s in m.sections] == ["tables", "wiki", "graph", "figures", "text"]
    out = render(m, "Which capability covers job performance?")
    heads = [out.index(h) for h in ("TABLES (", "WIKI PAGES (", "GRAPH FACTS (", "FIGURES (", "TEXT (")]
    assert heads == sorted(heads) and out.rstrip().endswith("QUESTION: Which capability covers job performance?")
    assert "[wiki:human-capital] Human Capital page" in out and "[F:1] A heat map." in out


def test_a_part_of_a_table_is_shown_with_its_part_and_rows_and_a_whole_short_table_through_the_table_view():
    m = merge([LaneResult("tables", [part("D:36", 2, 3, 200)])], fetch_parts=fetcher(3, 200))
    out = render(m)
    assert "[D:36] part 2 of 3, rows 21 to 40 of 60" in out
    md = "| Code | Objective |\n|---|---|\n| SO4 | Strengthen institutional excellence |\n| SO5 | Grow |"
    out = render(merge([LaneResult("tables", [Item("tables", "D:5", md)])]), "which objective strengthens excellence")
    assert "[D:5]" in out and "SO4 | Strengthen institutional excellence" in out and "|---|" not in out


def test_long_text_is_cut_to_its_lane_room_and_a_run_has_more_room():
    m = merge([LaneResult("text", [text(1, 3000), Item("text", "D:2", "r" * 3000, meta={"run": True})]),
               LaneResult("figures", [Item("figures", "F:1", "f" * 4000)])])
    t = sec(m, "text").items
    assert len(t[0].text) <= 1100 + 2 and t[0].meta["cut"] and len(t[1].text) <= 1800 + 2
    assert len(sec(m, "figures").items[0].text) <= 2500 + 2


def test_the_citation_set_is_exactly_what_is_shown():
    m = merge([LaneResult("text", [text(i) for i in range(9)])])
    assert m.allowed == {f"T:{i}" for i in range(5)}


def test_a_table_found_as_two_parts_counts_as_one_result():
    m = merge([LaneResult("tables", [part("D:36", 2, 8), part("D:36", 3, 8), part("D:9", 1, 1)])], fetch_parts=fetcher(8))
    assert sec(m, "tables").completeness.startswith("2 shown; table [D:36]")                # two tables, not three parts
