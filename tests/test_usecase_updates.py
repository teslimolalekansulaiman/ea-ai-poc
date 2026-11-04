"""Updates shipped with the code for a use case that already lives in the database: careful with the owner's own work, offered once,
and nothing stored when they cannot be applied."""
import copy
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from eawiki import usecase_updates as up  # noqa: E402
from eawiki import usecases  # noqa: E402
from eawiki.api.app import app  # noqa: E402

SEED = base.SPEC                                       # the use case as it ships now
OLD = base.SPEC_P2                                     # the use case as it stood before the update: what a database copy holds
UC = "demand-management"
UPDATE = "recommendation-request-draft"
FOLLOW = "recommendation-steps-in-sections"
STARTER = "recommendation-starter-lookups"
MESSAGE = "recommendation-without-architect-part"
S = "Recommendation"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A folder of use cases holding the older second stage, with the shipped update beside it."""
    monkeypatch.setattr(usecases, "DIR", tmp_path)
    monkeypatch.delenv("USECASE_STORE", raising=False)
    (tmp_path / "updates" / UC).mkdir(parents=True)
    for f in (base.ROOT / "use_cases" / "updates" / UC).glob("*.json"):
        shutil.copy(f, tmp_path / "updates" / UC / f.name)
    usecases.save(copy.deepcopy(OLD), UC)
    return tmp_path


def _doc(stage):
    """The document settings without the one the message-only update sets: the earlier updates do not."""
    return {k: v for k, v in stage["output"]["document"].items() if k != "apart"}


def _one(uid):
    return next(x for x in up.available(UC) if x["id"] == uid)


def _names(spec, stage=1):
    return [c["name"] for c in spec["stages"][stage]["output"]["columns"]]


def test_the_shipped_update_brings_an_older_copy_to_the_shipped_design(store):
    u = _one(UPDATE)
    assert u["id"] == UPDATE and not u["applied"] and u["errors"] == [] and u["changes"]
    assert any("renamed 'Recommendation type'" in c for c in u["changes"]) and any("'Recommended action' is removed" in c for c in u["changes"])
    assert all(any(f"'{n}' is added" in c for c in u["changes"]) for n in ("Risks and conditions", "Handled with", "Recommendation", "Request overview"))
    assert any("'Confidence' is removed" in c for c in u["changes"]) and not any("Next steps" in c for c in u["changes"])         # it was never in this copy
    before = usecases.get(UC)
    out = up.apply(UC, UPDATE)
    now = usecases.get(UC)
    assert out["version"] == before["version"] + 1 and now[up.APPLIED_KEY] == [UPDATE]
    assert usecases.validate(now) == []
    assert _names(now) == _names(SEED)                                                   # the same properties, in the same order
    a, b = now["stages"][1], SEED["stages"][1]
    assert a["summary_columns"] == b["summary_columns"] and a["result"]["row_tag"] == b["result"]["row_tag"] and _doc(a) == _doc(b)
    assert a["output"]["mode"] == "document" and "The last two properties" in a["instructions"]
    cons = next(c for c in a["output"]["columns"] if c["name"] == "Consolidate with demand(s)")
    assert cons["sees_others"] == next(c for c in b["output"]["columns"] if c["name"] == "Consolidate with demand(s)")["sees_others"]
    new = {c["name"]: c for c in a["output"]["columns"]}
    assert new["Recommendation"]["type"] == "text" and "senior enterprise architect" in new["Recommendation"]["how_to_resolve"]
    assert new["Request overview"]["scope"] == "request" and new["Handled with"]["derive"]["kind"] == "groups"
    assert new["Recommendation"]["sees_others"] == ["Recommendation type", "Recommended owner", "Handled with"]
    assert [(x["id"], x["applied"]) for x in up.available(UC)] == [(UPDATE, True), (STARTER, False), (FOLLOW, False), (MESSAGE, False)]       # offered once; the follow-up has nothing to do here
    assert _one(FOLLOW)["changes"] == [] and _one(FOLLOW)["errors"] == []
    with pytest.raises(up.UpdateError):
        up.apply(UC, UPDATE)


def test_the_owners_own_wording_is_kept_and_only_empty_wording_is_filled(store):
    spec = usecases.get(UC)
    sec = next(c for c in spec["stages"][1]["output"]["columns"] if c["name"] == "Security fit")
    sec["description"] = "MY OWN WORDS"
    own = next(c for c in spec["stages"][1]["output"]["columns"] if c["name"] == "Recommended owner")
    own.pop("how_to_resolve")                                                            # nothing written there
    spec["stages"][1]["instructions"] = "My stage instructions."
    usecases.save(spec, UC)
    u = _one(UPDATE)
    assert any("'Security fit': your description is kept" in k for k in u["kept"])
    up.apply(UC, UPDATE)
    now = usecases.get(UC)
    cols = {c["name"]: c for c in now["stages"][1]["output"]["columns"]}
    assert cols["Security fit"]["description"] == "MY OWN WORDS"
    assert cols["Recommended owner"]["how_to_resolve"] == next(c for c in SEED["stages"][1]["output"]["columns"] if c["name"] == "Recommended owner")["how_to_resolve"]
    assert now["stages"][1]["instructions"].startswith("My stage instructions.\n\n") and "The last two properties" in now["stages"][1]["instructions"]


def test_a_property_the_owner_already_has_is_never_touched(store):
    spec = usecases.get(UC)
    spec["stages"][1]["output"]["columns"].append({"name": "Risks and conditions", "type": "text", "description": "THEIRS"})
    usecases.save(spec, UC)
    up.apply(UC, UPDATE)
    mine = [c for c in usecases.get(UC)["stages"][1]["output"]["columns"] if c["name"] == "Risks and conditions"]
    assert len(mine) == 1 and mine[0]["description"] == "THEIRS" and mine[0]["type"] == "text"


def test_nothing_is_stored_when_it_cannot_be_applied(store):
    spec = usecases.get(UC)
    spec["stages"][1]["name"] = "Advice"                                                  # the stage the update names is not there
    usecases.save(spec, UC)
    u = _one(UPDATE)
    assert u["errors"] and "no stage named 'Recommendation'" in u["errors"][0].replace("There is ", "")
    v = usecases.get(UC)["version"]
    with pytest.raises(up.UpdateError):
        up.apply(UC, UPDATE)
    assert usecases.get(UC)["version"] == v and up.APPLIED_KEY not in usecases.get(UC)
    with pytest.raises(LookupError):
        up.apply(UC, "nope")
    with pytest.raises(LookupError):
        up.available("no-such-use-case")


# ---- the steps, one by one --------------------------------------------------------------------------------------------

def _plan(ops, spec=None):
    return up.plan(spec or OLD, {"id": "t", "ops": ops})


def test_a_renamed_property_is_followed_by_everything_that_refers_to_it():
    p = _plan([{"op": "rename_property", "stage": S, "from": "Recommendation", "to": "Way forward"}])
    st = p["spec"]["stages"][1]
    assert p["errors"] == [] and st["result"]["row_tag"] == "Way forward"
    assert "Way forward" in next(c for c in st["output"]["columns"] if c["name"] == "Recommended action")["uses"]
    assert "Recommendation" not in [c["name"] for c in st["output"]["columns"]]
    again = up.plan(p["spec"], {"id": "t", "ops": [{"op": "rename_property", "stage": S, "from": "Recommendation", "to": "Way forward"}]})
    assert again["changes"] == []                                                         # a step that has been taken changes nothing the second time


def test_a_removed_property_takes_its_references_with_it():
    p = _plan([{"op": "remove_property", "stage": S, "name": "Security fit"}])
    st = p["spec"]["stages"][1]
    assert p["errors"] == [] and "Security fit" not in next(c for c in st["output"]["columns"] if c["name"] == "Recommended action")["uses"]
    gone = _plan([{"op": "remove_property", "stage": S, "name": "Justification"}])          # the stage's summary property: it leaves the summary list too
    assert gone["errors"] == [] and gone["spec"]["stages"][1]["summary_columns"] == []


def test_a_step_that_does_not_make_sense_is_reported_not_guessed():
    assert "Unknown step" in _plan([{"op": "teleport", "stage": S}])["errors"][0]
    assert "There is no stage named 'Nope'" in _plan([{"op": "order", "stage": "Nope", "names": []}])["errors"][0]
    assert "missing" in _plan([{"op": "rename_property", "stage": S, "from": "Recommendation"}])["errors"][0]
    assert any("no property 'Nope' to fill in" in e for e in _plan([{"op": "fill_property", "stage": S, "name": "Nope", "fields": {"description": "x"}}])["errors"])
    broken = _plan([{"op": "set_stage", "stage": S, "fields": {"output.document": {"statement": "Not a property"}}}])
    assert broken["errors"] and "headline text" in broken["errors"][0]                    # what the use case's own checks reject, the update reports


def test_the_routes_list_apply_and_refuse(store):
    c = TestClient(app)
    got = c.get(f"/api/usecases/{UC}/updates").json()["updates"]
    assert [u["id"] for u in got] == [UPDATE, STARTER, FOLLOW, MESSAGE] and got[0]["changes"] and not got[0]["applied"]
    assert c.get("/api/usecases/nope/updates").status_code == 404
    assert c.post(f"/api/usecases/{UC}/updates/nope").status_code == 404
    ok = c.post(f"/api/usecases/{UC}/updates/{UPDATE}")
    assert ok.status_code == 200 and ok.json()["changes"]
    assert c.post(f"/api/usecases/{UC}/updates/{UPDATE}").status_code == 400              # already applied
    assert c.get(f"/api/usecases/{UC}/updates").json()["updates"][0]["applied"] is True and c.get(f"/api/usecases/{UC}/updates").json()["updates"][2]["changes"] == []
    got = c.get(f"/api/usecases/{UC}").json()["stages"][1]
    assert got["summary_columns"] == ["Recommendation"] and got["output"]["document"]["scope"] == "request"


def test_a_property_the_copy_does_not_have_is_left_out_of_what_a_property_is_shown_and_said_not_a_failure(store):
    spec = usecases.get(UC)
    spec["stages"][0]["output"]["columns"] = [c for c in spec["stages"][0]["output"]["columns"] if c["name"] != "Impacted business capability"]
    for c in spec["stages"][0]["output"]["columns"]:
        c["uses"] = [x for x in c.get("uses") or [] if x != "Impacted business capability"]
    usecases.save(spec, UC)
    u = _one(UPDATE)
    assert u["errors"] == [] and any("not shown the other demands' 'Impacted business capability'" in k for k in u["kept"])
    up.apply(UC, UPDATE)
    cons = next(c for c in usecases.get(UC)["stages"][1]["output"]["columns"] if c["name"] == "Consolidate with demand(s)")
    assert cons["sees_others"] == ["Is duplicate", "Duplicate demand number (in the sheet)", "Impacted application"]


# ---- a copy that already has the earlier whole-request update ------------------------------------------------------

def _earlier_copy():
    """The use case as the earlier whole-request update left it: with 'Next steps' and 'Confidence', and that update recorded as applied."""
    spec = copy.deepcopy(SEED)
    spec["stages"][1] = json.loads((base.ROOT / "tests" / "fixtures" / "phase2_effabae_stage.json").read_text(encoding="utf-8"))
    spec[up.APPLIED_KEY] = [UPDATE]
    return spec


def test_a_copy_that_already_has_the_earlier_update_is_brought_forward_and_nothing_is_left_pointing_at_what_went(store):
    usecases.save(_earlier_copy(), UC)
    assert _one(UPDATE)["applied"] is True
    u = _one(FOLLOW)
    assert u["errors"] == [] and any("'Next steps' is removed" in c for c in u["changes"]) and any("'Confidence' is removed" in c for c in u["changes"])
    assert any("'Recommendation': how to resolve is brought up to date" in c for c in u["changes"]) and any("'Request overview': sees others is brought up to date" in c for c in u["changes"])
    up.apply(UC, FOLLOW)
    now = usecases.get(UC)
    assert usecases.validate(now) == [] and _names(now) == _names(SEED)
    a, b = now["stages"][1], SEED["stages"][1]
    cols = {c["name"]: c for c in a["output"]["columns"]}
    assert cols["Recommendation"]["how_to_resolve"] == next(c for c in b["output"]["columns"] if c["name"] == "Recommendation")["how_to_resolve"]
    assert "Next steps" not in cols["Recommendation"]["uses"] and "Next steps" not in cols["Request overview"]["sees_others"] and "Next steps" not in a["output"]["document"]["internal"]
    assert _doc(a) == _doc(b) and a["instructions"].count("which ends with its next steps") == 1 and "next steps. The last" not in a["instructions"]
    assert now[up.APPLIED_KEY] == [UPDATE, FOLLOW]


def test_what_the_owner_changed_since_the_earlier_update_is_kept_when_it_is_brought_forward(store):
    spec = _earlier_copy()
    mine = next(c for c in spec["stages"][1]["output"]["columns"] if c["name"] == "Recommendation")
    mine["how_to_resolve"] = "MY OWN INSTRUCTIONS"
    usecases.save(spec, UC)
    u = _one(FOLLOW)
    assert any("'Recommendation': your how to resolve is kept" in k for k in u["kept"])
    up.apply(UC, FOLLOW)
    cols = {c["name"]: c for c in usecases.get(UC)["stages"][1]["output"]["columns"]}
    assert cols["Recommendation"]["how_to_resolve"] == "MY OWN INSTRUCTIONS" and "Next steps" not in cols["Recommendation"]["uses"]      # the setting that was not changed moves on


def test_an_upgrade_does_not_bring_back_a_property_the_owner_removed(store):
    spec = _earlier_copy()
    spec["stages"][1]["output"]["columns"] = [c for c in spec["stages"][1]["output"]["columns"] if c["name"] != "Request overview"]
    spec["stages"][1]["output"]["document"] = {"scope": "item", "statement": "Recommended owner"} if False else {}
    plan = up.plan(spec, next(x for x in up.shipped(UC) if x["id"] == FOLLOW))
    assert not any("Request overview" in c and "up to date" in c for c in plan["changes"])


# ---- starter questions for the second stage ---------------------------------------------------------------------------------

ASKING = ["Overlaps with", "Consolidate with demand(s)", "Contract / licence match", "Security fit", "Recommended owner", "Risks and conditions"]


def _without_questions(spec=None):
    spec = copy.deepcopy(spec or SEED)
    for c in spec["stages"][1]["output"]["columns"]:
        c.pop("lookups", None)
        if c["name"] in ("Contract / licence match", "Security fit"):
            c.pop("uses", None)
    return spec


def _starter():
    return json.loads((base.ROOT / "use_cases" / "updates" / UC / f"{STARTER}.json").read_text(encoding="utf-8"))      # the file, whatever folder other tests left in place


def _cols(spec):
    return {c["name"]: c for c in spec["stages"][1]["output"]["columns"]}


def test_the_starter_questions_fill_the_properties_that_ask_and_make_them_build_on_what_they_start_from():
    p = up.plan(_without_questions(), _starter())
    assert p["errors"] == [] and p["kept"] == []
    cols = _cols(p["spec"])
    assert [n for n in cols if cols[n].get("lookups")] == ASKING                               # the ones that decide from the demand or earlier answers ask nothing
    assert all(0 < len(cols[n]["lookups"]) <= usecases.MAX_LOOKUPS for n in ASKING)
    assert {"Overlaps with"} <= set(cols["Contract / licence match"]["uses"]) and {"Overlaps with"} <= set(cols["Security fit"]["uses"])
    owner = cols["Recommended owner"]["lookups"]
    assert [lk["from"] for lk in owner] == ["result:Overlaps with", "result:Impacted business capability"]
    assert all(lk["relations"] == [{"relation": "is_owned_by", "direction": "out"}] and lk["match"] == "name" for lk in owner)   # the graph's owner edge
    assert [lk["match"] for lk in cols["Consolidate with demand(s)"]["lookups"]] == ["compare"]
    assert usecases.validate(p["spec"], usecases.relation_names()) == []


def test_the_shipped_use_case_already_has_them_so_the_update_has_nothing_to_change():
    p = up.plan(copy.deepcopy(SEED), _starter())
    assert p["changes"] == [] and p["errors"] == []


def test_questions_the_owner_wrote_are_kept_and_so_is_what_they_build_on():
    spec = _without_questions()
    mine = [{"find": "my own question", "from": "need", "match": "meaning", "in": []}]
    _cols(spec)["Security fit"]["lookups"] = copy.deepcopy(mine)
    p = up.plan(spec, _starter())
    cols = _cols(p["spec"])
    assert cols["Security fit"]["lookups"] == mine and "uses" not in cols["Security fit"]
    assert any("Security fit" in k and "lookups" in k for k in p["kept"]) and cols["Overlaps with"]["lookups"]


def test_a_question_that_cannot_work_in_this_copy_is_left_out_and_said():
    spec = up.plan(_without_questions(), {"ops": [{"op": "rename_property", "stage": "Screening & Impact Assessment", "from": "Impacted business capability", "to": "Capability I renamed"}]})["spec"]
    p = up.plan(spec, _starter())
    cols = _cols(p["spec"])
    assert p["errors"] == []
    assert [lk["from"] for lk in cols["Recommended owner"]["lookups"]] == ["result:Overlaps with"]
    assert not any(lk["from"] == "result:Impacted business capability" for c in cols.values() for lk in c.get("lookups") or [])
    assert sum("has no property 'Impacted business capability'" in k for k in p["kept"]) == 2         # Overlaps with, Recommended owner


def test_a_question_that_would_start_a_loop_is_left_out_and_said():
    spec = _without_questions()
    _cols(spec)["Overlaps with"]["uses"] = ["Contract / licence match"]                          # the owner made it build on the contract
    p = up.plan(spec, _starter())
    cols = _cols(p["spec"])
    assert p["errors"] == []
    assert not any(lk["from"] == "result:Overlaps with" for lk in cols["Contract / licence match"].get("lookups") or [])
    assert any("builds on this property" in k and "Contract / licence match" in k for k in p["kept"])
    assert "Overlaps with" not in (cols["Contract / licence match"].get("uses") or [])


def test_a_copy_still_on_the_older_stage_is_told_what_it_lacks_and_nothing_is_stored(store):
    out = up.plan(copy.deepcopy(OLD), _starter())
    assert out["errors"] and "there is no property 'Risks and conditions' to fill in" in " ".join(out["errors"])


def test_the_starter_questions_are_applied_once_from_the_screen(store):
    spec = _without_questions()
    usecases.save(spec, UC, note="a copy before the starter questions")
    c = TestClient(app)
    got = {u["id"]: u for u in c.get(f"/api/usecases/{UC}/updates").json()["updates"]}
    assert not got[STARTER]["applied"] and got[STARTER]["changes"] and got[STARTER]["errors"] == []
    done = c.post(f"/api/usecases/{UC}/updates/{STARTER}").json()
    assert "version" in done
    stored = usecases.get(UC)
    assert _cols(stored)["Recommended owner"]["lookups"] and STARTER in stored["updates_applied"]
    assert c.post(f"/api/usecases/{UC}/updates/{STARTER}").status_code in (400, 409)            # once


def test_the_message_only_update_leaves_out_the_architects_part_and_the_owner_can_turn_it_back_on():
    spec = copy.deepcopy(SEED)
    spec["stages"][1]["output"]["document"].pop("apart")
    p = up.plan(spec, json.loads((base.ROOT / "use_cases" / "updates" / UC / f"{MESSAGE}.json").read_text(encoding="utf-8")))
    assert p["errors"] == [] and p["spec"]["stages"][1]["output"]["document"]["apart"] is False and p["changes"]
    assert up.plan(copy.deepcopy(SEED), json.loads((base.ROOT / "use_cases" / "updates" / UC / f"{MESSAGE}.json").read_text(encoding="utf-8")))["changes"] == []     # the shipped one has it
    on = copy.deepcopy(SEED)
    on["stages"][1]["output"]["document"].pop("apart")
    assert usecases.validate(on) == []
    bad = copy.deepcopy(SEED)
    bad["stages"][1]["output"]["document"]["apart"] = "no"
    assert any("true or false" in e for e in usecases.validate(bad))
