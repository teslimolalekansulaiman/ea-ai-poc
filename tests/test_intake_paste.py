"""A demand pasted into the box: free text, or a list of the input fields."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eawiki.cases import intake  # noqa: E402
from eawiki.query import executor  # noqa: E402

SPEC = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))

LISTED = """Demand ID: D-2026-901
Requesting department: Human Resources
Demand title: Training completion in the payroll portal
Business need / problem: Employees complete courses on the training pages, but HR re-enters every certificate
by hand into the HR & Payroll Portal.
Expected outcome / benefit: Completion is recorded automatically
Request type: Interface between systems
Systems or data mentioned: Training and Development Pages, HR & Payroll Portal"""


def test_plain_text_is_the_business_need_as_before():
    r = intake.from_text(SPEC, "The VPN drops every 20 minutes for remote staff. We need it stable.")
    it = r["items"][0]
    assert it["business_need"].startswith("The VPN drops") and it["title"] == "The VPN drops every 20 minutes for remote staff. We need it" and "_pasted" not in it
    assert executor._missing_required(SPEC, it) == []                       # free text is not held to the sheet's rules


def test_listed_inputs_go_to_their_fields_by_name_or_label_and_a_value_may_run_over_lines():
    it = intake.from_text(SPEC, LISTED)["items"][0]
    assert it["demand_id"] == "D-2026-901" and it["department"] == "Human Resources" and it["request_type"] == "Interface between systems"
    assert it["business_need"] == "Employees complete courses on the training pages, but HR re-enters every certificate\nby hand into the HR & Payroll Portal."
    assert it["systems_mentioned"] == "Training and Development Pages, HR & Payroll Portal" and it["title"] == "Training completion in the payroll portal"
    assert it["_pasted"] is True


def test_a_listed_demand_is_not_returned_for_the_fields_the_person_did_not_list():
    it = intake.from_text(SPEC, LISTED)["items"][0]
    assert "sponsor" not in it and "target_go_live" not in it
    assert executor._missing_required(SPEC, it) == []
    sheet_row = {k: v for k, v in it.items() if k != "_pasted"}
    assert executor._missing_required(SPEC, sheet_row)                      # the same fields from a sheet row would be returned


def test_text_before_the_labels_is_the_need_when_no_need_was_labelled_and_a_missing_title_is_made_from_it():
    text = "We cannot see spend by vendor across departments.\nDepartment: Procurement\nRequest type: Data & analytics\nRequester urgency: Medium"
    it = intake.from_text(SPEC, text)["items"][0]
    assert it["business_need"] == "We cannot see spend by vendor across departments." and it["title"].startswith("We cannot see spend by vendor")
    assert it["department"] == "Procurement" and it["requester_urgency"] == "Medium"


def test_two_labels_or_unknown_labels_do_not_make_a_structured_demand():
    one = intake.from_text(SPEC, "Department: Finance\nRequest type: Other\nplease help with the quarterly report, it is slow")
    assert "_pasted" not in one["items"][0] and one["items"][0]["business_need"].startswith("Department: Finance")
    unknown = intake.from_text(SPEC, "Colour: blue\nShape: round\nSize: big\nWeight: heavy")
    assert "_pasted" not in unknown["items"][0]


def test_a_url_or_a_time_in_the_text_is_not_a_label():
    text = "Meeting at 10:30 about https://example.org/a:b and the HR system.\nDepartment: HR\nSponsor: Director\nRequest type: Other"
    it = intake.from_text(SPEC, text)["items"][0]
    assert it["business_need"].startswith("Meeting at 10:30 about https://example.org/a:b") and it["sponsor"] == "Director"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  passed", name)
    print("ok")
