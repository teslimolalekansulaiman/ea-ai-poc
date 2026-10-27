"""Phase 1: what the demand mentions. No model: the validation and the prompt's shape."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eawiki.cases import profile  # noqa: E402
from eawiki.usecases import PROFILE_GROUPS  # noqa: E402

FIELDS = {"systems_mentioned": ("Systems or data mentioned", "HR system, payroll, attendance devices"),
          "business_need": ("Business need", "Employees request leave by email and the HR team re-types every request into the HR system by hand.")}


def test_every_group_is_explained_to_the_model_and_asked_for():
    p = profile._prompt(FIELDS)
    for g in PROFILE_GROUPS:
        assert g in profile.GROUP_HELP and f"- {g}:" in p and f'"{g}": ["..."]' in p
    assert "Anything the requester lists in a field about systems mentioned belongs here" in p


def test_a_clause_is_not_a_mention():
    raw = {"systems": ["HR system", "the HR team re-types every request into the HR system by hand today"], "processes": ["leave"]}
    out = profile.validate(raw, FIELDS)
    assert [m["text"] for m in out["systems"]] == ["HR system"] and [m["text"] for m in out["processes"]] == ["leave"]


def test_the_new_groups_are_kept_and_checked_like_the_others():
    raw = {"tools_today": ["email", "a fax machine nobody wrote"], "requested": ["HR system"]}
    out = profile.validate(raw, FIELDS)
    assert [m["text"] for m in out["tools_today"]] == ["email"] and [m["text"] for m in out["requested"]] == ["HR system"]
    assert set(out) == set(PROFILE_GROUPS)


def test_no_model_gives_an_empty_profile_that_says_so():
    p = profile.build_profile(FIELDS, None)
    assert p["origin"] == "none" and all(p[g] == [] for g in PROFILE_GROUPS)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  passed", name)
    print("ok")
