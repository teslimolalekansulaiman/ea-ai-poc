"""A merged entity keeps the real type of its members; `element` (type unknown) never wins."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eawiki import dedupe  # noqa: E402


def _mention(name, typ):
    return {"name": name, "type": typ, "origin": "t", "block_id": "b"}


def _merge(first, second):
    ms = [_mention("Oracle Database", first), _mention("Oracle DB", second)]
    keys = {m["type"]: (dedupe.normalize(m["name"]), m["type"]) for m in ms}
    a = (dedupe.normalize("Oracle Database"), first)
    b = (dedupe.normalize("Oracle DB"), second)
    out = dedupe.resolve(ms, [], adjudicate=lambda ca, cb: (True, "same"),
                         extra_pairs=[(a, b, 0.95)], apply_llm=True)
    assert len(out["nodes"]) == 1, out["nodes"]
    return out["nodes"][0]


def test_typed_member_wins_whichever_side_is_the_union_root():
    assert _merge("element", "physical_technology_component")["type"] == "physical_technology_component"
    assert _merge("physical_technology_component", "element")["type"] == "physical_technology_component"


def test_two_elements_stay_element():
    assert _merge("element", "element")["type"] == "element"


if __name__ == "__main__":
    test_typed_member_wins_whichever_side_is_the_union_root()
    test_two_elements_stay_element()
    print("ok")
