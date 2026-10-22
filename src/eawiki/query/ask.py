"""Single entry point: ask a question against the EA GraphRAG wiki.

    python -m eawiki.query.ask "where is applicant data stored?"
    python -m eawiki.query.ask "what depends on the Payment Gateway?" --k 8
    python -m eawiki.query.ask "..." --no-llm      # show retrieval only (no model call)

Flow (a DAG): route -> retrieve (vector and/or graph) -> assemble -> answer.
The model backend is `--backend` (cli today; `pulse` once wired). This is the
capability a use-case *skill* will call later.
"""

from __future__ import annotations

import argparse

from eawiki.query import answer as ans
from eawiki.query import route as rt
from eawiki.query.retrieve import Retriever


def ask(question: str, k: int = 8, backend: str = "cli", model=None,
        use_llm: bool = True) -> dict:
    r = Retriever()
    decision = rt.route(question)
    blocks = r.vector_search(question, k=k)          # always get block evidence
    subgraph = None

    if decision["strategy"] in ("graph", "browse"):
        # anchor on the best-matching entity and pull its relationships
        seed = (blocks[0]["text"].split("\n")[0] if blocks else question)
        ents = r.find_entities(question) or r.find_entities(seed)
        if ents:
            subgraph = r.subgraph(ents[0]["node_id"])

    context = ans.assemble_context(blocks, subgraph)
    result = {"question": question, "route": decision,
              "blocks": [b["block_id"] for b in blocks], "context": context}
    if use_llm:
        result["answer"] = ans.answer(question, context, backend, model)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask the EA GraphRAG wiki a question")
    ap.add_argument("question")
    ap.add_argument("--k", type=int, default=8, help="blocks to retrieve")
    ap.add_argument("--backend", default="cli", help="model backend (cli; pulse later)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--no-llm", dest="use_llm", action="store_false",
                    help="show routing + retrieved context only, no model call")
    args = ap.parse_args()

    out = ask(args.question, args.k, args.backend, args.model, args.use_llm)
    print(f"route : {out['route']['strategy']}  ({out['route']['reason']})")
    print(f"blocks: {out['blocks']}")
    if "answer" in out:
        print("\n" + out["answer"])
    else:
        print("\n--- retrieved context (no LLM) ---\n" + out["context"])


if __name__ == "__main__":
    main()
