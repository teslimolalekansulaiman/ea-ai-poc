"""Score a case against expected answers.

The EA team's example output gives an expected value for each property of each demand. This compares
what the system produced with it, property by property, so the properties whose lookups or guidance
are weak show up as numbers instead of as impressions. It scores values only: free text is left out,
and nothing here changes a case.

    python -m eawiki.cases.score <case id> [--gold use_cases/samples/<use case>-gold.json]

A value is compared as a set of words separated by ';'. Where the expected answer holds IDs (such as
O-02, I-04, C-204) the IDs are compared, because the explanation around them is worded differently.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

ID = re.compile(r"\b[A-Z]{1,3}-\d+(?:-\d+)?\b")
NOTSET = {"", "none", "not assessed", "not checked", "no score", "no link found", "not identified"}


def _text(v) -> str:
    return "; ".join(map(str, v)) if isinstance(v, list) else ("" if v is None else str(v))


def _norm_set(v) -> set:
    return {re.sub(r"\s+", " ", x).strip().casefold() for x in re.split(r"[;\n]", _text(v)) if x.strip()}


def compare(expected, got) -> str:
    """'match' | 'partial' | 'wrong' for an answered cell."""
    e_ids, g_ids = set(ID.findall(_text(expected))), set(ID.findall(_text(got)))
    if e_ids:
        if e_ids == g_ids:
            return "match"
        return "partial" if e_ids & g_ids else "wrong"
    e, g = _norm_set(expected), _norm_set(got)
    if e == g:
        return "match"
    if e and g and len(e & g) / len(e | g) >= 0.5:
        return "partial"
    # one word in an expected phrase: accept "Standard" for "Standard (Medium)" style answers
    if len(e) == 1 and len(g) == 1 and (next(iter(e)) in next(iter(g)) or next(iter(g)) in next(iter(e))):
        return "partial"
    return "wrong"


def score(cells: list[dict], gold: dict, phase: Optional[str] = None) -> dict:
    """cells: the case's cells; gold: the gold file. Returns per-property counts and the misses."""
    phase = phase or gold.get("stage") or "screening"
    by = {(c["item_id"], c["column"]): c for c in cells if c["phase_id"] == phase}
    props: dict = {}
    misses = []
    for iid, item in gold["items"].items():
        for col, exp in item["expected"].items():
            cell = by.get((iid, col))
            if cell is None:
                continue                                         # the demand is not in this case
            p = props.setdefault(col, {"match": 0, "partial": 0, "wrong": 0, "asked": 0, "empty": 0, "n": 0})
            p["n"] += 1
            if cell["status"] in ("needs_input", "needs_source"):
                p["asked"] += 1
                kind = "asked"
            elif _text(cell["value"]).strip().casefold() in NOTSET and _text(exp).strip().casefold() not in NOTSET:
                p["empty"] += 1
                kind = "empty"
            else:
                kind = compare(exp, cell["value"])
                p[kind] += 1
            if kind != "match":
                misses.append({"item": iid, "property": col, "result": kind, "expected": _text(exp)[:140],
                               "got": _text(cell["value"])[:140]})
    for p in props.values():
        p["accuracy"] = round((p["match"] + 0.5 * p["partial"]) / p["n"], 2) if p["n"] else 0.0
    n = sum(p["n"] for p in props.values())
    tot = {k: sum(p[k] for p in props.values()) for k in ("match", "partial", "wrong", "asked", "empty")}
    return {"properties": props, "total": dict(tot, n=n, accuracy=round((tot["match"] + 0.5 * tot["partial"]) / n, 2) if n else 0.0),
            "misses": misses}


def render(rep: dict) -> str:
    rows = sorted(rep["properties"].items(), key=lambda kv: kv[1]["accuracy"])
    out = [f"{'property':58} {'n':>3} {'match':>5} {'part.':>5} {'wrong':>5} {'asked':>5} {'empty':>5}  accuracy"]
    for name, p in rows:
        out.append(f"{name[:58]:58} {p['n']:>3} {p['match']:>5} {p['partial']:>5} {p['wrong']:>5} {p['asked']:>5} {p['empty']:>5}  {p['accuracy']:.2f}")
    t = rep["total"]
    out.append(f"{'ALL':58} {t['n']:>3} {t['match']:>5} {t['partial']:>5} {t['wrong']:>5} {t['asked']:>5} {t['empty']:>5}  {t['accuracy']:.2f}")
    return "\n".join(out)


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    from eawiki.cases.store import store
    cid = argv[0]
    case = store().get_case(cid)
    if not case:
        sys.exit(f"no case {cid}")
    gp = argv[argv.index("--gold") + 1] if "--gold" in argv else f"use_cases/samples/{case['use_case_id']}-gold.json"
    rep = score(store().cells(cid), json.loads(Path(gp).read_text(encoding="utf-8")))
    print(render(rep))
    for m in rep["misses"][:40]:
        print(f"  {m['item']} {m['property'][:34]}: {m['result']}; expected {m['expected']!r}; got {m['got']!r}")


if __name__ == "__main__":
    main(sys.argv[1:])
