"""Does retrieval bring the right block out of the hard Word test file? Opt-in script (the blocks must be extracted and described first).

The search is a TF-IDF stand-in over exactly the text the real index embeds (embed.embeddable_units: the description for a table or a
figure, the text for the rest); the real one is a vector search, so this tests what the index HOLDS, not how well a model ranks it.
For each question it says whether the block that holds the answer is among the top hits, and whether it reaches the answer step after
the passage fixes (labels set aside, what follows a label read, a caption bringing its figure or table).

    PYTHONPATH=src python tests/e2e_extraction_retrieval.py <folder with blocks/Test_Architecture_Pack.blocks.json and truth.json>
"""
import json
import math
import re
import sys
from pathlib import Path

from eawiki import embed
from eawiki.blocks import load_blocks
from eawiki.cases import passages as ps

D = Path(sys.argv[1])
blocks = load_blocks(D / "blocks/Test_Architecture_Pack.blocks.json")
units = embed.embeddable_units(blocks)
by_ord = {b.ordinal: b for b in blocks}


def toks(s):
    return re.findall(r"[a-z0-9]{2,}", str(s).lower())


DF = {}
for u in units:
    for t in set(toks(u["embed_text"])):
        DF[t] = DF.get(t, 0) + 1
N = len(units)


def vector_search(q, k=8):
    qt = toks(q)
    scored = []
    for u in units:
        c = {}
        for t in toks(u["embed_text"]):
            c[t] = c.get(t, 0) + 1
        num = sum(math.log(1 + N / DF[t]) * c[t] for t in qt if t in c)
        norm = math.sqrt(sum(v * v for v in c.values())) or 1
        scored.append((num / norm, u))
    scored.sort(key=lambda x: -x[0])
    seen, out = set(), []
    for s, u in scored:
        if s <= 0 or u["block_id"] in seen:
            continue
        seen.add(u["block_id"])
        out.append({"block_id": u["block_id"], "doc_id": u["doc_id"], "btype": u["type"], "section": " / ".join(u["section_path"]), "text": u["text"],
                    "distance": 1 - min(s, 1), "ordinal": u["ordinal"]})
        if len(out) == k:
            break
    return out


def expand(bid, window=1):
    n = by_ord[int(bid.split(":")[1])].ordinal
    out = []
    for o in range(n - window, n + window + 1):
        b = by_ord.get(o)
        if b is not None and b.type != "heading":
            text = b.text if b.type != "figure" else (b.description or "")
            out.append({"block_id": b.block_id, "btype": b.type, "section": " / ".join(b.section_path), "text": f"{b.doc_id} > {' / '.join(b.section_path)}\n{text}", "ordinal": b.ordinal})
    return out


# question, what must be in the answer step's text, which block holds it
QUESTIONS = [
    ("Which capabilities are in the Digital Transformation group?", ["Enterprise Architecture", "Consulting Support", "Digital Projects"], "figure 1 (heat map)"),
    ("What is the maturity rating of Innovation and Development?", ["Innovation and Development"], "figure 1 / big table"),
    ("Which capability covers evaluation forms and bonus results?", ["Job Performance"], "big table row"),
    ("Who owns the Job Performance capability?", ["Job Performance", "OU-11"], "big table row"),
    ("How does the Evaluate Service send data to the HR & Payroll Portal?", ["REST API"], "figure 2 (architecture)"),
    ("What is the application status of Evaluate?", ["Not in use"], "table 3.1"),
    ("Which strategic objective cuts manual work in HR and finance?", ["SO4", "manual work"], "objectives table"),
    ("What is the target for evaluation to payroll lead time?", ["2 days"], "nested KPI table"),
    ("What is the average maturity of Legal?", ["1.8"], "figure 3 (chart)"),
]


def answer_step_text(q, k=8):
    hits = vector_search(q, k * 3)
    out, _, _ = ps.reshape(hits, k, expand, q)
    from eawiki.cases import tableview
    return "\n".join(tableview.render(b["text"], q) if (b.get("btype") == "table") else b["text"] for b in out), [b["block_id"].split(":")[1] for b in out]


ok = 0
for q, must, where in QUESTIONS:
    raw = " ".join(b["text"] for b in vector_search(q, 8))
    text, ids = answer_step_text(q)
    in_raw = all(m.lower() in raw.lower() for m in must)
    in_text = all(m.lower() in text.lower() for m in must)
    ok += in_text
    print(f"{'OK  ' if in_text else 'MISS'} | top hits had it: {'yes' if in_raw else 'no ':3} | {q}\n       needs {must} from {where}; answer step got blocks {ids}")
print(f"\n{ok}/{len(QUESTIONS)} questions reach the answer step with the facts they need")
