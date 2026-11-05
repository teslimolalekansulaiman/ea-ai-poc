"""How long each step of a case run took, so that what makes a run slow can be seen and not guessed.

A cell (one property for one demand) is decided in two parts: the evidence is gathered (searches, the graph, the wiki, the page finder, a
comparison with the other demands, a diagram read by a vision model), then the answer is written (one model call, or a few). Each part is a
`Scope`: it holds the seconds spent in each kind of call and, when it ends, the seconds the whole part took. What the whole part took beyond
the calls that were timed is code and waiting, shown as such.

The tools a part uses are wrapped for it (`bind`), so every call is timed under its own label without the steps having to know. A step that
wants a better name than the kind of call (the page finder is a model call, but "wiki page search" says more) asks for it with `.labelled`.
Nothing here changes what a call returns or when it is made, and a failure to record never stops a run.

`summarise` turns the stored rows into what the screen shows: the steps by the time they took, the properties by the time they took, and
the time the phase took on the clock, which is shorter than the sum of its parts because the parts run side by side.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional

CALLS = {"search": "document search", "blocks_by_ids": "read passages", "link": "name the entities in the demand", "graph_facts": "read the graph",
         "llm_json": "model call (structured)", "llm_text": "model call (text)", "expand": "read what follows a passage", "fetch_parts": "read parts of a table",
         "read_image": "read a diagram (vision model)"}
OTHER = "code and waiting"


class Scope:
    """The measurements of one part of one cell (or one step of a phase), kept until it ends and then stored in one go."""

    def __init__(self, store, cid: str, phase_id: str, item_id: str = "", col: str = ""):
        self.store, self.cid, self.phase_id, self.item_id, self.col = store, cid, phase_id, item_id, col
        self.parts: dict = {}
        self.totals: dict = {}
        self._lock = threading.Lock()

    def add(self, step: str, seconds: float) -> None:
        with self._lock:
            p = self.parts.setdefault(step, [0.0, 0])
            p[0] += seconds
            p[1] += 1

    @contextmanager
    def total(self, label: str):
        """Time the whole part under `label`, and store what was measured when it ends (also when it fails)."""
        t = time.perf_counter()
        try:
            yield self
        finally:
            with self._lock:
                self.totals[label] = self.totals.get(label, 0.0) + (time.perf_counter() - t)
            self.flush(label)

    def flush(self, label: str) -> None:
        try:
            with self._lock:
                parts, self.parts = self.parts, {}
                total = self.totals.pop(label, None)
            rows = [{"phase_id": self.phase_id, "item_id": self.item_id, "col": self.col, "step": k, "part_of": label, "kind": "part",
                     "seconds": v[0], "calls": v[1]} for k, v in parts.items()]
            if total is not None:
                rows.append({"phase_id": self.phase_id, "item_id": self.item_id, "col": self.col, "step": label, "part_of": "", "kind": "total",
                             "seconds": total, "calls": 1})
            self.store.save_timings(self.cid, rows)
        except Exception:
            pass                                                       # timing is for looking at; it never stops a run


def timed(fn: Optional[Callable], scope: Scope, label: str) -> Optional[Callable]:
    """`fn`, timed under `label`. `.labelled(name)` is the same call timed under a better name."""
    if fn is None:
        return None

    def make(name: str):
        def run(*a, **k):
            t = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                scope.add(name, time.perf_counter() - t)
        return run

    run = make(label)
    run.labelled = make                                               # type: ignore[attr-defined]
    return run


def bind(tools, scope: Scope):
    """A copy of the tools whose calls are timed into `scope`. The wiki's own reads (code) are not wrapped: they are the part that is not a call."""
    if tools is None:
        return None
    changes = {f: timed(getattr(tools, f), scope, label) for f, label in CALLS.items() if getattr(tools, f, None) is not None}
    return dataclasses.replace(tools, **changes)


def labelled(fn: Optional[Callable], name: str) -> Optional[Callable]:
    """`fn` timed under `name` when it is a timed call, and `fn` itself when it is not (no timing, or an untimed test double)."""
    if fn is not None and hasattr(fn, "labelled"):
        return fn.labelled(name)
    return fn


def summarise(rows: list[dict], wall: Optional[float] = None, names: Optional[dict] = None) -> dict:
    """{steps: [{step, of, seconds, calls, average, share}], properties: [{column, seconds, demands, average, longest}], seconds, wall}.
    `seconds` adds the parts, which run side by side; `wall` is the time on the clock for the phase, when known."""
    tot = [r for r in rows if r["kind"] == "total"]
    parts = [r for r in rows if r["kind"] == "part"]
    by_step: dict = {}
    for r in parts:
        k = (r["part_of"], r["step"])
        e = by_step.setdefault(k, {"step": r["step"], "of": r["part_of"], "seconds": 0.0, "calls": 0})
        e["seconds"] += r["seconds"]
        e["calls"] += r["calls"]
    total_of: dict = {}
    for r in tot:
        total_of[r["step"]] = total_of.get(r["step"], 0.0) + r["seconds"]
    for label, secs in total_of.items():
        inside = sum(e["seconds"] for (of, _), e in by_step.items() if of == label)
        rest = secs - inside
        if rest > 0.0005:
            by_step[(label, OTHER)] = {"step": OTHER, "of": label, "seconds": rest, "calls": 0}
    grand = sum(total_of.values()) or 1.0
    steps = sorted(({**e, "average": (e["seconds"] / e["calls"]) if e["calls"] else 0.0, "share": e["seconds"] / grand} for e in by_step.values()),
                   key=lambda e: -e["seconds"])
    per: dict = {}
    for r in tot:
        if not r["col"]:
            continue
        e = per.setdefault(r["col"], {"column": r["col"], "seconds": 0.0, "items": set()})
        e["seconds"] += r["seconds"]
        e["items"].add(r["item_id"])
    biggest: dict = {}
    for r in parts:
        if not r["col"]:
            continue
        cur = biggest.get(r["col"])
        agg = (cur or {}).get(r["step"], 0.0) + r["seconds"]
        biggest.setdefault(r["col"], {})[r["step"]] = agg
    props = []
    for col, e in per.items():
        n = max(len(e["items"]), 1)
        top = max(biggest.get(col, {}).items(), key=lambda kv: kv[1], default=(None, 0.0))
        props.append({"column": col, "seconds": e["seconds"], "demands": len(e["items"]), "average": e["seconds"] / n,
                      "longest": top[0] or "", "longest_seconds": top[1]})
    props.sort(key=lambda p: -p["seconds"])
    return {"steps": steps, "properties": props, "seconds": sum(total_of.values()), "wall": wall, "names": names or {}}
