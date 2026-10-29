"""Ask, fast and deep, over the extracted hard Word test file: what reaches the answer step in each mode. Opt-in script.

The index is a TF-IDF stand-in over exactly the units the real index embeds (table windows included, with their part tags); the page search
and the answer are not called (the page search is told 'none', the image reader returns the stored description). So this tests what the
two modes SHOW the model, not how a real embedding ranks or how a model answers.

    PYTHONPATH=src python tests/e2e_ask_deep.py <folder with blocks/Test_Architecture_Pack.blocks.json>
"""
import math
import re
import sys
from pathlib import Path

from eawiki import embed, lanes
from eawiki.blocks import load_blocks
from eawiki.query import graph as qg
from eawiki.query import route as rt

D = Path(sys.argv[1])
blocks = load_blocks(D / "blocks/Test_Architecture_Pack.blocks.json")
units = embed.embeddable_units(blocks)
by_ord = {b.ordinal: b for b in blocks}
DESC = {b.block_id: (b.description or "") for b in blocks}


def toks(s):
    return re.findall(r"[a-z0-9]{2,}", str(s).lower())


DF = {}
for u in units:
    for t in set(toks(u["embed_text"])):
        DF[t] = DF.get(t, 0) + 1
N = len(units)


def row(u, score):
    return {"block_id": u["block_id"], "doc_id": u["doc_id"], "btype": u["type"], "section": " / ".join(u["section_path"]), "text": u["text"],
            "distance": 1 - min(score, 1), "ordinal": u["ordinal"], "part": u.get("part", 1), "parts": u.get("parts", 1),
            "rows_from": u.get("rows_from"), "rows_to": u.get("rows_to"), "rows_total": u.get("rows_total")}


class Index:
    def vector_search(self, q, k=8, kinds=None, docs=None, types=None):
        qt, scored = toks(q), []
        for u in units:
            if types and u["type"] not in types:
                continue
            c = {}
            for t in toks(u["embed_text"]):
                c[t] = c.get(t, 0) + 1
            num = sum(math.log(1 + N / DF[t]) * c[t] for t in qt if t in c)
            scored.append((num / (math.sqrt(sum(v * v for v in c.values())) or 1), u))
        scored.sort(key=lambda x: -x[0])
        seen, out = set(), []
        for s, u in scored:
            if s <= 0 or (u["block_id"], u.get("part", 1)) in seen:
                continue
            seen.add((u["block_id"], u.get("part", 1)))
            out.append(row(u, s))
            if len(out) == k:
                break
        return out

    def lane_search(self, q, lane, k=5, kinds=None, docs=None):
        return self.vector_search(q, k=k, types=list(lanes.types_of(lane)))

    def expand(self, bid, window=1):
        n = int(bid.split(":")[1])
        out = []
        for o in range(n - window, n + window + 1):
            b = by_ord.get(o)
            if b is not None and b.type != "heading":
                out.append({"block_id": b.block_id, "btype": b.type, "section": " / ".join(b.section_path), "ordinal": b.ordinal,
                            "text": f"{b.doc_id} > {' / '.join(b.section_path)}\n" + (b.text if b.type != "figure" else (b.description or ""))})
        return out

    def blocks_by_ids(self, ids):
        return [row(u, 0) for u in units if u["block_id"] in set(ids)]


class NoPages:
    def wiki_entries(self):
        return []

    def page(self, slug):
        return None


qg._retriever = lambda: Index()
qg._kb = lambda: NoPages()
qg.llm_text = lambda p, backend, model: "PAGES: none"
qg._figure_reader = lambda: (lambda bid, prompt: DESC.get(bid) or None)

QUESTIONS = [
    ("Which capabilities are in the Digital Transformation group?", ["Enterprise Architecture", "Consulting Support", "Digital Projects"]),
    ("What is the maturity rating of Innovation and Development?", ["Innovation and Development"]),
    ("Which capability covers evaluation forms and bonus results?", ["Job Performance"]),
    ("Who owns the Job Performance capability?", ["Job Performance", "OU-11"]),
    ("How does the Evaluate Service send data to the HR & Payroll Portal?", ["REST API"]),
    ("What is the application status of Evaluate?", ["Not in use"]),
    ("Which strategic objective cuts manual work in HR and finance?", ["SO4", "manual work"]),
    ("What is the target for evaluation to payroll lead time?", ["2 days"]),
    ("What is the average maturity of Legal?", ["1.8"]),
]


def context(q, deep):
    s = {"question": q, "k": 8, "route": rt.route(q), "use_llm": True, "deep": deep}
    s.update(qg.n_retrieve(s))
    got = qg.n_relevance(s)
    return got.get("context") or got.get("answer", ""), s


tot = {False: 0, True: 0}
for q, must in QUESTIONS:
    res = {}
    for deep in (False, True):
        ctx, s = context(q, deep)
        res[deep] = all(m.lower() in ctx.lower() for m in must)
        tot[deep] += res[deep]
    ctx, s = context(q, True)
    print(f"fast {'OK  ' if res[False] else 'MISS'} | deep {'OK  ' if res[True] else 'MISS'} | {q}\n       deep sections: "
          + "; ".join(f"{e['lane']}{'' if e['complete'] else ' (partial)'}" for e in s["evidence"]) + f" | context {len(ctx)} chars")
print(f"\nfast {tot[False]}/{len(QUESTIONS)}   deep {tot[True]}/{len(QUESTIONS)}")
