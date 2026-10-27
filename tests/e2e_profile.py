"""Phase 1 measured with the real model: what the demand mentions.

    python tests/e2e_profile.py [--workers 6] [--only D-101] [--out file.json]

For each of the 18 demands the profile step (eawiki.cases.profile) is run on the demand's own fields and
compared with the reference mentions of tests/kb_fixture.py (the systems and data a careful reader would
list). Reported per demand: reference mentions found, found under the wrong group, missing; and the
EXTRA mentions the model listed in the systems and data groups, which are shown for review rather than
scored as errors (an extra can be a fair reading of the demand). NOT part of the suite: it calls a model.
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

from eawiki import subjects  # noqa: E402
from eawiki.cases import gather as gmod  # noqa: E402
from eawiki.cases import profile as profmod  # noqa: E402

SPEC = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))


def llm(prompt):
    return subjects.llm_json(prompt, "cli")


def key(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(s).casefold())).strip()


def run_demand(d):
    item = dict(d["item"], _id=d["item"]["demand_id"])
    fields = gmod.labelled_fields(SPEC, item)
    prof = profmod.build_profile(fields, llm)
    got = {g: [m["text"] for m in prof.get(g, [])] for g in profmod.PROFILE_GROUPS}
    gold = {"systems": [m for m, ids in d["gold"]["mentions"].items() if not any(i.startswith("DE-") for i in ids)],
            "data": [m for m, ids in d["gold"]["mentions"].items() if any(i.startswith("DE-") for i in ids)]}
    found, wrong_group, missing = [], [], []
    for grp, items in gold.items():
        for m in items:
            if key(m) in {key(x) for x in got[grp]}:
                found.append(m)
            elif key(m) in {key(x) for g, xs in got.items() for x in xs}:
                wrong_group.append(m)
            else:
                missing.append(m)
    gold_keys = {key(m) for xs in gold.values() for m in xs}
    extras = {g: [x for x in got[g] if key(x) not in gold_keys] for g in ("systems", "data")}
    return {"id": d["item"]["demand_id"], "origin": prof.get("origin"), "gold": gold, "got": got,
            "found": found, "wrong_group": wrong_group, "missing": missing, "extras": extras}


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
    tf = tw = tm = te = tg = 0
    for r in res:
        n = len(r["found"]) + len(r["wrong_group"]) + len(r["missing"])
        ex = sum(len(v) for v in r["extras"].values())
        tf, tw, tm, te, tg = tf + len(r["found"]), tw + len(r["wrong_group"]), tm + len(r["missing"]), te + ex, tg + n
        flag = "ok " if not r["wrong_group"] and not r["missing"] else "BAD"
        print(f"{r['id']} {flag} found {len(r['found'])}/{n}" + (f"  wrong group {r['wrong_group']}" if r["wrong_group"] else "")
              + (f"  MISSING {r['missing']}" if r["missing"] else "") + f"  extras({ex}): " + "; ".join(r["extras"]["systems"] + r["extras"]["data"]))
    print(f"\nreference mentions: {tg}; found in the right group {tf}; found in the wrong group {tw}; missing {tm}; extras listed {te} ({te / max(len(res), 1):.1f} per demand)")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
