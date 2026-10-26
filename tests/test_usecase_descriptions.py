"""A column or input field may carry a description; it is validated, tidied and shown to the model."""
import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eawiki import usecases  # noqa: E402

SPEC = {
    "name": "T",
    "input": {"item_fields": [{"name": "demand", "type": "text", "description": "  The request text.  "},
                              {"name": "unit", "type": "text", "description": "   "}]},
    "stages": [{"name": "S", "output": {"columns": [
        {"name": "Priority", "type": "text", "description": " Fast-track when a mandate applies. "},
        {"name": "Owner", "type": "text"}]}}],
}


def test_too_long_or_non_text_description_is_rejected():
    bad = copy.deepcopy(SPEC)
    bad["stages"][0]["output"]["columns"][0]["description"] = "x" * (usecases.MAX_DESCRIPTION + 1)
    assert any("longer than" in e for e in usecases.validate(bad))
    bad["stages"][0]["output"]["columns"][0]["description"] = 5
    assert any("must be text" in e for e in usecases.validate(bad))
    assert usecases.validate(SPEC) == []


def test_save_trims_and_drops_blank_descriptions(tmp_path=None, monkeypatch=None):
    usecases.DIR = tmp_path or Path(tempfile.mkdtemp())
    out = usecases.save(copy.deepcopy(SPEC), "t")
    f = out["input"]["item_fields"]
    assert f[0]["description"] == "The request text."
    assert "description" not in f[1]
    c = out["stages"][0]["output"]["columns"]
    assert c[0]["description"] == "Fast-track when a mandate applies."
    assert "description" not in c[1]


def test_guidance_fields_are_validated_tidied_and_read_by_the_model():
    spec = copy.deepcopy(SPEC)
    col = spec["stages"][0]["output"]["columns"][0]
    col.update(how_to_resolve="  Apply the rule.  ", look_in=[" Gap_Analysis_Sample ", "", "Gap_Analysis_Sample"],
               evidence_required=True, info_needed=" ", uses=["Owner"])
    assert usecases.validate(spec) == []
    bad = copy.deepcopy(spec)
    bad["stages"][0]["output"]["columns"][0]["uses"] = ["Nope"]
    assert any("not another column" in e for e in usecases.validate(bad))
    usecases.DIR = Path(tempfile.mkdtemp())          # never write into the real use_cases folder
    out = usecases.save(spec, "g")
    c = out["stages"][0]["output"]["columns"][0]
    assert c["how_to_resolve"] == "Apply the rule." and c["look_in"] == ["Gap_Analysis_Sample"]
    assert "evidence_required" not in c and "info_needed" not in c      # defaults are not stored
    from eawiki.query import executor
    c["evidence_required"] = False
    hint = executor._schema_hint(out["stages"][0]["output"]["columns"])
    assert "how to decide it: Apply the rule." in hint and "look first in: Gap_Analysis_Sample" in hint
    assert "builds on: Owner" in hint and "NOT required" in hint


def test_a_cell_that_needs_a_source_and_has_none_asks_the_architect():
    from eawiki.query import executor
    stage = {"id": "s", "name": "S", "output": {"columns": [
        {"name": "A", "type": "text", "info_needed": "Provide A."},
        {"name": "B", "type": "text", "evidence_required": False}]}}
    state = {"spec": {"stages": [stage]}, "stage_idx": 0, "valid": ["d1"], "needs": [],
             "ctx": {"d1": {"block_ids": ["x:1"]}},
             "results": {"d1": {"s": {"cells": [
                 {"column": "A", "value": "v", "status": "answered", "evidence": []},
                 {"column": "B", "value": "v", "status": "answered", "evidence": []}]}}}}
    out = executor.n_output_guard(state)
    cells = out["results"]["d1"]["s"]["cells"]
    assert cells[0]["status"] == "needs_input" and cells[0]["needs"] == "Provide A."
    assert cells[1]["status"] == "answered"                              # a rule or definition is enough


def test_the_model_prompt_carries_the_description():
    from eawiki.query import executor
    hint = executor._schema_hint(SPEC["stages"][0]["output"]["columns"])
    assert "what it means and how to resolve it: Fast-track when a mandate applies." in hint
    assert hint.count("what it means") == 1          # Owner has no description, so nothing is added
    fields = executor._fields_hint(SPEC)
    assert "demand): The request text." in fields
    assert "unit" not in fields                       # blank description, so not listed


if __name__ == "__main__":
    import tempfile
    test_too_long_or_non_text_description_is_rejected()
    test_save_trims_and_drops_blank_descriptions(Path(tempfile.mkdtemp()))
    test_guidance_fields_are_validated_tidied_and_read_by_the_model()
    test_a_cell_that_needs_a_source_and_has_none_asks_the_architect()
    test_the_model_prompt_carries_the_description()
    print("ok")


def test_a_structured_demand_is_searched_by_its_fields_and_held_to_the_required_ones():
    import json
    from eawiki.query import executor
    spec = json.loads((Path(__file__).resolve().parents[1] / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))
    full = {"demand_id": "D-2026-001", "title": "Mobile app", "business_need": "Paper forms", "expected_outcome": "Under 1 day",
            "systems_mentioned": "HR system", "department": "HR", "requester_role": "Head", "sponsor": "Director",
            "date_submitted": "2026-08-03", "request_type": "New solution", "requester_urgency": "High",
            "target_go_live": "2027-03-31"}
    assert executor._item_id(full, 0, spec) == "D-2026-001"
    text = executor._item_text(spec, full)
    assert "Demand title: Mobile app" in text and "Systems or data mentioned: HR system" in text
    assert executor._missing_required(spec, full) == []
    partial = {k: v for k, v in full.items() if k not in ("sponsor", "target_go_live")}
    assert executor._missing_required(spec, partial) == ["Business sponsor", "Target go-live"]
    assert executor._missing_required(spec, {"demand_no": "D-1", "business_need": "free text"}) == []   # plain box
