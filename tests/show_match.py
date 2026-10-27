"""Print, for every demand, each reference mention and the entities step 1 matches it to (for review by eye).

    python tests/show_match.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402

from eawiki.cases import namelookup as nl  # noqa: E402

for d in kb.DEMANDS:
    print(f"\n{d['item']['demand_id']}  {d['item']['title']}")
    for m, gold in d["gold"]["mentions"].items():
        kinds = ["data"] if any(i.startswith("DE-") for i in gold) else ["app", "tech"]
        r = nl.resolve_entities(m, kb.NODES, kinds=kinds)
        other = nl.other_kinds(m, kb.NODES, kinds)
        shown = "; ".join(f"{c['id']} {c['name']} [{c['how']}{'' if c['strong'] else ', NOT strong'}]" for c in r[:3]) or "no entity"
        print(f"  {m!r:34} reference {gold or 'no entry'}  ->  {shown}" + ("  AMBIGUOUS" if nl.ambiguous(r) else "")
              + (f"   (also as: {', '.join(c['name'] for c in other)})" if other else ""))
