"""A column or input field may carry a description; it is validated, tidied and shown to the model."""
import copy
import sys
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


def test_save_trims_and_drops_blank_descriptions(tmp_path, monkeypatch=None):
    usecases.DIR = tmp_path
    out = usecases.save(copy.deepcopy(SPEC), "t")
    f = out["input"]["item_fields"]
    assert f[0]["description"] == "The request text."
    assert "description" not in f[1]
    c = out["stages"][0]["output"]["columns"]
    assert c[0]["description"] == "Fast-track when a mandate applies."
    assert "description" not in c[1]


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
    test_the_model_prompt_carries_the_description()
    print("ok")
