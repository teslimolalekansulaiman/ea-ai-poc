"""Comparing demands of one sheet, with the real model: 21 demands, three duplicate pairs and three related pairs.

    python tests/e2e_compare.py [--repeat 1] [--out file.json]

Each demand gets its real profile, its candidates among the other 20, and the model's verdicts. Scored against the
reference pairs of tests/kb_fixture.py: a duplicate pair must reach `same` from BOTH sides, a related pair must not be
`same`, and no other pair may be `same`. NOT part of the suite: it calls a model.
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402

from eawiki import subjects  # noqa: E402
from eawiki.cases import compare as cp  # noqa: E402
from eawiki.cases import gather as gmod  # noqa: E402
from eawiki.cases import profile as profmod  # noqa: E402

SPEC = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))
SHEET = [dict(d["item"], _id=d["item"]["demand_id"]) for d in kb.DEMANDS + kb.DUP_DEMANDS]
QUESTION = "whether another demand in the sheet asks for the same outcome, for the same users, on the same systems, even if it is worded differently"
SAME = {frozenset(p) for p in kb.SAME_PAIRS}
RELATED = {frozenset(p) for p in kb.RELATED_PAIRS}


def text_of(it):
    return gmod.item_text(SPEC, it)


def run(repeat_no):
    llm_json = lambda p: subjects.llm_json(p, "cli")        # noqa: E731
    llm_text = lambda p: subjects.llm_text(p, "cli", None)  # noqa: E731
    with ThreadPoolExecutor(8) as pool:
        profs = dict(pool.map(lambda it: (it["_id"], profmod.build_profile(gmod.labelled_fields(SPEC, it), llm_json)), SHEET))
        sets = cp.candidate_sets(SHEET, text_of, profs)
        res = list(pool.map(lambda it: (it["_id"], cp.run(QUESTION, it["_id"], text_of(it), profs[it["_id"]], [o for o in SHEET if o["_id"] != it["_id"]],
                                                        text_of, profs, llm_text, cands=sets[it["_id"]])), SHEET))
    verdict = {(a, i["id"]): i for a, r in res for i in r["items"]}
    bad = []
    for pair in SAME:
        a, b = sorted(pair)
        for x, y in ((a, b), (b, a)):
            v = verdict.get((x, y))
            if not v or v["verdict"] != "same":
                bad.append(f"duplicate pair {x}->{y}: {'not a candidate' if not v else v['verdict']}")
    for (x, y), v in verdict.items():
        if v["verdict"] == "same" and frozenset((x, y)) not in SAME:
            bad.append(f"false duplicate {x}->{y}: {v['reason']}")
        if v["verdict"] == "unread":
            bad.append(f"unread {x}->{y}")
    related = {tuple(sorted(p)): [verdict.get((a, b), {}).get("verdict", "not a candidate") for a, b in (sorted(p), sorted(p)[::-1])] for p in RELATED}
    return bad, related, res


def answers():
    """The whole chain with the real model: the comparison reaches the answer step, which decides Is duplicate, then the number."""
    from eawiki.cases import plan as pmod
    from eawiki.cases import solve as smod
    llm_json = lambda p: subjects.llm_json(p, "cli")        # noqa: E731
    llm_text = lambda p: subjects.llm_text(p, "cli", None)  # noqa: E731
    cols = {c["name"]: c for st in SPEC["stages"] for c in st["output"]["columns"]}
    flag, num = cols["Is duplicate"], cols["Duplicate demand number (in the sheet)"]
    tools = gmod.Tools(search=lambda q, k, d: [], blocks_by_ids=lambda ids: [], link=lambda t: {}, graph_facts=lambda ids: {}, llm_json=llm_json,
                       doc_ids=lambda: [], llm_text=llm_text)

    def one(args):
        it, profs, cache = args
        others = [o for o in SHEET if o["_id"] != it["_id"]]
        out = {}
        decided = {}
        for col in (flag, num):
            ev = gmod.gather(tools, pmod.default_plan(col, []), SPEC, it, others, cache, None, profs[it["_id"]], dict(decided), profs)
            cell = smod.solve(col, it, SPEC, ev, dict(decided), llm_json)
            decided[col["name"]] = cell["value"]
            out[col["name"]] = cell["value"]
        return it["_id"], out
    with ThreadPoolExecutor(8) as pool:
        profs = dict(pool.map(lambda it: (it["_id"], profmod.build_profile(gmod.labelled_fields(SPEC, it), llm_json)), SHEET))
        cache = {}
        res = dict(pool.map(one, [(it, profs, cache) for it in SHEET]))
    partner = {}
    for a, b in kb.SAME_PAIRS:
        partner.setdefault(a, set()).add(b)
        partner.setdefault(b, set()).add(a)
    bad = []
    for it in SHEET:
        i = it["_id"]
        got = res[i]["Is duplicate"]
        n = str(res[i]["Duplicate demand number (in the sheet)"])
        if i in partner:
            if got != "Yes" or not all(p in n for p in partner[i]):
                bad.append(f"{i}: Is duplicate {got!r}, number {n!r} (want Yes and {sorted(partner[i])})")
        elif got != "No" or any(x["_id"] in n for x in SHEET):
            bad.append(f"{i}: Is duplicate {got!r}, number {n!r} (want No and no number)")
    print(f"answers: {'all 21 demands right' if not bad else str(len(bad)) + ' wrong'}")
    for b in bad:
        print("   ", b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", action="store_true", help="also run the answer step for Is duplicate and the number")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.answers:
        answers()
        return
    out = []
    for n in range(a.repeat):
        bad, related, res = run(n)
        print(f"run {n + 1}: {'all pairs right' if not bad else str(len(bad)) + ' problems'}; related pairs (each side): {related}")
        for b in bad:
            print("   ", b)
        out.append({"bad": bad, "related": {"|".join(k): v for k, v in related.items()}, "items": {a: r["items"] for a, r in res}})
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
