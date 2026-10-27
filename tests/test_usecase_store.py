"""Use-case settings in the database: they survive a deploy (a new file set), every save is a version, a version can be put back,
and the file shipped with the code only seeds."""
import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from eawiki import history, usecases  # noqa: E402

BASE = {"id": "t", "name": "T", "input": {"item_fields": [{"name": "title", "label": "Title", "type": "text"}]},
        "stages": [{"name": "S", "id": "s", "output": {"columns": [{"name": "P", "type": "text", "description": "first"},
                                                                   {"name": "Q", "type": "text"}]}}]}


@pytest.fixture
def stores(monkeypatch):
    d = Path(tempfile.mkdtemp())
    monkeypatch.setattr(history, "DB_PATH", d / "app.db")
    history._store.cache_clear()
    monkeypatch.setattr(usecases, "DIR", d / "files")
    monkeypatch.setenv("USECASE_STORE", "db")
    (d / "files").mkdir()
    yield d
    history._store.cache_clear()


def ship(d, spec):                      # what a deploy puts on the disk
    (d / "files" / f"{spec['id']}.json").write_text(json.dumps(spec), encoding="utf-8")


def test_the_file_seeds_a_use_case_the_database_has_not_seen(stores):
    ship(stores, BASE)
    assert [s["id"] for s in usecases.list_specs()] == ["t"]
    assert usecases.get("t")["stages"][0]["output"]["columns"][0]["description"] == "first"
    assert [v["note"] for v in usecases.versions("t")] == ["seeded from the file shipped with the code"]


def test_a_save_lives_in_the_database_and_a_new_file_set_does_not_replace_it(stores):
    ship(stores, BASE)
    edited = copy.deepcopy(BASE)
    edited["stages"][0]["output"]["columns"][0]["description"] = "edited in the screen"
    usecases.save(edited, "t")
    assert not any("edited" in (p.read_text() if p.exists() else "") for p in (stores / "files").glob("*.json"))     # no file written
    new_deploy = copy.deepcopy(BASE)
    new_deploy["stages"][0]["output"]["columns"][0]["description"] = "the code's newer text"
    ship(stores, new_deploy)
    assert usecases.get("t")["stages"][0]["output"]["columns"][0]["description"] == "edited in the screen"


def test_every_save_is_a_version_and_one_can_be_put_back(stores):
    ship(stores, BASE)
    for text in ("one", "two", "three"):
        s = copy.deepcopy(BASE)
        s["stages"][0]["output"]["columns"][0]["description"] = text
        usecases.save(s, "t")
    vs = usecases.versions("t")
    assert len(vs) == 4 and vs[0]["version"] > vs[-1]["version"]
    two = next(v for v in vs if v["version"] == vs[1]["version"])
    back = usecases.restore("t", two["vid"])
    assert back["stages"][0]["output"]["columns"][0]["description"] == "two" and back["version"] > vs[0]["version"]
    assert usecases.get("t")["stages"][0]["output"]["columns"][0]["description"] == "two"
    assert usecases.versions("t")[0]["note"].startswith("restored from version")
    with pytest.raises(ValueError):
        usecases.restore("t", "nope")


def test_the_file_diff_names_the_properties_and_the_file_can_be_loaded(stores):
    ship(stores, BASE)
    usecases.get("t")
    edited = copy.deepcopy(BASE)
    edited["stages"][0]["output"]["columns"][0]["description"] = "mine"
    edited["stages"][0]["output"]["columns"].append({"name": "R", "type": "text"})
    usecases.save(edited, "t")
    newer = copy.deepcopy(BASE)
    newer["stages"][0]["output"]["columns"][1]["description"] = "the code adds this"
    ship(stores, newer)
    d = usecases.file_diff("t")
    assert d["changed"] == ["S / P", "S / Q"] and d["removed"] == ["S / R"] and d["added"] == [] and d["in_file"]
    usecases.load_from_file("t")
    assert usecases.file_diff("t")["changed"] == [] and usecases.get("t")["stages"][0]["output"]["columns"][1]["description"] == "the code adds this"


def test_a_deleted_use_case_is_not_brought_back_by_its_file_and_can_be_made_again(stores):
    ship(stores, BASE)
    assert usecases.delete("t") is True and usecases.get("t") is None and usecases.list_specs() == []
    assert usecases.delete("t") is False
    usecases.save(BASE, "t")
    assert usecases.get("t") is not None


def test_without_a_database_the_files_are_the_store(monkeypatch):
    d = Path(tempfile.mkdtemp())
    monkeypatch.setattr(usecases, "DIR", d)
    monkeypatch.setenv("USECASE_STORE", "file")
    usecases.save(BASE, "t")
    assert (d / "t.json").exists() and usecases.versions("t") == [] and usecases.get("t")["id"] == "t"


def test_postgres_selects_the_database_unless_told_otherwise(monkeypatch):
    monkeypatch.delenv("USECASE_STORE", raising=False)
    monkeypatch.setenv("HISTORY_BACKEND", "postgres")
    assert usecases.use_db()
    monkeypatch.setenv("USECASE_STORE", "file")
    assert not usecases.use_db()
    monkeypatch.delenv("USECASE_STORE")
    monkeypatch.setenv("HISTORY_BACKEND", "sqlite")
    assert not usecases.use_db()
