"""The Demand use case's second stage as it ships: one recommendation for the whole request, in one draft. Each demand has its own
section; one overview opens the draft; both are written last, from everything before them, and the draft keeps the architect's
findings apart. These tests read the shipped file, not a fixture, so a change to its design is a change to a test."""
import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import pytest  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.cases import document, engine as eng  # noqa: E402
from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import REQUEST_ID, CaseStore  # noqa: E402

SPEC = base.SPEC                                   # the shipped use case
REC = SPEC["stages"][1]
COLS = {c["name"]: c for c in REC["output"]["columns"]}
FINDINGS = ["Overlaps with", "Consolidate with demand(s)", "Contract / licence match", "Security fit"]
OVERVIEW = "Handle the three demands together where they overlap."
PID = "recommendation"


@pytest.fixture(autouse=True)
def _use_cases(monkeypatch):
    monkeypatch.setattr(usecases, "DIR", base.ROOT / "use_cases")


def test_the_shipped_stage_is_valid_and_is_the_design_that_was_agreed():
    assert usecases.validate(SPEC) == []
    assert [c["name"] for c in REC["output"]["columns"]] == ["Recommendation type", "Overlaps with", "Consolidate with demand(s)", "Contract / licence match",
                                                              "Security fit", "Recommended owner", "Risks and conditions", "Next steps", "Handled with",
                                                              "Recommendation", "Request overview", "Confidence", "Evidence"]
    assert "Recommended action" not in COLS and "Justification" not in COLS                  # they became paragraphs of the demand's section
    assert REC["summary_columns"] == ["Recommendation"] and REC["result"]["row_tag"] == "Recommendation type"
    section, overview, handled = COLS["Recommendation"], COLS["Request overview"], COLS["Handled with"]
    assert section["type"] == "text" and section["evidence_required"] is False and section.get("scope") is None
    assert section["sees_others"] == ["Recommendation type", "Recommended owner", "Handled with"]
    assert set(section["uses"]) >= {*FINDINGS, "Recommendation type", "Recommended owner", "Risks and conditions", "Next steps", "Handled with"}
    assert overview["scope"] == "request" and overview["evidence_required"] is False
    assert handled["derive"] == {"kind": "groups", "from": "Consolidate with demand(s)", "lead_by": "date_submitted"} and not handled.get("uses")
    for col, words in ((section, ("100 to 150 words", "to the requester", "no heading", "Plain text only")), (overview, ("60 to 120 words", "Name which demands are handled together"))):
        for must in ("senior enterprise architect", "roles, never personal names", "Do not state a grade", *words):
            assert must.lower() in col["how_to_resolve"].lower(), must
    assert REC["output"]["mode"] == "document"
    assert REC["output"]["document"] == {"scope": "request", "statement": "Request overview", "item_text": "Recommendation",
                                         "internal": ["Recommendation type", *FINDINGS, "Recommended owner", "Risks and conditions", "Next steps", "Handled with"]}
    assert COLS["Consolidate with demand(s)"]["sees_others"] == ["Is duplicate", "Duplicate demand number (in the sheet)", "Impacted application", "Impacted business capability"]


def _run(items=3):
    order, seen = [], {}

    def llm(prompt):
        m = re.search(r"PROPERTY: (.+?)  \[", prompt)
        name = m.group(1) if m else ""
        if name in COLS and "INSTRUCTIONS FOR THIS STAGE" in prompt:
            who = re.search(r"\[demand:demand_id\] Demand ID: (\S+)", prompt)
            who = who.group(1) if who else REQUEST_ID
            order.append((name, who))
            seen.setdefault((name, who), prompt)
            canned = {"Recommendation type": "Enhancement", "Overlaps with": ["HR Portal"], "Contract / licence match": "None found", "Security fit": "Open",
                      "Consolidate with demand(s)": ["D-2026-003"] if who == "D-2026-001" else ["None"], "Recommended owner": "HR Systems Lead",
                      "Risks and conditions": ["Security fit not confirmed"], "Next steps": ["The owner confirms the status"],
                      "Recommendation": f"Section for {who}.", "Request overview": OVERVIEW}
            if name in canned:
                ids = re.findall(r"\[([^\]\s]+:\d+)\]", prompt)
                return {"value": canned[name], "status": "answered", "evidence": [] if name == "Request overview" else ids[:1], "needs": "", "note": "n"}
        return base.fake_llm(prompt)

    def tools():
        t = base.fake_tools()
        t.llm_json = llm
        return t

    e = Engine(CaseStore(), tools, workers=2)
    cid = e.create(copy.deepcopy(SPEC), base.ITEMS[:items], "shipped")
    e.run_phase(cid, "screening")
    e.approve(cid, "screening", background=False)
    return e, cid, order, seen


def test_each_demands_section_and_then_the_overview_are_written_last_from_everything_before():
    e, cid, order, seen = _run()
    names = [n for n, _ in order]
    # the findings first, in the order the dependencies set; then each demand's section; the overview last, and once
    last_finding = max(i for i, n in enumerate(names) if n not in ("Recommendation", "Request overview"))
    first_section = min(i for i, n in enumerate(names) if n == "Recommendation")
    assert names.count("Recommendation") == 3 and names.count("Request overview") == 1
    assert first_section > last_finding and names.index("Request overview") > max(i for i, n in enumerate(names) if n == "Recommendation")
    assert max(names.index(n) for n in FINDINGS) < min(names.index("Recommendation type"), names.index("Recommended owner")) < names.index("Risks and conditions") < names.index("Next steps")
    # a demand's section reads that demand's whole picture: the request, both stages, who it is combined with, and the others
    p = seen[("Recommendation", "D-2026-001")]
    assert "ONE demand" in p and "senior enterprise architect" in p
    assert "Recommendation type: Enhancement" in p and "Risks and conditions: Security fit not confirmed" in p and "Next steps: The owner confirms the status" in p
    assert "Handled with: Combined with D-2026-003; lead: D-2026-001" in p and re.search(r"Screening & Impact Assessment / Demand type: ", p)
    others = p.split("THE OTHER DEMANDS IN THIS REQUEST")[1].split("\n\n")[0]
    assert "- D-2026-003 (" in others and "- D-2026-001 (" not in others and "Handled with: Combined with D-2026-001" in others
    # the overview reads every demand, with their sections, and is told it is writing for the whole request
    o = seen[("Request overview", REQUEST_ID)]
    assert "ONE request, which holds several demands" in o and "ALREADY DECIDED FOR THIS DEMAND" not in o
    block = o.split("THE DEMANDS IN THIS REQUEST")[1].split("\n\n")[0]
    assert re.findall(r"^- (D-2026-\d+) \(", block, re.M) == ["D-2026-001", "D-2026-003", "D-2026-004"]
    assert "Handled with: Alone" in block and "Combined with D-2026-003; lead: D-2026-001" in block and "Risks and conditions: Security fit not confirmed" in block
    # consolidation was shown the other demands' screening answers
    cons = seen[("Consolidate with demand(s)", "D-2026-001")]
    assert re.search(r"^- D-2026-003 \(.*?\): Is duplicate: ", cons.split("THE OTHER DEMANDS IN THIS REQUEST")[1], re.M)


def test_the_draft_is_one_for_the_request_with_the_findings_kept_apart_and_left_out_of_the_download():
    e, cid, order, seen = _run()
    case = e.store.get_case(cid)
    [entry] = document.listing(e.store, case, PID)
    d = entry["doc"]
    assert entry["item_id"] == REQUEST_ID and d["rec"]["body"] == OVERVIEW and d["rec"]["title"] == "Recommendation for this request"
    msg = [s for s in d["sections"] if not s.get("internal")]
    assert [s["title"].split(" · ")[0] for s in msg] == ["D-2026-001", "D-2026-003", "D-2026-004"]
    assert [s.get("group") for s in msg] == ["Combined: D-2026-001, D-2026-003"] * 2 + [None]
    assert [s["body"] for s in msg] == ["Section for D-2026-001.", "Section for D-2026-003.", "Section for D-2026-004."]
    apart = {s["title"] for s in d["sections"] if s.get("internal")}
    assert {"D-2026-001 · Security fit", "D-2026-001 · Recommendation type", "D-2026-004 · Handled with", document.TO_CONFIRM} <= apart
    assert not any("Confidence" in t for t in apart)                                      # graded in code, for the table
    page = document.render_html(entry)
    assert OVERVIEW in page and "Combined: D-2026-001, D-2026-003" in page and "Section for D-2026-004." in page
    assert all(t not in page for t in [*FINDINGS, "Handled with", document.TO_CONFIRM, document.EVIDENCE])


def test_answering_a_property_of_the_stage_writes_the_derived_and_request_wide_properties_again():
    deps = eng.Engine._dependants(REC, "Security fit")
    assert {"Recommendation", "Request overview", "Handled with"} <= deps
    assert {"Recommendation type", "Risks and conditions", "Next steps"} <= eng.Engine._dependants(REC, "Overlaps with")
