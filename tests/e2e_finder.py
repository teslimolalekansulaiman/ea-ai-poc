"""Steps 2 and 3 measured with the real model: mentions that no word matches, against the knowledge base's list.

    python tests/e2e_finder.py [--batch 4] [--repeat 1] [--out file.json]

The cases (tests/kb_fixture.py FINDER_CASES) were written before the finder was run: abbreviations,
another wording, another language, and things the knowledge base does not have. They are sent in
batches like the mentions of one demand. Scored: a reference entity must be among the picks; for a
mention with no entry nothing may be picked. Extra picks beside the reference are listed, not hidden.
NOT part of the suite: it calls a model.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402

from eawiki import subjects  # noqa: E402
from eawiki.cases import namelookup as nl  # noqa: E402
from eawiki.cases import pagefinder as pf  # noqa: E402

INDEX = pf.build_index(kb.NODES, kb.page_entries())
KINDS = {"systems": ["app", "tech"], "data": ["data"]}


def llm(prompt):
    return subjects.llm_text(prompt, "cli", None)


def run(batch):
    ms = [{"text": m, "group": g} for m, g, _ in batch]
    r = pf.find(ms, INDEX, llm)
    out = []
    for m, g, gold in batch:
        picks = r["picks"][m]
        cands = pf.merge(nl.resolve_entities(m, kb.NODES, kinds=KINDS[g]), picks, KINDS[g])
        got = [c["id"] for c in cands["candidates"]]
        aside = [c["id"] for c in cands["other_kinds"]]
        ok = (set(gold) <= set(got)) if gold else not got
        out.append({"mention": m, "gold": gold, "picked": [it["node_id"] or it["slug"] for it in picks], "candidates": got, "set_aside": aside,
                    "ok": ok, "extra": [i for i in got if i not in gold], "status": r["status"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    for m, g, _ in kb.FINDER_CASES:                                          # these must be cases step 1 cannot settle
        assert not any(c["strong"] for c in nl.resolve_entities(m, kb.NODES, kinds=KINDS[g])), f"step 1 already settles {m!r}"
    allr = []
    t = time.time()
    for rep in range(a.repeat):
        cases = kb.FINDER_CASES[rep % a.batch:] + kb.FINDER_CASES[:rep % a.batch]           # a different grouping each repeat
        batches = [cases[i:i + a.batch] for i in range(0, len(cases), a.batch)]
        with ThreadPoolExecutor(len(batches)) as pool:
            res = [x for part in pool.map(run, batches) for x in part]
        allr.append(res)
        pos = [r for r in res if r["gold"]]
        neg = [r for r in res if not r["gold"]]
        print(f"run {rep + 1}: reference entity among the candidates {sum(r['ok'] for r in pos)}/{len(pos)}; "
              f"nothing picked where there is no entry {sum(r['ok'] for r in neg)}/{len(neg)}; "
              f"extra candidates beside a reference {sum(len(r['extra']) for r in pos)}; unavailable {sum(r['status'] != 'ok' for r in res)}")
        for r in res:
            if not r["ok"] or r["extra"] or r["set_aside"]:
                print(f"   {'BAD ' if not r['ok'] else '    '}{r['mention']!r}: reference {r['gold'] or 'no entry'} -> candidates {r['candidates']}"
                      + (f" set aside (other kind) {r['set_aside']}" if r["set_aside"] else ""))
    print(f"{time.time() - t:.0f}s")
    if a.out:
        Path(a.out).write_text(json.dumps(allr, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
