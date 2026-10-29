"""Bulk upload and removal of source documents: each file gets its own verdict, kinds are folders, nothing rebuilds until the batch is
applied, and the batch is applied with ONE rebuild."""
import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from eawiki import pipeline as pl  # noqa: E402
from eawiki import sources  # noqa: E402
from eawiki.api import app as appmod  # noqa: E402


def office(text="x") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w>{text}</w>")
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "SAMPLES", tmp_path / "samples")
    monkeypatch.setattr(appmod, "ARCHIVE", tmp_path / "archive")
    monkeypatch.setattr(appmod, "_require_writable", lambda: None)
    starts = []
    monkeypatch.setattr(pl, "run_async", lambda: starts.append(1) or {"running": True})
    monkeypatch.setattr(pl, "status", lambda: {"running": False})
    return tmp_path, starts, TestClient(appmod.app)


def up(client, name, data, kind="architecture"):
    return client.post("/api/docs/upload", files={"file": (name, data)}, data={"kind": kind}).json()


def test_each_file_gets_its_own_verdict_and_nothing_rebuilds(env):
    root, starts, c = env
    got = [up(c, "a.docx", office("a")), up(c, "b.pptx", office("b"), "governance"), up(c, "c.txt", b"hello"), up(c, "d.docx", b"not a zip"),
           up(c, "e.docx", b""), up(c, "f.docx", office("f"), "nonsense")]
    assert [g["state"] for g in got] == ["added", "added", "rejected", "rejected", "rejected", "rejected"]
    assert "Only .docx and .pptx" in got[2]["reason"] and "cannot be opened" in got[3]["reason"] and "empty" in got[4]["reason"] and "not a kind" in got[5]["reason"]
    assert starts == []                                                                         # saving files starts no rebuild
    assert (root / "samples/a.docx").exists() and (root / "samples/governance/b.pptx").exists()  # a kind is the folder the parse step reads
    assert sources.kind_of(root / "samples/governance/b.pptx") == "governance" and sources.kind_of(root / "samples/a.docx") == "architecture"


def test_a_name_clash_a_duplicate_and_a_replacement_are_told_apart(env):
    root, _, c = env
    up(c, "a.docx", office("a"))
    assert up(c, "a.docx", office("a"))["state"] == "unchanged"
    assert up(c, "a.docx", office("changed"))["state"] == "replaced"
    dup = up(c, "copy.docx", office("changed"))
    assert dup["state"] == "rejected" and "Same content as 'a.docx'" in dup["reason"]
    clash = up(c, "a.pptx", office("other"))
    assert clash["state"] == "rejected" and "already uses the name 'a'" in clash["reason"]
    elsewhere = up(c, "a.docx", office("g"), "governance")
    assert elsewhere["state"] == "rejected" and "(architecture)" in elsewhere["reason"]


def test_a_file_over_the_limit_is_refused_without_being_kept(env, monkeypatch):
    root, _, c = env
    monkeypatch.setitem(sources.LIMITS, "max_file_mb", 0)
    got = up(c, "big.docx", office("a"))
    assert got["state"] == "rejected" and "larger than" in got["reason"] and not list((root / "samples").rglob("big*"))


def test_a_batch_is_applied_with_one_rebuild_and_removals_are_archived(env):
    root, starts, c = env
    for n in "abcd":
        up(c, f"{n}.docx", office(n))
    r = c.post("/api/docs/apply", json={"remove": ["a", "b"], "added": 0})
    assert r.status_code == 200 and sorted(r.json()["archived"]) == ["a.docx", "b.docx"] and len(starts) == 1
    assert (root / "archive/a.docx").exists() and not (root / "samples/a.docx").exists() and (root / "samples/c.docx").exists()


def test_the_knowledge_base_is_never_emptied_and_an_empty_batch_is_refused(env):
    root, starts, c = env
    up(c, "a.docx", office("a"))
    assert c.post("/api/docs/apply", json={"remove": ["a"], "added": 0}).status_code == 400
    assert c.post("/api/docs/apply", json={"remove": ["a"], "added": 1}).status_code == 200        # a file added in the same batch counts
    assert c.post("/api/docs/apply", json={"remove": [], "added": 0}).status_code == 400
    assert c.post("/api/docs/apply", json={"remove": ["zz"], "added": 1}).status_code == 404
    assert len(starts) == 1


def test_nothing_is_saved_while_a_rebuild_runs(env, monkeypatch):
    root, _, c = env
    monkeypatch.setattr(pl, "status", lambda: {"running": True})
    assert c.post("/api/docs/upload", files={"file": ("a.docx", office())}).status_code == 409
    assert c.post("/api/docs/apply", json={"remove": [], "added": 1}).status_code == 409


def test_the_single_file_routes_still_work_and_use_the_same_checks(env):
    root, starts, c = env
    assert c.post("/api/docs/add", files={"file": ("a.docx", office("a"))}).json()["state"] == "added" and len(starts) == 1
    assert c.post("/api/docs/add", files={"file": ("x.txt", b"hi")}).status_code == 400
    up(c, "b.docx", office("b"))
    assert c.delete("/api/docs/b").json()["archived"] == ["b.docx"] and len(starts) == 2
    assert c.delete("/api/docs/a").status_code == 400                                            # the last document stays


def test_the_kinds_and_limits_are_offered_to_the_screen(env, monkeypatch):
    root, _, c = env
    monkeypatch.setattr(appmod, "_block_files", lambda: [])
    got = c.get("/api/docs").json()
    assert set(got["kinds"]) == {"architecture", "motivation", "governance", "reference"} and got["limits"]["max_batch_files"] == 20
