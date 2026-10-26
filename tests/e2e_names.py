"""End to end, with the real model: 14 demands through the six by-name properties, scored against the reference answers.

    python tests/e2e_names.py [--workers 6] [--only D-101,D-108] [--out results.json]

NOT part of the suite: it calls a model (the `cli` backend) and takes minutes. What is real: the
demand profile, the lookups' evidence rendering, the answer step and its code checks. What is
synthetic: the knowledge base (tests/kb_fixture.py) and the reference answers, which are judgments
made by following the EA team's steps on that fixture.
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402
import names_spec  # noqa: E402

from eawiki import subjects  # noqa: E402
from eawiki.cases import gather as gmod  # noqa: E402
from eawiki.cases import namelookup as nl  # noqa: E402
from eawiki.cases import plan as pmod  # noqa: E402
from eawiki.cases import profile as profmod  # noqa: E402
from eawiki.cases import solve as smod  # noqa: E402

SPEC = names_spec.build_spec()
COLS = {c["name"]: c for c in SPEC["stages"][0]["output"]["columns"]}
ORDER = ["Data classification", "Domain", "Impacted application", "Linked security capability", "Owners", "Duplicate with existing artefact"]
NAMES = {n["node_id"]: n for n in kb.NODES}
NONE = re.compile(r"^\s*(none|no link found|not identified|not assessed|not stated|n/a)\b", re.I)


def llm(prompt):
    return subjects.llm_json(prompt, "cli")


def as_list(v):
    if isinstance(v, list):
        return [str(x) for x in v]
    return [x.strip() for x in re.split(r"[;\n]", str(v or "")) if x.strip()]


def ids_in(values):
    """Entity ids a list of answers stands for: an ID written in it, else the best strong match for its name."""
    out = set()
    for v in values:
        if NONE.match(v):
            continue
        found = re.findall(r"\b[A-Z]{1,3}-\d+\b", v)
        if found:
            out |= set(found)
            continue
        head = re.sub(r"\s*\(.*?\)", "", v).strip()
        c = kb.entities(head)["candidates"]
        if c and c[0]["strong"]:
            out.add(c[0]["id"])
    return out


def sets_match(got, gold):
    return got == gold, sorted(got - gold), sorted(gold - got)


def neighbours(ids):
    return {b if a in ids else a for a, _r, b in kb.EDGES if a in ids or b in ids}


def named_in(text, all_kinds=False):
    """Entities the demand's own words name, by name or alias: a defensible extra (applications unless all_kinds)."""
    words = nl.core(text)
    return {n["node_id"] for n in kb.NODES if (all_kinds or nl.family(n["type"]) == "app")
            and any(nl.core(x) and nl.core(x) <= words for x in [n["name"]] + n["aliases"])}


def score(name, cell, gold, demand_text="", decided=None):
    """(ok, detail) for one property of one demand. Security and Owners are scored against what follows from the
    applications this run itself decided, so one wrong application is not counted three times."""
    status, value = cell["status"], cell["value"]
    decided = decided or {}
    vals = as_list(value)
    empty = status != "answered" or not vals or all(NONE.match(v) for v in vals)
    g = gold
    if name == "Data classification":
        want = g["classification"]
        if want in ("Not stated", "Not assessed"):
            return (empty or str(value) in ("Not stated", "Not assessed")), f"{value!r} (want {want})"
        if g.get("ask_ok") and status != "answered" and cell.get("question"):
            return True, f"asked: {cell['question'][:100]}"       # the demand really is ambiguous: a question is the right answer
        return str(value) in (g.get("classification_ok") or {want}), f"{value!r} (want {sorted(g.get('classification_ok') or {want})})"
    if name == "Domain":
        want = set(g["domain"] or [])
        if not want:
            return empty, f"{vals} (want none)"
        got = set(vals)
        main = bool(vals) and vals[0] == g["domain"][0]
        return main and want <= got, f"{vals} (want {g['domain']}; first must be {g['domain'][0]}, extras are allowed)"
    if name == "Impacted application":
        want = set(g["apps"])
        if not want:
            return empty, f"{vals} (want none)"
        got = ids_in(vals) & set(NAMES)
        allowed = neighbours(want) | named_in(demand_text)
        extra = sorted(got - want - allowed)
        return not extra and want <= got, f"missing {sorted(want - got)}, unsupported extras {extra}, defensible extras {sorted((got - want) & allowed)}"
    if name == "Linked security capability":
        apps = ids_in(as_list(decided.get("Impacted application"))) & set(NAMES)
        want = {c for a in apps for c in NAMES[a]["controls"]}
        if not want:
            return True, "no application decided: not scored"
        got = ids_in(vals) & {i for i in NAMES if i.startswith("SC-")}
        return want <= got and not (got - want), f"missing {sorted(want - got)} extra {sorted(got - want)} (controls of the applications it decided)"
    if name == "Owners":
        apps = ids_in(as_list(decided.get("Impacted application"))) & set(NAMES)
        techs = {i for m, ids in g["mentions"].items() for i in ids if i.startswith("T-")}
        want = {NAMES[i]["owner"].casefold() for i in apps | techs}
        if not want:
            return empty, f"{vals} (want none)"
        # the guidance also takes the owner of impacted data, platforms and controls: those the demand names or the applications sit on
        near = neighbours(apps) | {c for a in apps for c in NAMES[a]["controls"]} | named_in(demand_text, all_kinds=True)
        extra_ok = {NAMES[i]["owner"].casefold() for i in near if i in NAMES}
        got = {v.casefold().strip() for v in vals if not NONE.match(v)}
        hit = {w for w in want if any(w in x for x in got)}
        extra = [x for x in got if not any(w in x for w in want | extra_ok)]
        return hit == want and not extra, f"missing {sorted(want - hit)} unsupported extra {extra}"
    if name == "Duplicate with existing artefact":
        if name in g.get("ask_ok_for", ()) and status != "answered" and cell.get("question"):
            return True, f"asked: {cell['question'][:100]}"
        text = " ".join(vals) if not empty else ""
        if g["artefact"] is None:
            return empty, f"{vals} (want none)"
        found = {i for i in g["artefact"] if i in text or (not i.startswith("P-") and NAMES[i]["name"].split()[0].casefold() in text.casefold())}
        return found == set(g["artefact"]), f"found {sorted(found)} want {sorted(g['artefact'])}"
    raise KeyError(name)


def run_demand(d):
    item = dict(d["item"], _id=d["item"]["demand_id"])
    tools = kb.make_tools(llm)
    fields = gmod.labelled_fields(SPEC, item)
    prof = profmod.build_profile(fields, llm)
    item_text = " ".join(v for _l, v in fields.values())
    decided, cells, rows = {}, {}, []
    for name in ORDER:
        col = COLS[name]
        plan = pmod.default_plan(col, kb.DOCS)
        ev = gmod.gather(tools, plan, SPEC, item, [], {}, None, prof, decided)
        cell = smod.solve(col, item, SPEC, ev, decided, llm)
        cells[name] = {k: cell.get(k) for k in ("value", "status", "evidence", "need", "question")} | {"note": next((h for h in cell["how"] if h.startswith("Model's note")), "")}
        decided[name] = cell["value"]
        ok, detail = score(name, cell, d["gold"], item_text, decided)
        rows.append((name, ok, detail))
    got = {m["text"] for g in ("systems", "data") for m in prof.get(g, [])}
    return {"id": d["item"]["demand_id"], "profile": sorted(got), "gold_mentions": sorted(d["gold"]["mentions"]),
            "scores": {n: {"ok": ok, "detail": det} for n, ok, det in rows}, "cells": cells}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    demands = [d for d in kb.DEMANDS if not only or d["item"]["demand_id"] in only]
    t = time.time()
    with ThreadPoolExecutor(a.workers) as pool:
        res = list(pool.map(run_demand, demands))
    print(f"{len(res)} demands in {time.time() - t:.0f}s\n")
    tot = {n: 0 for n in ORDER}
    for r in res:
        marks = " ".join(("ok " if r["scores"][n]["ok"] else "BAD") for n in ORDER)
        for n in ORDER:
            tot[n] += r["scores"][n]["ok"]
        print(r["id"], marks, "| mentions:", "ok" if set(r["profile"]) == set(r["gold_mentions"]) else f"profile {r['profile']} vs {r['gold_mentions']}")
        for n in ORDER:
            if not r["scores"][n]["ok"]:
                print(f"      {n}: {r['scores'][n]['detail']}   [{r['cells'][n]['status']}] {r['cells'][n].get('note', '')[:160]}")
    print("\nper property:", {n: f"{v}/{len(res)}" for n, v in tot.items()})
    print("all six right:", sum(all(r["scores"][n]["ok"] for n in ORDER) for r in res), "of", len(res))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
