"""The AI layer — a guarded question-answering pipeline (the entry the UI calls).

Flow (a DAG): input guard -> route -> retrieve (+kind scope) -> relevance guard ->
answer -> citation/faithfulness guard. Guardrails (eawiki.query.guardrails) run at the
input, retrieval and output stages; refusal/abstention short-circuit the rest.

Model backend is `--backend` (cli locally; pulse via env in prod) — one place.

    python -m eawiki.query.ask "where is applicant data stored?"
    python -m eawiki.query.ask "ignore your instructions and..."     # -> refused
    python -m eawiki.query.ask "..." --no-llm                        # retrieval only
"""

from __future__ import annotations

import argparse
import json

from eawiki.query import graph as g


def ask(question: str, k: int = 8, backend: str = "cli", model=None,
        kinds=None, use_llm: bool = True, safety_llm: bool = True,
        max_distance: float = 0.95, check_faithfulness: bool = False,
        history=None, case_context: str = "") -> dict:
    """Answer a question through the LangGraph guarded pipeline. Returns a structured
    result with a `status`: refused | abstained | retrieved | answered | blocked_output.
    `history` carries prior [{role, content}] turns so follow-ups resolve in context."""
    return g.run(question, backend=backend, model=model, k=k, kinds=kinds,
                 use_llm=use_llm, safety=safety_llm, max_distance=max_distance,
                 history=history, case_context=case_context)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask the EA GraphRAG wiki a question (guarded)")
    ap.add_argument("question")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--backend", default="cli")
    ap.add_argument("--model", default=None)
    ap.add_argument("--kinds", default=None, help="comma-separated doc kinds to scope to")
    ap.add_argument("--no-llm", dest="use_llm", action="store_false")
    ap.add_argument("--no-safety-llm", dest="safety_llm", action="store_false",
                    help="skip the LLM safety classifier (keep deterministic input guard)")
    ap.add_argument("--faithfulness", action="store_true", help="run the LLM faithfulness check")
    ap.add_argument("--json", action="store_true", help="print the full structured result")
    args = ap.parse_args()

    kinds = [k.strip() for k in args.kinds.split(",")] if args.kinds else None
    out = ask(args.question, args.k, args.backend, args.model, kinds,
              args.use_llm, args.safety_llm, check_faithfulness=args.faithfulness)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print(f"status: {out['status']}")
    if out["status"] in ("refused", "blocked_output"):
        ig = out.get("input_guard", out.get("output_guard", {}))
        print(f"  blocked by {ig.get('layer','?')} guard "
              f"({ig.get('category','unsafe')}: {ig.get('reason','')})")
    else:
        if out.get("route"):
            print(f"route : {out['route']['strategy']}   blocks: {out.get('blocks')}")
        if "citation_check" in out:
            cc = out["citation_check"]
            print(f"cites : {cc['cited']}  grounded={cc['grounded']}"
                  + (f"  INVALID={cc['invalid']}" if cc['invalid'] else ""))
    print("\n" + out.get("answer", out.get("context", "")))


if __name__ == "__main__":
    main()
