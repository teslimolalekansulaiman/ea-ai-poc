"""The relationship suggestions, drafted by the real model for every by-name lookup of the six name properties.

    python tests/e2e_relsuggest.py [--repeat 2]

The graph is the test knowledge base's, the relationship types are the real metamodel's. Prints what the model proposes,
with how many edges the graph holds for it, for the owner to read and judge: there is no right answer to score, only
proposals to compare with the owner's own list (docs/NAME_LOOKUP_SETTINGS.xlsx). NOT part of the suite: it calls a model.
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
import names_spec  # noqa: E402

from eawiki import subjects  # noqa: E402
from eawiki.cases import graphread, relsuggest  # noqa: E402
from eawiki.query import graphquery as gq  # noqa: E402

MM = json.loads((ROOT / "data" / "togaf92_metamodel.json").read_text(encoding="utf-8"))
EDGE_TYPES = [{"key": k, **v} for k, v in MM["edge_types"].items()]
NODES, EDGES = kb.graph_parts()
COUNTS = graphread.relation_counts(gq._Graph(NODES, EDGES, {}))
G = names_spec.G


def llm(prompt):
    return subjects.llm_text(prompt, "cli", None)


def one(job):
    col, lk = job
    prop = {"name": col["name"], **{k: G[col["name"]].get(k) for k in ("description", "how_to_resolve", "rules")}}
    return col["name"], lk, relsuggest.suggest(prop, lk, EDGE_TYPES, COUNTS, llm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()
    jobs = [(c, lk) for c in names_spec.COLS for lk in c["lookups"] if lk["match"] == "name"] * a.repeat
    with ThreadPoolExecutor(8) as pool:
        res = list(pool.map(one, jobs))
    last = None
    for name, lk, out in res:
        if name != last:
            print(f"\n## {name}")
            last = name
        print(f"  lookup: {lk['find']}  [kinds: {', '.join(lk.get('types') or []) or 'any'}]  status {out['status']}")
        for s in out["suggestions"]:
            print(f"     {s['relation']:18} {s['direction']:5} edges {s['edges']:2}  {s['why']}")
        if not out["suggestions"]:
            print("     (none)")


if __name__ == "__main__":
    main()
