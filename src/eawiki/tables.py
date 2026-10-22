"""Step 1b — Table interpretation (LLM structure + hybrid apply).

Real documents contain *any* kind of table, so we never hardcode which column is
the subject. Instead, per table:

  1. INTERPRET (one decision per table) — the LLM classifies the table
     (catalogue | matrix | key_value | process | other) and, for a catalogue,
     decides which column is the subject and what each other column means,
     mapping everything onto the --menu schema. The LLM is the path (no keyword
     fallback); it runs through a pluggable backend (`cli` = `claude -p`, `sdk` =
     Anthropic SDK). The result is a small JSON "plan", CACHED by header shape so
     identical tables cost nothing to re-run and the mapping is reviewable.
  2. APPLY — clean catalogue/matrix tables are executed DETERMINISTICALLY across
     every row (code copies cells; no LLM touches values; exact block_id + row +
     column provenance). Complex / low-confidence tables are escalated to a full
     LLM read, whose emitted edges are validated against the schema's
     source->target triples. (--mode controls routing.)

Diagrams (figure blocks) are still handled later by the 3a vision pass.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from eawiki.blocks import Block, content_hash, load_blocks
from eawiki.subjects import llm_text, _extract_json, llm_json  # shared pluggable LLM backend

# Default model for the interpreter. Override with --model (cli uses the
# session default when None). Vocabulary comes entirely from the --menu schema.
DEFAULT_MODEL: Optional[str] = None
DEFAULT_BACKEND = "cli"

# Values that mean "no real target" — kept as an attribute, never as an edge,
# so coverage questions ("capabilities with no owner") still see the signal.
NULLISH = {"", "-", "n/a", "na", "none", "unassigned", "no owner",
           "no owner assigned", "no integration", "not assigned",
           "in-house", "in house"}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _is_nullish(v: str) -> bool:
    return v.strip().lower() in NULLISH or not v.strip()


def _split(value: str, multi: bool) -> list[str]:
    if multi:
        return [p.strip() for p in value.split(";") if p.strip()]
    return [value.strip()] if value.strip() else []


def load_menu(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _grid(block: Block) -> list[list[str]]:
    return (block.table or {}).get("cells") or []


# ---------------------------------------------------------------------------
# INTERPRET — produce a plan for one table
#
# plan schema:
#   { "table_kind": "catalogue"|"matrix"|"key_value"|"process"|"other",
#     "source": "llm"|"fallback"|"cache",
#     # catalogue:
#     "subject_column": 0, "subject_type": "application",
#     "columns": [ {"index":1,"header":"Owner","role":"edge",
#                   "relation":"owned_by","target_type":"department","multi":false},
#                  {"index":3,"header":"Status","role":"attribute","name":"status"} ],
#     # matrix:
#     "row_entity_type": "...","col_entity_type":"...","cell_relation":"depends_on",
#     "notes": "" }
# ---------------------------------------------------------------------------
def _vocab(menu: dict) -> str:
    # include each node type's DEFINITION so the LLM can disambiguate look-alikes
    # (e.g. TOGAF `control` = a process decision step, NOT a security control).
    nodes = "\n".join(
        f"  - {k}: {v.get('definition') or v.get('label') or ''}"
        for k, v in menu["node_types"].items())
    edges = "\n".join(
        f"  - {r}: {'/'.join(spec['source_types'])} -> {'/'.join(spec['target_types'])}"
        for r, spec in menu["edge_types"].items())
    return f"NODE TYPES (key: meaning):\n{nodes}\n\nEDGE TYPES (relation: allowed source -> target):\n{edges}"


# Cross-cutting rule surfaced in every table prompt (TOGAF has no security domain).
_SECURITY_RULE = ("- Security is CROSS-CUTTING: a security control / safeguard is `requirement` "
                  "(NOT `control`, which is a process decision step); a compliance framework or "
                  "standard (ISO 27001, NCA ECC, SAMA) is `standard`.")


def build_plan_llm(block: Block, menu: dict, backend: str, model: Optional[str]) -> dict:
    """Ask the LLM (via the pluggable cli/sdk backend) to classify the table and
    map its columns onto the schema. No keyword fallback — the LLM is the path."""
    grid = _grid(block)
    header = grid[0]
    sample = grid[1:6]
    preview = "HEADER: " + " | ".join(header) + "\nROWS:\n" + "\n".join(
        " | ".join(r) for r in sample)

    prompt = f"""You interpret the STRUCTURE of a table from an enterprise-architecture document. You never read or transcribe cell values as facts — you only decide what the table's shape means and map it onto the given schema. Output ONE JSON object and nothing else.

{_vocab(menu)}

Table to interpret:
{preview}

TABLE KINDS (pick exactly one):
- catalogue: an inventory where EACH ROW is one entity; one column (usually the first) NAMES the row's subject, and the other columns describe it (attribute) or point to a related entity (edge). Column headers are attribute/relationship NAMES (e.g. "Owner", "Vendor", "Status"). Emits subjects + edges + attributes.
- matrix: a cross-tab where the COLUMN HEADERS are themselves entity instances (e.g. application names across the top) and the ROW LABELS are entities; each filled cell marks a relationship between the row entity and the column entity. Emits edges.
- key_value: a two-column property sheet about ONE thing (Field | Value); there is no per-row subject. No subjects.
- process: an ORDERED sequence of steps/activities (e.g. Step | Action). No subjects.
- other: anything else (freeform notes, legends, glossaries). No subjects.
Decisive test — catalogue vs matrix: are the column headers NAMES OF PROPERTIES (catalogue) or NAMES OF ENTITIES (matrix)?

Classify the table and return a JSON plan with this schema:
{{
  "table_kind": "catalogue" | "matrix" | "key_value" | "process" | "other",
  "subject_column": <int, catalogue only: the column index whose cell names each row's subject>,
  "subject_type": "<catalogue only: one NODE TYPE above>",
  "columns": [   // catalogue only, one entry per NON-subject column
    {{"index": <int>, "header": "<text>", "role": "edge",
      "relation": "<one EDGE TYPE>", "target_type": "<one NODE TYPE>", "multi": <bool, true if cell holds ';'-separated values>}},
    {{"index": <int>, "header": "<text>", "role": "attribute", "name": "<snake_case>"}}
  ],
  "row_entity_type": "<matrix only: NODE TYPE of the row labels>",
  "col_entity_type": "<matrix only: NODE TYPE of the column headers>",
  "cell_relation": "<matrix only: EDGE TYPE a filled cell represents>",
  "notes": "<short reason if unsure>"
}}

Rules:
- A column names another real entity (owner, vendor, server) -> role "edge" with a relation+target_type from the schema.
- A column that only describes the subject (status, classification) -> role "attribute".
- Use ONLY node/edge types listed above. If nothing fits, pick the closest and say so in notes.
{_SECURITY_RULE}
- key_value / process / other tables have no subjects: return just table_kind and notes."""

    plan = llm_json(prompt, backend, model)
    if not isinstance(plan, dict):
        raise ValueError("interpreter did not return a JSON object")
    plan["source"] = f"llm-{backend}"
    plan.setdefault("notes", "")
    return plan


def _plan_key(block: Block) -> str:
    """Cache key = the table's header shape (same header -> same plan)."""
    header = [c.strip().lower() for c in _grid(block)[0]]
    return content_hash("|".join(header), str(len(header)))


def get_plan(block: Block, menu: dict, backend: str, model: Optional[str], cache_dir: Path) -> dict:
    """LLM interpreter, cached by header shape. No keyword fallback: on failure
    the exception propagates and the caller skips the table."""
    key = _plan_key(block)
    cache_file = cache_dir / f"{key}.json"
    if cache_file.exists():
        p = json.loads(cache_file.read_text(encoding="utf-8"))
        p["source"] = "cache"
        return p
    plan = build_plan_llm(block, menu, backend, model)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return plan


# ---------------------------------------------------------------------------
# APPLY — execute a plan across the table (deterministic, provenance-exact)
# ---------------------------------------------------------------------------
def apply_plan(block: Block, plan: dict) -> tuple[list[dict], list[dict], list[dict]]:
    grid = _grid(block)
    subjects: list[dict] = []
    edges: list[dict] = []
    attributes: list[dict] = []
    if len(grid) < 2:
        return subjects, edges, attributes
    header = [c.strip() for c in grid[0]]
    kind = plan.get("table_kind")

    if kind == "catalogue":
        sc = plan.get("subject_column", 0)
        subj_type = plan.get("subject_type", "entity")
        for r, row in enumerate(grid[1:], start=1):
            if sc >= len(row) or not row[sc].strip():
                continue
            subject = row[sc].strip()
            subjects.append({"name": subject, "type": subj_type,
                             "block_id": block.block_id, "doc_id": block.doc_id,
                             "section_path": block.section_path, "row": r})
            for col in plan.get("columns", []):
                c = col["index"]
                if c >= len(row):
                    continue
                value = row[c].strip()
                prov = {"block_id": block.block_id, "doc_id": block.doc_id,
                        "row": r, "column": col.get("header", header[c] if c < len(header) else str(c))}
                if col.get("role") == "attribute" or _is_nullish(value):
                    name = col.get("name") or col.get("relation") or col.get("header", "").lower()
                    attributes.append({"subject": subject, "name": name, "value": value, **prov})
                    continue
                for target in _split(value, col.get("multi", False)):
                    edges.append({"source": subject, "source_type": subj_type,
                                  "relation": col["relation"],
                                  "target": target, "target_type": col["target_type"], **prov})

    elif kind == "matrix":
        rt, ct = plan.get("row_entity_type", "entity"), plan.get("col_entity_type", "entity")
        rel = plan.get("cell_relation", "related_to")
        col_entities = [c.strip() for c in header[1:]]
        for ce in col_entities:
            subjects.append({"name": ce, "type": ct, "block_id": block.block_id,
                             "doc_id": block.doc_id, "section_path": block.section_path, "row": 0})
        for r, row in enumerate(grid[1:], start=1):
            if not row or not row[0].strip():
                continue
            rlabel = row[0].strip()
            subjects.append({"name": rlabel, "type": rt, "block_id": block.block_id,
                             "doc_id": block.doc_id, "section_path": block.section_path, "row": r})
            for c, ce in enumerate(col_entities, start=1):
                if c >= len(row):
                    continue
                value = row[c].strip()
                if _is_nullish(value):
                    continue
                edges.append({"source": rlabel, "source_type": rt, "relation": rel,
                              "target": ce, "target_type": ct, "value": value,
                              "block_id": block.block_id, "doc_id": block.doc_id, "row": r, "column": ce})

    # key_value / process / other -> no subjects extracted here (left to 3a prose)
    return subjects, edges, attributes


# ---------------------------------------------------------------------------
# HYBRID — route clean tables to the deterministic apply, complex/low-confidence
# ones to a full LLM read. The deterministic apply assumes cell == one clean
# value; it cannot handle compound/qualified cells, ragged rows, or matrices
# whose cells carry values rather than marks. For those an LLM reads the whole
# table and emits entities/relationships, which are then validated against the
# schema's source->target triples (same confirmation the deterministic path
# relies on). Only catalogue/matrix tables are considered; others are left to 3a.
# ---------------------------------------------------------------------------
_CONJUNCTION = re.compile(r"\b(and|or|plus|via|through)\b", re.IGNORECASE)
_MARKS = {"x", "✓", "✔", "yes", "y", "•", "*", "1", "true", "n", "no", "0", "false"}


def table_complexity(block: Block, plan: dict) -> tuple[bool, str]:
    """Deterministic signals that the apply step would mishandle this table.
    Returns (is_complex, reason). Pure grid inspection — no LLM, no cost."""
    kind = plan.get("table_kind")
    if kind not in ("catalogue", "matrix"):
        return False, ""
    rows = _grid(block)[1:]
    reasons: list[str] = []

    if len({len(r) for r in rows}) > 1:
        reasons.append("ragged rows")

    if kind == "catalogue":
        sc = plan.get("subject_column", 0)
        # which non-subject columns are edges (a clean ';' split is NOT complex)
        filled = compound = 0
        for r in rows:
            for c, cell in enumerate(r):
                if c == sc:
                    continue
                v = cell.strip()
                if not v or _is_nullish(v):
                    continue
                filled += 1
                # breakers the deterministic splitter can't do: parentheticals,
                # multi-line, conjunctions, comma-joined lists (apply splits ';' only)
                if ("\n" in v) or ("(" in v) or _CONJUNCTION.search(v) or ("," in v):
                    compound += 1
        if compound >= 2 and filled and compound / filled >= 0.25:
            reasons.append(f"{compound}/{filled} compound/qualified cells")

    if kind == "matrix":
        vals = [c.strip().lower() for r in rows for c in r[1:]
                if c.strip() and not _is_nullish(c)]
        if any(v not in _MARKS for v in vals):
            reasons.append("matrix cells carry values, not just marks")

    note = (plan.get("notes") or "").lower()
    if any(w in note for w in ("unsure", "closest", "not sure", "ambiguous")):
        reasons.append("low-confidence plan")

    return bool(reasons), "; ".join(reasons)


def _allowed_triple(menu: dict, source_type: str, relation: str, target_type: str) -> bool:
    spec = menu["edge_types"].get(relation)
    if not spec:
        return False
    st, tt = spec.get("source_types", ["*"]), spec.get("target_types", ["*"])
    return (("*" in st) or source_type in st) and (("*" in tt) or target_type in tt)


def _validate_llm_facts(menu: dict, subjects: list[dict], edges: list[dict]) -> None:
    """In-place: snap unknown node types to the `element` fallback and demote
    edges that violate the schema triples to `associated_with`, flagging both."""
    node_types = set(menu["node_types"])
    for s in subjects:
        if s.get("type") not in node_types:
            s["note"] = f"unknown type '{s.get('type')}' -> element"
            s["type"] = "element"
    for e in edges:
        st, tt, rel = e.get("source_type"), e.get("target_type"), e.get("relation")
        if st not in node_types:
            e["source_type"] = "element"
        if tt not in node_types:
            e["target_type"] = "element"
        if not _allowed_triple(menu, e["source_type"], rel, e["target_type"]):
            e["note"] = f"demoted from '{rel}' (not a valid {st}->{tt} triple)"
            e["relation"] = "associated_with"
            e["validation"] = "demoted"
        else:
            e["validation"] = "ok"


def extract_table_llm(block: Block, menu: dict, backend: str, model: Optional[str], cache_dir: Path) -> dict:
    """Full LLM read of one table -> schema-valid subjects/edges/attributes with
    cell-text evidence. Cached by FULL-GRID content (not header shape, since the
    values matter here). Edges are validated against the schema triples."""
    grid = _grid(block)
    key = content_hash(json.dumps(grid, ensure_ascii=False), "fullread")
    cache_file = cache_dir / f"fullread_{key}.json"
    if cache_file.exists():
        out = json.loads(cache_file.read_text(encoding="utf-8"))
        out["source"] = "llm-fullread-cache"
        return out

    preview = "HEADER: " + " | ".join(grid[0]) + "\nROWS:\n" + "\n".join(
        f"[row {i}] " + " | ".join(r) for i, r in enumerate(grid[1:81], start=1))
    prompt = f"""You extract an enterprise-architecture graph from ONE table. Use ONLY the node and edge types given. Never invent a type. Emit an edge only when a cell names a SEPARATE entity (not a mere property of the row). Quote the exact cell text you used as `evidence`. Output ONE JSON object and nothing else.

{_vocab(menu)}

Table:
{preview}

Return ONE JSON object:
{{
  "subjects": [{{"name": "<text>", "type": "<NODE TYPE>", "row": <int>, "evidence": "<cell text>"}}],
  "edges": [{{"source": "<text>", "source_type": "<NODE TYPE>", "relation": "<EDGE TYPE>",
              "target": "<text>", "target_type": "<NODE TYPE>",
              "access_type": "<only for an access/reads-writes edge>",
              "row": <int>, "evidence": "<cell text>"}}],
  "attributes": [{{"subject": "<text>", "name": "<snake_case>", "value": "<text>", "row": <int>, "evidence": "<cell text>"}}]
}}

Rules:
- A column/cell that names another real entity (owner, vendor, server, framework) -> an edge whose relation+types come from the schema above.
- A cell that only describes the subject (status, classification) -> an attribute, not an edge.
- Split compound cells ("A and B", "A, B", "A (primary), B (DR)") into multiple edges; capture qualifiers in evidence.
- Respect each edge's allowed source->target types. If a real link fits none, use `associated_with`.
- Use the subject's node type for `source_type`; never invent names not present in the cells.
{_SECURITY_RULE}"""

    out = llm_json(prompt, backend, model)
    if not isinstance(out, dict):
        raise ValueError("full-read did not return a JSON object")
    out.setdefault("subjects", [])
    out.setdefault("edges", [])
    out.setdefault("attributes", [])
    _validate_llm_facts(menu, out["subjects"], out["edges"])
    out["source"] = "llm-fullread"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def facts_from_llm(block: Block, out: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Attach provenance to LLM-extracted facts, matching apply_plan's shape."""
    prov = lambda row: {"block_id": block.block_id, "doc_id": block.doc_id,
                        "row": row, "column": "(llm-fullread)"}
    subjects = [{"name": s["name"], "type": s["type"], "section_path": block.section_path,
                 **prov(s.get("row", 0)), **({"note": s["note"]} if s.get("note") else {})}
                for s in out["subjects"] if s.get("name")]
    edges = [{"source": e["source"], "source_type": e["source_type"], "relation": e["relation"],
              "target": e["target"], "target_type": e["target_type"],
              **({"access_type": e["access_type"]} if e.get("access_type") else {}),
              "evidence": e.get("evidence", ""), "validation": e.get("validation", "ok"),
              **({"note": e["note"]} if e.get("note") else {}), **prov(e.get("row", 0))}
             for e in out["edges"] if e.get("source") and e.get("target")]
    attrs = [{"subject": a["subject"], "name": a.get("name", ""), "value": a.get("value", ""),
              **prov(a.get("row", 0))} for a in out["attributes"] if a.get("subject")]
    return subjects, edges, attrs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Step 1b — table interpretation (LLM structure + hybrid apply)")
    ap.add_argument("--in", dest="in_dir", default="data/blocks")
    ap.add_argument("--out", dest="out", default="data/graph/facts_1b.json")
    ap.add_argument("--plans", dest="plans", default="data/graph/table_plans.json")
    ap.add_argument("--menu", dest="menu", default="menu.json")
    ap.add_argument("--cache", dest="cache", default="data/graph/plan_cache")
    ap.add_argument("--backend", dest="backend", choices=["cli", "sdk", "openai", "openrouter", "pulse"], default=DEFAULT_BACKEND,
                    help="LLM backend: cli = `claude -p` (default, no SDK/key needed); sdk = Anthropic SDK")
    ap.add_argument("--mode", dest="mode", choices=["deterministic", "hybrid", "llm"],
                    default="hybrid",
                    help="deterministic = LLM plan + apply; llm = always full-read; "
                         "hybrid (default) = apply clean tables, full-read complex/low-confidence ones")
    ap.add_argument("--model", dest="model", default=DEFAULT_MODEL)
    ap.add_argument("--workers", type=int, default=6,
                    help="concurrent tables (each is one+ claude -p call); 1 = sequential")
    args = ap.parse_args()

    menu = load_menu(Path(args.menu))

    all_subjects: list[dict] = []
    all_edges: list[dict] = []
    all_attrs: list[dict] = []
    plans_log: list[dict] = []
    src_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}

    cache_dir = Path(args.cache)

    # Gather every table block first (each is independent), then process the set
    # concurrently — one worker per table. Distinct block_ids => distinct cache
    # files, so concurrent get_plan/extract writes don't collide.
    tables: list[Block] = []
    for fp in sorted(glob.glob(f"{args.in_dir}/*.blocks.json")):
        for b in load_blocks(Path(fp)):
            if b.type == "table" and len(_grid(b)) >= 2:
                tables.append(b)

    def _process_table(b: Block) -> dict:
        """All the per-table work; returns a structured result (never raises)."""
        try:
            plan = get_plan(b, menu, args.backend, args.model, cache_dir)
        except Exception as ex:  # no keyword fallback -> skip this table, keep going
            return {"block": b, "interpret_error": ex}
        complex_, reason = table_complexity(b, plan)
        want_llm = args.mode == "llm" or (args.mode == "hybrid" and complex_)
        route, route_reason = "deterministic", reason
        if want_llm and plan.get("table_kind") in ("catalogue", "matrix"):
            try:
                llm_out = extract_table_llm(b, menu, args.backend, args.model, cache_dir)
                s, e, a = facts_from_llm(b, llm_out)
                route = "llm-fullread"
            except Exception as ex:  # full-read failed -> fall back to deterministic apply
                s, e, a = apply_plan(b, plan)
                route, route_reason = "deterministic", f"full-read failed ({type(ex).__name__}); {reason}"
        else:
            s, e, a = apply_plan(b, plan)
        return {"block": b, "plan": plan, "route": route, "route_reason": route_reason,
                "s": s, "e": e, "a": a}

    # Run the pool, then aggregate in stable (input) order so outputs are diffable.
    workers = max(1, args.workers)
    by_id: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_process_table, tables):
            by_id[res["block"].block_id] = res

    for b in tables:
        res = by_id[b.block_id]
        if "interpret_error" in res:
            ex = res["interpret_error"]
            print(f"  ! interpret failed for {b.block_id} ({type(ex).__name__}: {str(ex)[:120]}) — skipped")
            plans_log.append({"block_id": b.block_id, "doc_id": b.doc_id,
                              "header": [c.strip() for c in _grid(b)[0]],
                              "route": "skipped", "route_reason": f"interpret failed: {type(ex).__name__}",
                              "plan": {"table_kind": "error", "source": f"llm-{args.backend}-error"}})
            route_counts["skipped"] = route_counts.get("skipped", 0) + 1
            continue
        plan = res["plan"]
        src_counts[plan["source"]] = src_counts.get(plan["source"], 0) + 1
        route_counts[res["route"]] = route_counts.get(res["route"], 0) + 1
        all_subjects += res["s"]
        all_edges += res["e"]
        all_attrs += res["a"]
        plans_log.append({"block_id": b.block_id, "doc_id": b.doc_id,
                          "header": [c.strip() for c in _grid(b)[0]],
                          "route": res["route"], "route_reason": res["route_reason"], "plan": plan})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"subjects": all_subjects, "edges": all_edges, "attributes": all_attrs},
        indent=2, ensure_ascii=False), encoding="utf-8")
    Path(args.plans).write_text(json.dumps(plans_log, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"tables: {len(plans_log)}   plan source: {src_counts}   routes: {route_counts}")
    print(f"subjects: {len(all_subjects)}   edges: {len(all_edges)}   attributes: {len(all_attrs)}")
    print(f"-> {out}\n-> {args.plans}  (reviewable interpretation plans + routes)")


if __name__ == "__main__":
    main()
