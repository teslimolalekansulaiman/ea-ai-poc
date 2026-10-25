"""Step 3a (text half) — write each subject's wiki page + extract prose triples.

For each subject, ONE LLM pass over its TEXT blocks (the full-context bundle Step 2
gathered; figures are handled by figures.py) — with the subject's Step 1b table
facts injected — produces two things from one reading:
  1. the wiki PAGE  — a grounded markdown synthesis, citing block ids inline;
  2. the TRIPLES    — relationships it found, each with a source block id and a
     quoted span, validated against the metamodel source->target triples.

The page is the product; the graph is the byproduct. Backend is the pluggable
cli (`claude -p`) / sdk, same as the other steps.

Outputs:
  data/pages/<slug>.md       — the wiki page
  data/graph/facts_3a.json   — {nodes, edges} with evidence + block_id

    python -m eawiki.pages --menu data/togaf92_metamodel.json --backend cli [--only "Customer Portal"] [--limit N]
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from eawiki.blocks import Block, content_hash, load_blocks
from eawiki.subjects import llm_text, _extract_json, _norm, llm_json, effective_model
from eawiki.tables import _vocab, _validate_llm_facts, _SECURITY_RULE, _PREDICATE_RULE


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "subject"


def _subject_blocks(subject: dict, by_id: dict[str, Block]) -> str:
    """The subject's TEXT blocks (skip figures), id :: section :: text."""
    lines = []
    for bid in subject.get("block_ids", []):
        b = by_id.get(bid)
        if b is None or b.type == "figure":
            continue
        txt = (b.text or "").strip()
        if not txt:
            continue
        sect = " / ".join(b.section_path) or "(root)"
        lines.append(f"[{bid}] ({sect})\n{txt[:800]}")
    return "\n\n".join(lines) or "(no text blocks)"


def _injected_facts(name: str, facts_1b: dict) -> str:
    """The subject's already-known table facts, so the page weaves them in and
    the model doesn't have to re-derive them from the raw table markdown."""
    key = _norm(name)
    edges = [f"{e['source']} --{e['relation']}--> {e['target']}"
             for e in facts_1b.get("edges", [])
             if _norm(e["source"]) == key or _norm(e["target"]) == key]
    attrs = [f"{a['name']} = {a['value']}"
             for a in facts_1b.get("attributes", []) if _norm(a["subject"]) == key]
    out = []
    if edges:
        out.append("relationships: " + "; ".join(sorted(set(edges))))
    if attrs:
        out.append("attributes: " + "; ".join(sorted(set(attrs))))
    return "\n".join(out) or "(none from tables)"


def _page_prompt(subject: dict, by_id: dict[str, Block], facts_1b: dict, menu: dict) -> str:
    name, stype, kind = subject["name"], subject.get("type"), subject.get("kind")
    return f"""You are writing ONE page of an enterprise-architecture wiki, and extracting the relationships it states. Output ONE JSON object and nothing else.

Subject: "{name}"  (type: {stype}, kind: {kind})

{_vocab(menu)}

Already-known facts about this subject (from structured tables — treat as true; weave them into the page and include them as edges if a block supports them):
{_injected_facts(name, facts_1b)}

Source blocks for this subject (id :: section :: text) — the full context:
{_subject_blocks(subject, by_id)}

Return ONE JSON object:
{{
  "page_markdown": "<a full, readable wiki page about the subject: start with '# {name}', then a summary, what it is, how it relates to other things, and any context / rationale / risks the blocks support. Cite blocks inline like [03-data:5]. Plain markdown; escape newlines as \\n inside this JSON string.>",
  "edges": [{{"source": "<text>", "source_type": "<NODE TYPE>", "relation": "<EDGE TYPE>",
              "target": "<text>", "target_type": "<NODE TYPE>",
              "access_type": "<only for an accesses edge>",
              "evidence": "<quoted span from a block>", "block_id": "<the block it came from>"}}],
  "nodes": [{{"name": "<a NEW entity this page introduces, if any>", "type": "<NODE TYPE>",
              "evidence": "<quoted span>", "block_id": "<block>"}}]
}}

Rules:
- The PAGE is the product: write it fully and readably from the blocks; it is NOT limited to what the edges capture.
- Extract an edge ONLY when a block states or clearly implies it; put the quoted span in `evidence` and the citing block id in `block_id`. No quote -> no edge.
- Use ONLY the node/edge types above; respect each edge's allowed source->target. If a real link fits none, use `associated_with`.
- The subject is usually one endpoint of its edges; use the subject's own type for that endpoint.
- Do not invent facts not in the blocks; ignore scaffolding (Purpose/Overview headings).
{_SECURITY_RULE}
{_PREDICATE_RULE}"""


def _needs_model(subject: dict, by_id: dict[str, Block]) -> bool:
    """A subject earns a model-written page when there is prose to read about it. A subject
    that only appears as a catalogue-table row, with no paragraph or list item naming it and
    no section of its own, has nothing for the model to write from beyond the table facts
    that earlier steps already extracted — so it gets a deterministic page instead."""
    if subject.get("source") != "catalogue" or subject.get("kind") == "theme":
        return True
    name = _norm(subject["name"])
    for bid in subject.get("block_ids", []):
        b = by_id.get(bid)
        if b is None or b.type not in ("paragraph", "list_item", "caption"):
            continue
        if name and name in _norm(b.text):
            return True
        if any(_norm(h) == name for h in b.section_path):
            return True
    return False


def _stub_page(subject: dict, by_id: dict[str, Block], facts_1b: dict) -> dict:
    """A page built in code from what the tables state — no model, nothing invented. Same
    shape as a model page so everything downstream treats it alike (it adds no new edges:
    the table edges are already in facts_1b)."""
    name, key = subject["name"], _norm(subject["name"])
    edges = sorted({f"{e['source']} --{e['relation']}--> {e['target']}"
                    for e in facts_1b.get("edges", [])
                    if _norm(e["source"]) == key or _norm(e["target"]) == key})
    attrs = sorted({f"{a['name']}: {a['value']}" for a in facts_1b.get("attributes", [])
                    if _norm(a["subject"]) == key})
    tables = [bid for bid in subject.get("block_ids", [])
              if by_id.get(bid) is not None and by_id[bid].type == "table"][:3]
    where = ""
    if tables:
        sect = " / ".join(by_id[tables[0]].section_path) or by_id[tables[0]].doc_id
        where = f" in {sect} " + " ".join(f"[{t}]" for t in tables)
    lines = [f"# {name}", "", f"*{subject.get('type') or 'subject'}* — listed{where or ' in the source tables'}.",
             ""]
    if attrs:
        lines += ["## Attributes", ""] + [f"- {a}" for a in attrs] + [""]
    if edges:
        lines += ["## Relationships", ""] + [f"- {e}" for e in edges] + [""]
    if not attrs and not edges:
        lines += ["The sources list this item without further detail.", ""]
    return {"page_markdown": "\n".join(lines), "edges": [], "nodes": [], "_stub": True}


def _table_home(subject: dict, by_id: dict[str, Block]) -> Optional[str]:
    """The table block a table-only subject is listed in: the first of its table blocks whose
    text names it, else its first table block. None if it has no table block at all."""
    tables = sorted((by_id[b] for b in subject.get("block_ids", [])
                     if b in by_id and by_id[b].type == "table"),
                    key=lambda b: (b.doc_id, b.ordinal))
    if not tables:
        return None
    name = _norm(subject["name"])
    for b in tables:
        if name and name in _norm(b.text):
            return b.block_id
    return tables[0].block_id


def _item_section(subject: dict, home: str, facts_1b: dict) -> list[str]:
    """One item's part of a catalogue page, from the table facts only (no model)."""
    name, key = subject["name"], _norm(subject["name"])
    attrs = sorted({f"{a['name']}: {a['value']}" for a in facts_1b.get("attributes", [])
                    if _norm(a["subject"]) == key})
    rels = sorted({f"{e['source']} --{e['relation']}--> {e['target']}"
                   for e in facts_1b.get("edges", [])
                   if _norm(e["source"]) == key or _norm(e["target"]) == key})
    lines = [f"## {name}", "", f"*{subject.get('type') or 'subject'}* [{home}]", ""]
    lines += [f"- {a}" for a in attrs] + [f"- {r}" for r in rels]
    if not attrs and not rels:
        lines.append("- Listed without further detail.")
    return lines + [""]


def _catalogue_page(home: str, subs: list[dict], by_id: dict[str, Block],
                    facts_1b: dict) -> tuple[str, str]:
    """ONE page for a whole table: every item it lists, each with the attributes and
    relationships the table states. Built in code — no model, nothing invented."""
    b = by_id[home]
    slug = _slug(f"catalogue-{b.doc_id}-{b.ordinal}")
    where = b.section_path[-1] if b.section_path else b.doc_id
    lines = [f"# {where} — catalogue", "",
             f"{len(subs)} item{'s' if len(subs) != 1 else ''} listed in {b.doc_id}"
             + (f", section {' / '.join(b.section_path)}" if b.section_path else "")
             + f" [{home}].", ""]
    for sub in sorted(subs, key=lambda x: x["name"].lower()):
        lines += _item_section(sub, home, facts_1b)
    return slug, "\n".join(lines)


def _run_page(prompt: str, menu: dict, backend: str, model) -> dict:
    out = llm_json(prompt, backend, model)
    if not isinstance(out, dict):
        raise ValueError("page extractor did not return a JSON object")
    out.setdefault("page_markdown", "")
    out.setdefault("edges", [])
    out.setdefault("nodes", [])
    _validate_llm_facts(menu, out["nodes"], out["edges"])
    return out


def extract_page(subject: dict, by_id: dict[str, Block], facts_1b: dict,
                 menu: dict, backend: str, model) -> dict:
    return _run_page(_page_prompt(subject, by_id, facts_1b, menu), menu, backend, model)


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 3a (text) — wiki pages + prose triples")
    ap.add_argument("--in", dest="in_dir", default="data/blocks")
    ap.add_argument("--subjects", default="data/graph/subjects.json")
    ap.add_argument("--facts1b", default="data/graph/facts_1b.json")
    ap.add_argument("--menu", default="data/togaf92_metamodel.json")
    ap.add_argument("--pages", dest="pages_dir", default="data/pages")
    ap.add_argument("--out", dest="out", default="data/graph/facts_3a.json")
    ap.add_argument("--backend", default="cli", choices=["cli", "sdk", "openai", "openrouter", "pulse"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", default=None, help="run a single subject by name")
    ap.add_argument("--limit", type=int, default=0, help="cap number of subjects (0 = all)")
    ap.add_argument("--workers", type=int, default=6,
                    help="concurrent subjects (each is one claude -p call); 1 = sequential")
    ap.add_argument("--cache-dir", default="data/graph/pages_cache",
                    help="reuse a subject's page+triples when its prompt is unchanged")
    ap.add_argument("--no-cache", action="store_true", help="regenerate every page")
    ap.add_argument("--no-stubs", action="store_true",
                    help="write a model page for EVERY subject, including table-only ones")
    args = ap.parse_args()

    menu = json.loads(Path(args.menu).read_text(encoding="utf-8"))
    facts_1b = json.loads(Path(args.facts1b).read_text(encoding="utf-8"))
    subjects = json.loads(Path(args.subjects).read_text(encoding="utf-8"))

    by_id: dict[str, Block] = {}
    for fp in sorted(glob.glob(f"{args.in_dir}/*.blocks.json")):
        for b in load_blocks(Path(fp)):
            by_id[b.block_id] = b

    if args.only:
        subjects = [s for s in subjects if _norm(s["name"]) == _norm(args.only)]
    if args.limit:
        subjects = subjects[:args.limit]

    pages_dir = Path(args.pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache_dir)

    # Table-only subjects (no prose to read) do not get a page each: they are grouped by the
    # table that lists them and written as ONE catalogue page per table, in code. Everything
    # else goes to the model as before. A table-only subject with no table block of its own
    # (should not happen) falls through to the per-subject stub below.
    by_table: dict[str, list[dict]] = {}
    model_subjects: list[dict] = []
    for sub in subjects:
        home = None if args.no_stubs or _needs_model(sub, by_id) else _table_home(sub, by_id)
        if home:
            by_table.setdefault(home, []).append(sub)
        else:
            model_subjects.append(sub)
    redirects: dict[str, dict] = {}
    for home, subs in sorted(by_table.items()):
        slug, md = _catalogue_page(home, subs, by_id, facts_1b)
        (pages_dir / f"{slug}.md").write_text(md + "\n", encoding="utf-8")
        for sub in subs:
            redirects[_slug(sub["name"])] = {"page": slug, "name": sub["name"]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    (Path(args.out).parent / "page_redirects.json").write_text(
        json.dumps(redirects, indent=1, ensure_ascii=False), encoding="utf-8")
    subjects = model_subjects
    results: list[tuple[dict, dict]] = []  # (subject, out)
    written = 0
    cached = 0
    stubs = 0

    # Cache key = the fully rendered prompt + backend/model. It folds in the subject's
    # blocks, its table facts and the metamodel vocabulary, so the page is reused only
    # when none of those changed — a document add/remove regenerates just the subjects it
    # touched, and a metamodel edit (changing the vocabulary) regenerates all of them.
    def _do(s: dict) -> tuple[dict, dict, bool]:
        if not args.no_stubs and not _needs_model(s, by_id):
            return s, _stub_page(s, by_id, facts_1b), False
        prompt = _page_prompt(s, by_id, facts_1b, menu)
        key = content_hash(prompt, args.backend, effective_model(args.model))
        cf = cache_dir / f"{key}.json"
        if not args.no_cache and cf.exists():
            try:
                return s, json.loads(cf.read_text(encoding="utf-8")), True
            except Exception:
                pass
        out = _run_page(prompt, menu, args.backend, args.model)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cf.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return s, out, False

    # Each subject is an independent claude -p call -> run them concurrently.
    # Page files have distinct paths (write in worker); facts are collected and
    # written once, in the main thread, after all workers finish.
    workers = max(1, args.workers)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_do, s): s for s in subjects}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                _, out, hit = fut.result()
            except Exception as exc:
                print(f"  ! {s['name']}: failed ({type(exc).__name__}: {str(exc)[:90]}) — skipped")
                continue
            cached += 1 if hit else 0
            stubs += 1 if out.get("_stub") else 0
            page = out["page_markdown"].strip()
            if page:
                (pages_dir / f"{_slug(s['name'])}.md").write_text(page + "\n", encoding="utf-8")
                written += 1
            results.append((s, out))
            print(f"  {s['name']:32s} {'stub' if out.get("_stub") else 'cache' if hit else 'fresh'}  page={'yes' if page else 'no ':3}  "
                  f"edges={len(out['edges']):2d}  nodes+={len(out['nodes'])}")

    # Stable, review-friendly output: order facts by subject, not completion order.
    results.sort(key=lambda r: r[0]["name"].lower())
    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    for s, out in results:
        prov = {"subject": s["name"], "origin": "3a-text"}
        all_nodes += [{**n, **prov} for n in out["nodes"] if n.get("name")]
        all_edges += [{**e, **prov} for e in out["edges"] if e.get("source") and e.get("target")]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"nodes": all_nodes, "edges": all_edges}, indent=2, ensure_ascii=False), encoding="utf-8")
    generated = len(results) - cached - stubs
    n_items = sum(len(v) for v in by_table.values())
    print(f"\npages written: {written} -> {pages_dir}  (cache: {cached} reused, {generated} generated, "
          f"{stubs} single stubs); {len(by_table)} catalogue pages cover {n_items} table-only items")
    print(f"cache: reused {cached}   generated {generated}   catalogue pages {len(by_table)} "
          f"({n_items} items)")
    print(f"3a text facts: {len(all_nodes)} nodes, {len(all_edges)} edges -> {args.out}")


if __name__ == "__main__":
    main()
