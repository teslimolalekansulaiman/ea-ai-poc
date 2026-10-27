"""The seven properties through the real case engine and the real model, on the test knowledge base.

    python tests/e2e_seven.py [--only D-101,D-2026-103] [--workers 8] [--out file.json]

The seven: Data classification, Domain, Impacted application, Linked security capability, Owners, Duplicate with existing
artefact and Is duplicate (with Demand type, which Linked security capability builds on, and the intake gate that stops an
invalid demand). The sheet is the 18 demands, the 3 duplicate-test demands and the 4 samples (a digital demand, the same
demand worded differently, a people demand, an incident). What is real: the engine, the gate, the profile, the six steps
of the page finder, the comparison with the other demands, the answer step and its checks, and the model (`cli` backend).
What is not: the knowledge base is the synthetic one in tests/kb_fixture.py, and the passage search is lexical, because
the vector search cannot run here. Reference answers are judgments. NOT part of the suite: it calls a model.
"""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402
import kb_tools  # noqa: E402
import seven_scoring as sc  # noqa: E402

from eawiki import history, subjects  # noqa: E402

history.DB_PATH = Path(tempfile.mkdtemp()) / "seven.db"

from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import CaseStore  # noqa: E402

PROPS = ["Data classification", "Domain", "Impacted application", "Linked security capability", "Owners",
         "Duplicate with existing artefact / artefact name", "Is duplicate"]
SHORT = {"Duplicate with existing artefact / artefact name": "Duplicate with existing artefact"}
KEEP = ["Is it a true demand?", "Demand type"] + PROPS


def spec():
    s = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))
    st = s["stages"][0]
    st["output"]["columns"] = [c for c in st["output"]["columns"] if c["name"] in KEEP]
    st.pop("consistency", None)
    s["stages"] = [st]
    for c in st["output"]["columns"]:
        c["uses"] = [u for u in c.get("uses", []) if u in KEEP]
    return s


def items():
    return [dict(d["item"], _id=d["item"]["demand_id"]) for d in kb.DEMANDS + kb.DUP_DEMANDS + kb.SAMPLES]


SAME = {frozenset(p) for p in kb.SAME_PAIRS + [("D-2026-101", "D-2026-102")]}


def score_sample(i, cells):
    v = lambda n: cells[n]["value"]                                    # noqa: E731
    st = lambda n: cells[n]["status"]                                   # noqa: E731
    out = []
    if i == "D-2026-104":                                               # the incident: stopped at the gate, everything else Not assessed
        out.append(("gate stops it", v("Is it a true demand?") != "Yes", str(v("Is it a true demand?"))[:80]))
        out.append(("the rest not assessed", all("not assessed" in str(v(p)).casefold() for p in PROPS), {p: v(p) for p in PROPS}))
        return out
    out.append(("gate passes it", v("Is it a true demand?") == "Yes", v("Is it a true demand?")))
    if i in ("D-2026-101", "D-2026-102"):
        got = sc.ids_in(sc.as_list(v("Impacted application"))) & set(sc.NAMES)
        out.append(("applications", {"C-209", "C-207"} <= got, sorted(got)))
        out.append(("domain main Application", sc.as_list(v("Domain"))[:1] == ["Application"], v("Domain")))
        out.append(("classification Internal or Confidential", str(v("Data classification")) in ("Internal", "Confidential"), v("Data classification")))
    if i == "D-2026-103":
        out.append(("demand type People", v("Demand type") == "People", v("Demand type")))
        out.append(("no application", not sc.ids_in(sc.as_list(v("Impacted application"))), v("Impacted application")))
        out.append(("domain Business first", sc.as_list(v("Domain"))[:1] == ["Business"], v("Domain")))
        out.append(("classification Not stated", str(v("Data classification")) in ("Not stated", "Not assessed") or st("Data classification") != "answered", v("Data classification")))
        out.append(("security Not applicable", "not applicable" in str(v("Linked security capability")).casefold(), v("Linked security capability")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    rows = [it for it in items() if not only or it["_id"] in only]
    llm_json = lambda p: subjects.llm_json(p, "cli")                   # noqa: E731
    llm_text = lambda p: subjects.llm_text(p, "cli", None)             # noqa: E731
    eng = Engine(CaseStore(), lambda: kb_tools.make_tools(llm_json, llm_text), workers=a.workers)
    cid = eng.create(spec(), rows, "seven")
    t = time.time()
    eng.run_phase(cid, "screening")
    cells = {}
    for c in eng.store.cells(cid, "screening"):
        cells.setdefault(c["item_id"], {})[c["column"]] = {"value": c["value"], "status": c["status"], "evidence": c["evidence"],
                                                           "question": "asked" if c["status"] == "needs_input" else ""}
    print(f"{len(rows)} demands in {time.time() - t:.0f}s\n")
    gold = {d["item"]["demand_id"]: d["gold"] for d in kb.DEMANDS}
    tot = {SHORT.get(p, p): [0, 0] for p in PROPS}
    report = {}
    for it in rows:
        i = it["_id"]
        cs = cells.get(i, {})
        lines = []
        if i in gold:
            decided = {n: c["value"] for n, c in cs.items()}
            text = " ".join(str(v) for k, v in it.items() if not k.startswith("_"))
            for p in PROPS[:-1]:
                ok, detail = sc.score(SHORT.get(p, p), cs[p], gold[i], text, {SHORT.get(k, k): v for k, v in decided.items()})
                lines.append((SHORT.get(p, p), ok, detail))
        elif i.startswith("D-2026-"):
            for label, ok, detail in score_sample(i, cs):
                lines.append((label, ok, detail))
        partner = {y for pr in SAME if i in pr for y in pr if y != i and y in {r["_id"] for r in rows}}
        flag = str(cs.get("Is duplicate", {}).get("value"))
        if str(cs.get("Is it a true demand?", {}).get("value")) == "Yes":      # a demand stopped at the gate never reaches the comparison
            lines.append(("Is duplicate", flag == ("Yes" if partner else "No"), f"{flag} (want {'Yes' if partner else 'No'}{', partner ' + ', '.join(sorted(partner)) if partner else ''})"))
        for p, ok, _d in lines:
            if SHORT.get(p, p) in tot:
                tot[SHORT.get(p, p)][0] += ok
                tot[SHORT.get(p, p)][1] += 1
        report[i] = [(p, ok, str(d)[:300]) for p, ok, d in lines]
        bad = [(p, d) for p, ok, d in lines if not ok]
        print(f"{i} {'ok ' if not bad else 'BAD'} " + " ".join(('+' if ok else '-') for _p, ok, _d in lines))
        for p, d in bad:
            print(f"      {p}: {str(d)[:240]}")
    print("\nper property:", {p: f"{r[0]}/{r[1]}" for p, r in tot.items()})
    if a.out:
        Path(a.out).write_text(json.dumps({"cells": cells, "report": report}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
