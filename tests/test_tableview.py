"""How a table passage reaches the answer step: tidied, long ones cut by relevance, and a cut says so."""

from eawiki.cases import gather as gmod
from eawiki.cases import tableview as tv

# A key-value table as a document stores it: every value once per merged column, the label last and in bold.
KV = [("Runs the monthly leave calendar for the depot staff, replacing a shared spreadsheet", "Description"),
      ("Facilities Office", "Responsible operator"), ("Depot staff", "Application users"),
      ("Depot manager", "Stakeholders"), ("Support crew", "Team Members"), ("Internal: Web App.", "Application Interfaces"),
      ("Operated by the hosting provider.", "Hosting"), ("Support crew", "Tech Support"), ("Support crew", "Supplier name"),
      ("Frontend: Ruby DB: SQLite", "Technologies Used"), ("Application", "Type"),
      ("Retired", "Application Status"), ("Replaced by the Rota Hub; kept for last year's records only", "Notes")]
KV_BLOCK = "Apps_Sample > Table of Contents / 29 Calendar\n\n" + "\n".join(f"{v}\t{v}\t**{lab}**" for v, lab in KV)

# A mapping table with a long column, padded the way a markdown export pads it; the answer is far down.
NAMES = [f"Item {i:02d}" for i in range(1, 41)]
NAMES[33], NAMES[34] = "Roster Accuracy", "Roster Dispute"
LONG = "A long description that makes the column wide " * 4


def padded(rows):
    width = max(len(r[2]) for r in rows)
    lines = ["| Data entity | Capability | Group" + " " * (width - 5) + " |", "|---|---|" + "-" * (width + 2) + "|"]
    lines += [f"| {a} | {b} | {c.ljust(width)} |" for a, b, c in rows]
    return "Mapping_Sample > Capability map\n\n" + "\n".join(lines)


MAP_ROWS = [(n, "Planning" if i % 2 else "Logistics", LONG) for i, n in enumerate(NAMES)]
MAP_ROWS[33] = ("Roster Accuracy", "Shift Management", LONG)
MAP_ROWS[34] = ("Roster Dispute", "Shift Management", LONG)
MAP_BLOCK = padded(MAP_ROWS)


def test_merged_cells_come_once_and_the_label_comes_first():
    out = tv.render(KV_BLOCK)
    assert "Application Status: Retired" in out and "Notes: Replaced by the Rota Hub" in out
    assert out.count("Facilities Office") == 1 and "**" not in out
    assert len(out) < len(KV_BLOCK) * 0.7


def test_a_key_value_table_that_the_old_cut_truncated_keeps_its_last_rows():
    padded_kv = KV_BLOCK + "\n" + "\n".join(f"{v} {i}\t{v} {i}\t**Extra {i}**" for i, (v, _) in enumerate(KV[:6]))
    assert "Retired" in padded_kv[:1100] or len(padded_kv) > 1100
    out = tv.render(padded_kv, "retired status")
    assert "Application Status: Retired" in out and len(out) <= tv.TABLE_CHARS + 200


def test_a_padded_table_is_tidied_and_its_header_kept():
    before, header, rows = tv.parse(MAP_BLOCK)
    assert before == "Mapping_Sample > Capability map"
    assert header == "Data entity | Capability | Group"
    assert len(rows) == 40 and all("  " not in r for r in rows)
    assert not any(r.startswith("---") for r in rows)


def test_a_long_table_keeps_the_rows_that_match_not_the_first_ones():
    cut = MAP_BLOCK[:1100]
    assert "Roster Accuracy" not in cut                      # what the model used to see
    out = tv.render(MAP_BLOCK, "the roster is wrong and rows are disputed: roster accuracy")
    assert "Roster Accuracy | Shift Management" in out
    assert "Data entity | Capability | Group" in out         # the header stays
    assert "table of 40 rows" in out and "closest to what was asked" in out
    assert len(out) <= tv.TABLE_CHARS + 200


def test_no_matching_row_gives_the_first_rows_and_says_so():
    out = tv.render(MAP_BLOCK, "zebra quartz")
    assert "Item 01" in out and "no row matched" in out and "Roster Accuracy" not in out


def test_a_short_table_is_shown_whole_without_a_note():
    out = tv.render("Doc > S\n\n| a | b |\n|---|---|\n| x | y |\n| z | w |")
    assert out == "Doc > S\na | b\nx | y\nz | w"


def test_prose_is_not_a_table():
    assert not tv.is_table({"btype": "paragraph", "text": "One sentence. Another one, with a comma."})
    assert tv.is_table({"btype": "table", "text": "anything"})


def test_the_evidence_shows_the_matching_row_of_a_long_table():
    ev = {"demand": {"business_need": ("Business need", "roster accuracy disputes")}, "lookups": [], "wiki": [], "graph_reads": [],
          "graph": None, "others": [], "blocks": [{"block_id": "M:1", "btype": "table", "text": MAP_BLOCK}], "used": []}
    text = gmod.render(ev)
    assert "Roster Accuracy | Shift Management" in text


# A matrix as a document stores it: a row per application, a column per control, a mark where one applies, equal marks side by side.
MATRIX = ("Std > Application to Security Control Matrix\n\n"
          "| Application | Encryption | Logging | Access review | MFA | Backup |\n|---|---|---|---|---|---|\n"
          "| Evaluate | Yes | Yes |  | Yes |  |\n| Rota Hub |  | Yes | Yes | Yes | Yes |\n| Depot Wiki |  |  |  |  | Yes |")


def test_a_matrix_keeps_which_column_each_mark_is_in_and_equal_marks_are_not_merged():
    out = tv.render(MATRIX)
    assert "Evaluate: Encryption=Yes; Logging=Yes; MFA=Yes" in out          # the empty Access review column is not a mark
    assert "Rota Hub: Logging=Yes; Access review=Yes; MFA=Yes; Backup=Yes" in out
    assert "Depot Wiki: Backup=Yes" in out and "Application | Encryption | Logging | Access review | MFA | Backup" in out


def test_two_equal_cells_in_one_row_of_an_ordinary_table_stay():
    out = tv.render("| Item | From | To |\n|---|---|---|\n| Leave | Annual | Annual |\n| Sick | Medical | Self |\n| Study | Unpaid | Unpaid |")
    assert "Leave | Annual | Annual" in out and "Sick | Medical | Self" in out


def test_a_merged_column_goes_only_when_the_whole_table_repeats_it():
    out = tv.render(KV_BLOCK)
    assert out.count("Retired") == 1
