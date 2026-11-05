"""How long each step of a case run took: recorded without changing what a call returns, summarised so that what is slow can be seen."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cases_engine as base  # noqa: E402
import test_shipped_recommendation as shipped  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.cases import timing  # noqa: E402


@pytest.fixture(autouse=True)
def _use_cases(monkeypatch):
    monkeypatch.setattr(usecases, "DIR", base.ROOT / "use_cases")


class Sink:
    def __init__(self):
        self.rows = []

    def save_timings(self, cid, rows):
        self.rows += rows


def test_a_timed_call_returns_what_it_returns_and_is_recorded_under_its_label_or_a_better_one():
    sink = Sink()
    sc = timing.Scope(sink, "c", "p", "D-1", "Owners")
    slow = lambda x: (time.sleep(0.02), x * 2)[1]                                   # noqa: E731
    f = timing.timed(slow, sc, "model call (text)")
    assert f(21) == 42 and f.labelled("wiki page search (model)")(1) == 2
    assert timing.timed(None, sc, "x") is None
    assert timing.labelled(slow, "x") is slow                                         # an untimed call is left alone
    with sc.total("gather the evidence"):
        f(1)
    parts = {r["step"]: r for r in sink.rows if r["kind"] == "part"}
    assert set(parts) == {"model call (text)", "wiki page search (model)"} and parts["model call (text)"]["calls"] == 2      # a scope keeps every call made through it until it is flushed, the one before the part too
    [total] = [r for r in sink.rows if r["kind"] == "total"]
    assert total["step"] == "gather the evidence" and total["seconds"] >= 0.02 and total["item_id"] == "D-1" and total["col"] == "Owners"
    assert all(r["part_of"] == "gather the evidence" for r in sink.rows if r["kind"] == "part")


def test_a_failing_call_is_still_timed_and_a_store_that_fails_never_stops_a_run():
    class Broken:
        def save_timings(self, cid, rows):
            raise RuntimeError("database is down")
    sc = timing.Scope(Broken(), "c", "p")
    f = timing.timed(lambda: 1 / 0, sc, "model call (text)")
    with pytest.raises(ZeroDivisionError):
        with sc.total("write the answer"):
            f()
    assert True                                                                       # the error is the call's own; recording added none


def test_bind_times_every_call_of_the_tools_and_leaves_the_rest_alone():
    sink = Sink()
    sc = timing.Scope(sink, "c", "p", "D-1", "Owners")
    tools = base.fake_tools()
    bound = timing.bind(tools, sc)
    assert bound is not tools and bound.kb is tools.kb and bound.doc_ids is tools.doc_ids          # a copy; what is not a call is the same
    assert bound.search("q", 3, None) == tools.search("q", 3, None)
    bound.llm_json("PROPERTY: X  [text]")
    with sc.total("gather the evidence"):
        pass
    assert {r["step"] for r in sink.rows if r["kind"] == "part"} == {"document search", "model call (structured)"}
    assert timing.bind(None, sc) is None


def test_the_summary_shows_the_steps_the_properties_and_what_was_not_a_call():
    rows = [
        {"phase_id": "p", "item_id": "D-1", "col": "Owners", "step": "gather the evidence", "part_of": "", "kind": "total", "seconds": 10.0, "calls": 1},
        {"phase_id": "p", "item_id": "D-1", "col": "Owners", "step": "wiki page search (model)", "part_of": "gather the evidence", "kind": "part", "seconds": 6.0, "calls": 3},
        {"phase_id": "p", "item_id": "D-1", "col": "Owners", "step": "document search", "part_of": "gather the evidence", "kind": "part", "seconds": 1.0, "calls": 4},
        {"phase_id": "p", "item_id": "D-1", "col": "Owners", "step": "write the answer", "part_of": "", "kind": "total", "seconds": 4.0, "calls": 1},
        {"phase_id": "p", "item_id": "D-1", "col": "Owners", "step": "model call: write the answer", "part_of": "write the answer", "kind": "part", "seconds": 3.5, "calls": 1},
        {"phase_id": "p", "item_id": "D-2", "col": "Owners", "step": "gather the evidence", "part_of": "", "kind": "total", "seconds": 8.0, "calls": 1},
        {"phase_id": "p", "item_id": "D-1", "col": "Domain", "step": "gather the evidence", "part_of": "", "kind": "total", "seconds": 2.0, "calls": 1},
    ]
    out = timing.summarise(rows, wall=15.0)
    assert out["seconds"] == 24.0 and out["wall"] == 15.0
    first = out["steps"][0]
    assert first["step"] == timing.OTHER and first["of"] == "gather the evidence" and abs(first["seconds"] - (10 + 8 + 2 - 7)) < 1e-9      # the time of the part beyond the calls that were timed
    pages = next(e for e in out["steps"] if e["step"] == "wiki page search (model)")
    assert pages["calls"] == 3 and pages["average"] == 2.0 and abs(pages["share"] - 6 / 24) < 1e-9
    assert [p["column"] for p in out["properties"]] == ["Owners", "Domain"] and out["properties"][0]["demands"] == 2
    assert out["properties"][0]["longest"] == "wiki page search (model)" and out["properties"][0]["seconds"] == 22.0
    assert timing.summarise([])["steps"] == [] and timing.summarise([])["properties"] == []


def _case_timings(monkeypatch):
    import importlib
    api = importlib.import_module("eawiki.api.cases")
    e, cid, _order, _seen = shipped._run()
    monkeypatch.setattr(api, "store", lambda: e.store)
    return api, e, cid


def test_a_run_records_its_planning_its_profiles_its_first_check_each_cell_and_the_request_text(monkeypatch):
    api, e, cid = _case_timings(monkeypatch)
    rows = e.store.timings(cid)
    totals = {(r["phase_id"], r["step"]) for r in rows if r["kind"] == "total"}
    assert ("screening", "plan the lookups") in totals and ("screening", "the first check") in totals and ("screening", "read what the demand mentions") in totals
    assert ("screening", "gather the evidence") in totals and ("screening", "write the answer") in totals and (shipped.PID, "write the answer") in totals
    cells = [r for r in rows if r["kind"] == "total" and r["step"] == "write the answer" and r["phase_id"] == shipped.PID and r["item_id"] and r["col"]]
    assert {r["item_id"] for r in cells} >= {"D-2026-001", "D-2026-003", "D-2026-004"} and {"Recommendation", "Request overview"} <= {r["col"] for r in cells}
    assert any(r["item_id"] == "_request" and r["col"] == "Request overview" for r in rows)                      # the text written once for the request has its own
    assert {r["step"] for r in rows if r["kind"] == "part" and r["part_of"] == "write the answer"} == {"model call: write the answer"}


def test_the_route_gives_the_summary_for_a_phase_and_a_new_run_starts_the_record_again(monkeypatch):
    api, e, cid = _case_timings(monkeypatch)
    app = FastAPI()
    app.include_router(api.router)
    c = TestClient(app)
    got = c.get(f"/api/cases/{cid}/timings", params={"phase": shipped.PID}).json()
    [ph] = got["phases"]
    assert ph["id"] == shipped.PID and ph["steps"] and ph["properties"] and ph["seconds"] > 0 and ph["running"] is False
    assert {"Recommendation", "Request overview"} <= {p["column"] for p in ph["properties"]}
    both = c.get(f"/api/cases/{cid}/timings").json()["phases"]
    assert [p["id"] for p in both] == ["screening", shipped.PID] and c.get("/api/cases/nope/timings").status_code == 404
    before = len(e.store.timings(cid, "screening"))
    e.run_phase(cid, "screening")                                                                      # a full run starts that phase's record again
    assert 0 < len(e.store.timings(cid, "screening")) <= before + 5
    e.run_phase(cid, "screening", only_item="D-2026-001", only_cols={"Domain"})                        # one cell added to it, nothing cleared
    assert len(e.store.timings(cid, "screening")) > 0


def test_the_summary_says_what_the_case_ran_with_which_is_what_it_was_started_with():
    spec = {"wiki_pages": True, "stages": [{"name": "S", "output": {"columns": [
        {"name": "A", "type": "text", "lookups": [{"find": "x", "from": "need", "match": "meaning", "in": [], "pages": False}]},
        {"name": "B", "type": "text", "lookups": [{"find": "y", "from": "need", "match": "meaning", "in": []}]},
        {"name": "C", "type": "text"}, {"name": "D", "type": "citations"}, {"name": "E", "type": "text", "derive": {"kind": "groups"}}]}}]}
    got = timing.settings_of(spec, spec["stages"][0])
    assert got == {"wiki_pages": True, "wiki_search": ["B", "C"], "own_questions": 2, "planned": ["C"]}           # A turned it off for itself; C has no questions, so a model plans them
    off = {**spec, "wiki_pages": False}
    off["stages"][0]["output"]["columns"][0]["lookups"][0]["pages"] = True                                         # a lookup that asks for it itself
    assert timing.settings_of(off, off["stages"][0])["wiki_search"] == ["A"] and timing.settings_of(off, off["stages"][0])["wiki_pages"] is False


def test_the_route_carries_those_settings(monkeypatch):
    api, e, cid = _case_timings(monkeypatch)
    app = FastAPI()
    app.include_router(api.router)
    [ph] = TestClient(app).get(f"/api/cases/{cid}/timings", params={"phase": shipped.PID}).json()["phases"]
    assert set(ph["settings"]) == {"wiki_pages", "wiki_search", "own_questions", "planned"} and "Handled with" not in ph["settings"]["planned"]
