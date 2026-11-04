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
UPDATE = "recommendation-message"
S = "Recommendation"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A folder of use cases holding the older second stage, with the shipped update beside it."""
    monkeypatch.setattr(usecases, "DIR", tmp_path)
    monkeypatch.delenv("USECASE_STORE", raising=False)
    (tmp_path / "updates" / UC).mkdir(parents=True)
    shutil.copy(base.ROOT / "use_cases" / "updates" / UC / f"{UPDATE}.json", tmp_path / "updates" / UC / f"{UPDATE}.json")
    usecases.save(copy.deepcopy(OLD), UC)
    return tmp_path


def _names(spec, stage=1):
    return [c["name"] for c in spec["stages"][stage]["output"]["columns"]]


def test_the_shipped_update_brings_an_older_copy_to_the_shipped_design(store):
    [u] = up.available(UC)
    assert u["id"] == UPDATE and not u["applied"] and u["errors"] == [] and u["changes"]
    assert any("renamed 'Recommendation type'" in c for c in u["changes"]) and any("'Recommended action' is removed" in c for c in u["changes"])
    assert any("'Risks and conditions' is added" in c for c in u["changes"])
    before = usecases.get(UC)
    out = up.apply(UC, UPDATE)
    now = usecases.get(UC)
    assert out["version"] == before["version"] + 1 and now[up.APPLIED_KEY] == [UPDATE]
    assert usecases.validate(now) == []
    assert _names(now) == _names(SEED)                                                   # the same properties, in the same order
    a, b = now["stages"][1], SEED["stages"][1]
    assert a["summary_columns"] == b["summary_columns"] and a["result"]["row_tag"] == b["result"]["row_tag"] and a["output"]["document"] == b["output"]["document"]
    assert a["output"]["mode"] == "document" and "The last property, Recommendation," in a["instructions"]
    cons = next(c for c in a["output"]["columns"] if c["name"] == "Consolidate with demand(s)")
    assert cons["sees_others"] == next(c for c in b["output"]["columns"] if c["name"] == "Consolidate with demand(s)")["sees_others"]
    new = next(c for c in a["output"]["columns"] if c["name"] == "Recommendation")
    assert new["type"] == "text" and "senior enterprise architect" in new["how_to_resolve"]
    assert [x["applied"] for x in up.available(UC)] == [True]                           # offered once
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
    [u] = up.available(UC)
    assert any("'Security fit': your description is kept" in k for k in u["kept"])
    up.apply(UC, UPDATE)
    now = usecases.get(UC)
    cols = {c["name"]: c for c in now["stages"][1]["output"]["columns"]}
    assert cols["Security fit"]["description"] == "MY OWN WORDS"
    assert cols["Recommended owner"]["how_to_resolve"] == next(c for c in SEED["stages"][1]["output"]["columns"] if c["name"] == "Recommended owner")["how_to_resolve"]
    assert now["stages"][1]["instructions"].startswith("My stage instructions.\n\n") and "The last property, Recommendation," in now["stages"][1]["instructions"]


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
    [u] = up.available(UC)
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
    assert [u["id"] for u in got] == [UPDATE] and got[0]["changes"] and not got[0]["applied"]
    assert c.get("/api/usecases/nope/updates").status_code == 404
    assert c.post(f"/api/usecases/{UC}/updates/nope").status_code == 404
    ok = c.post(f"/api/usecases/{UC}/updates/{UPDATE}")
    assert ok.status_code == 200 and ok.json()["changes"]
    assert c.post(f"/api/usecases/{UC}/updates/{UPDATE}").status_code == 400              # already applied
    assert c.get(f"/api/usecases/{UC}/updates").json()["updates"][0]["applied"] is True
    assert json.loads(json.dumps(c.get(f"/api/usecases/{UC}").json()))["stages"][1]["summary_columns"] == ["Recommendation"]
