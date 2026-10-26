"""Is each property ready to be answered? Checked before any run, without answering anything.

For every property of a phase it reports: is there guidance, which sources does its plan name, do
they exist (is a named document ingested, did the graph link the sample items to anything), and how
many of the sample items found any evidence. A property with nothing to read says so here, with the
reason, instead of producing a confident empty answer later. The plan and the gathering are the
same code the real run uses, so the check cannot say "ready" about a path the run does not take.
"""

from __future__ import annotations

from eawiki.cases import gather as gmod
from eawiki.cases import plan as pmod
from eawiki.cases import profile as profmod
from eawiki.cases import solve as smod
from eawiki.cases.engine import gate_column, phase_id, summary_columns

SAMPLE = 3


def property_report(col: dict, plan: dict, spec: dict, items: list[dict], tools: gmod.Tools, docs: list[str],
                    link_cache: dict, profiles: dict | None = None) -> dict:
    reasons, hits = [], []
    kinds = []
    for lk in plan.get("lookups") or []:
        for k in lk["in"]:
            ds = pmod.resolve_docs(k, docs)
            if not any(x["kind"] == k for x in kinds):
                kinds.append({"kind": k, "docs": ds})
    no_kind = [x["kind"] for x in kinds if not x["docs"]]
    if no_kind:
        reasons.append("no ingested document for: " + ", ".join(no_kind))
    named = plan.get("documents") or []
    missing_docs = [d for d in named if d.lower() not in {x.lower() for x in docs}]
    if missing_docs:
        reasons.append("not ingested: " + ", ".join(missing_docs))
    if not (col.get("description") or "").strip():
        reasons.append("no description")
    for it in items[:SAMPLE]:
        ev = gmod.gather(tools, plan, spec, it, [o for o in items if o is not it], link_cache, None,
                         (profiles or {}).get(it.get("_id")))
        found = len(ev["blocks"]) + (1 if ev["graph"] and ev["graph"]["facts"] else 0) + len(ev["others"])
        hits.append(found)
    needs_source = smod.needs_evidence(col)
    got = sum(1 for h in hits if h)
    if needs_source and hits and got == 0:
        reasons.append("no evidence found for any sample item")
    verdict = "ready"
    all_kinds_missing = bool(kinds) and len(no_kind) == len(kinds)
    if reasons:
        verdict = "not_ready" if (needs_source and (missing_docs or all_kinds_missing or (hits and got == 0))) else "partial"
    elif needs_source and hits and got < len(hits):
        verdict, reasons = "partial", [f"evidence found for {got} of {len(hits)} sample items"]
    return {"property": col["name"], "verdict": verdict, "reasons": reasons, "sources": plan["sources"],
            "documents": named, "queries": plan["queries"], "plan_origin": plan.get("origin"),
            "lookups": [{"find": lk["find"], "from": lk["from"], "match": lk["match"], "in": lk["in"], "docs": lk["docs"]}
                        for lk in plan.get("lookups") or []], "kinds": kinds,
            "evidence_required": needs_source, "evidence_found": f"{got} of {len(hits)}"}


def readiness(spec: dict, items: list[dict], tools: gmod.Tools, cache: dict | None = None) -> dict:
    docs = tools.doc_ids()
    fields = [f["name"] for f in (spec.get("input") or {}).get("item_fields") or []]
    link_cache: dict = {}
    profiles = {it.get("_id"): profmod.build_profile(gmod.labelled_fields(spec, it), tools.llm_json) for it in items[:SAMPLE]}
    phases = []
    for stage in spec["stages"]:
        out = []
        for col in stage["output"]["columns"]:
            if col["name"] == gate_column(spec) or col.get("type") == "citations" or col["name"] in summary_columns(stage):
                continue
            plan = pmod.build_plan(col, fields, docs, tools.llm_json, cache)
            out.append(property_report(col, plan, spec, items, tools, docs, link_cache, profiles))
        phases.append({"phase": phase_id(stage), "name": stage.get("name"), "properties": out})
    counts: dict = {}
    for ph in phases:
        for p in ph["properties"]:
            counts[p["verdict"]] = counts.get(p["verdict"], 0) + 1
    return {"documents": docs, "sample": min(SAMPLE, len(items)), "phases": phases, "counts": counts}
