"""The settings that let a stage work once for the whole request: a property with request scope, a property derived in code,
the other items' answers shown to a late property, and a document that is one per request. Each is checked, and tidied."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import pytest  # noqa: E402

from eawiki import usecases  # noqa: E402

OLD = base.SPEC_P2


@pytest.fixture(autouse=True)
def _use_cases(monkeypatch):
    monkeypatch.setattr(usecases, "DIR", base.ROOT / "use_cases")


def _spec():
    spec = copy.deepcopy(OLD)
    cols = spec["stages"][1]["output"]["columns"]
    cols.insert(-2, {"name": "Overview", "type": "text", "scope": "request", "evidence_required": False})
    cols.insert(-2, {"name": "Handled with", "type": "text", "derive": {"kind": "groups", "from": "Consolidate with demand(s)", "lead_by": "date_submitted"}})
    spec["stages"][1]["output"]["document"] = {"scope": "request", "statement": "Overview", "item_text": "Justification", "internal": ["Overlaps with", "Handled with"]}
    return spec


def _col(spec, name):
    return next(c for c in spec["stages"][1]["output"]["columns"] if c["name"] == name)


def test_the_request_settings_together_are_valid():
    assert usecases.validate(_spec()) == []


def test_a_property_worked_out_once_per_request_is_text_or_a_list_and_not_the_stages_summary():
    s = _spec()
    _col(s, "Overview")["type"] = "enum"
    _col(s, "Overview")["values"] = ["A"]
    assert any("text or a list" in e for e in usecases.validate(s))
    s = _spec()
    _col(s, "Overview")["scope"] = "everyone"
    assert any("once for the whole request, not 'everyone'" in e for e in usecases.validate(s))
    s = _spec()
    s["stages"][1]["summary_columns"] = ["Overview"]
    assert any("cannot also be the stage's summary property" in e for e in usecases.validate(s))


def test_a_derived_property_is_plain_text_formed_from_a_list_of_this_stage_and_led_by_an_input_field():
    s = _spec()
    _col(s, "Handled with")["derive"]["kind"] = "magic"
    assert any("can only be derived as 'groups'" in e for e in usecases.validate(s))
    s = _spec()
    _col(s, "Handled with")["derive"]["from"] = "Security fit"                         # not a list
    assert any("a list property of this stage" in e for e in usecases.validate(s))
    s = _spec()
    _col(s, "Handled with")["derive"]["lead_by"] = "nope"
    assert any("not one" in e for e in usecases.validate(s))
    s = _spec()
    _col(s, "Handled with")["uses"] = ["Overlaps with"]
    assert any("builds on nothing" in e for e in usecases.validate(s))
    s = _spec()
    _col(s, "Handled with")["derive"]["lead_by"] = ""                                    # no field: the order the items came in
    assert usecases.validate(s) == []


def test_only_a_late_property_may_be_shown_the_other_items_answers_of_its_own_stage():
    s = _spec()
    _col(s, "Justification")["sees_others"] = ["Recommended owner", "Handled with", "Is duplicate"]      # the summary property: this stage's and an earlier stage's
    assert usecases.validate(s) == []
    _col(s, "Overview")["sees_others"] = ["Recommended owner", "Justification"]                        # once per request: the same
    assert usecases.validate(s) == []
    s = _spec()
    _col(s, "Security fit")["sees_others"] = ["Recommended owner"]                                      # an ordinary property: earlier stages only
    assert any("only a summary property, or one worked out once per request" in e for e in usecases.validate(s))
    s = _spec()
    _col(s, "Justification")["sees_others"] = ["Justification"]                                        # never itself
    assert any("not a property of an earlier stage" in e for e in usecases.validate(s))


def test_a_document_for_the_whole_request_needs_a_request_headline_and_a_per_item_text():
    s = _spec()
    s["stages"][1]["output"]["document"]["statement"] = "Justification"                    # not worked out once per request
    assert any("headline text worked out once per request" in e for e in usecases.validate(s))
    s = _spec()
    s["stages"][1]["output"]["document"]["item_text"] = "Overview"
    assert any("each item's section" in e for e in usecases.validate(s))
    s = _spec()
    s["stages"][1]["output"]["document"]["scope"] = "planet"
    assert any("one per item or one for the whole request" in e for e in usecases.validate(s))
    s = _spec()
    s["stages"][1]["output"]["document"]["internal"] = ["Overview"]
    assert any("cannot be kept per item" in e for e in usecases.validate(s))


def test_what_is_left_at_its_default_leaves_no_key_behind():
    s = _spec()
    _col(s, "Security fit")["scope"] = "item"
    _col(s, "Security fit")["derive"] = {}
    s["stages"][0]["output"]["columns"][0]["scope"] = ""
    doc = s["stages"][1]["output"]["document"]
    s["stages"][1]["output"]["document"] = {"statement": "Recommended action", "scope": "item", "item_text": "", "internal": []}
    usecases._tidy_descriptions(s)
    assert "scope" not in _col(s, "Security fit") and "derive" not in _col(s, "Security fit") and "scope" not in s["stages"][0]["output"]["columns"][0]
    assert s["stages"][1]["output"]["document"] == {"statement": "Recommended action"}
    assert doc["scope"] == "request"                                                               # a real value stays
