#!/usr/bin/env python3
"""Generate the prose-extraction system prompt from a metamodel schema.

Single source of truth is a metamodel JSON (default: data/togaf92_metamodel.json;
pass another path as argv[1]). Re-run after editing the schema so the prompt's
vocabulary stays in sync.

    python3 -I scripts/build_extraction_prompt.py [schema.json] [out.md]

Writes prompts/extraction_system_prompt.md by default.
"""
import json, pathlib, datetime, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "togaf92_metamodel.json"
OUT = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "prompts" / "extraction_system_prompt.md"

# --- few-shot examples: how your source columns/prose map onto TOGAF entities.
# These replace the old menu.json `synonyms` layer. Add to this list as you see
# recurring phrasings the model gets wrong.
FEWSHOT = [
    ('"Owning Department: Finance Operations" on an application row',
     'Finance Operations -> node `organization_unit`. '
     'Edge: logical_application_component --is_owned_by--> organization_unit.'),
    ('"Vendor: Oracle" on an application row',
     'Oracle -> node `actor` (external supplier; attribute role=supplier). '
     'Edge: logical_application_component --provides_consumes--> ... or supplier served via `supports`; '
     'if only "supplied by", use actor with `supports` toward the component.'),
    ('"Stored In: Customer DB (Oracle)" for the data entity Customer',
     'Customer -> `data_entity`; Customer DB -> `physical_data_component`. '
     'Edge: data_entity --resides_within--> physical_data_component.'),
    ('"System of record: Billing App" for the data entity Invoice',
     'Invoice -> `data_entity`; Billing App -> `logical_application_component`. '
     'Edge: logical_application_component --accesses--> data_entity with access_type="read-write".'),
    ('"Server: web-prod-01" that runs the Payments application',
     'web-prod-01 -> `physical_technology_component`; Payments -> `logical_application_component`. '
     'Edge: logical_application_component --is_deployed_on--> physical_technology_component.'),
    ('"Location: Riyadh DC" for a server',
     'Riyadh DC -> `location`. Edge: physical_technology_component --resides_at--> location.'),
    ('"Control: MFA enforced on all production systems; Framework: NCA ECC"',
     'MFA enforced -> `requirement` (a security control = something the architecture must satisfy); '
     'NCA ECC -> `standard`. Edge: standard --applies_to--> requirement (or --applies_to--> the governed component). '
     'NOTE: security is cross-cutting in TOGAF; do NOT invent a security node type.'),
    ('"The Settlement service feeds transaction files to the Reporting system nightly"',
     'Settlement, Reporting -> `logical_application_component` each. '
     'Edge: logical_application_component --communicates_with--> logical_application_component (source=Settlement).'),
    ('"Fee Collection is a supporting process for the Revenue Management capability"',
     'Fee Collection -> `process`; Revenue Management -> `business_capability`. '
     'Edge: business_service/process --supports--> business_capability. '
     'Alternatively business_capability --is_realized_by--> process.'),
    ('A relationship that is clearly real but fits no TOGAF edge type',
     'Use edge `associated_with` (the generic fallback) and keep the evidence quote; do not invent a type.'),
]

OUTPUT_CONTRACT = '''{
  "nodes": [
    {
      "mention": "<verbatim name as written in the text>",
      "type": "<one node_types key, e.g. logical_application_component>",
      "domain": "<the type's domain, for a sanity check>",
      "attributes": { "<attr>": "<value>" },
      "evidence": "<short quote from the block that justifies this node>"
    }
  ],
  "edges": [
    {
      "source": "<mention of the source node>",
      "target": "<mention of the target node>",
      "type": "<one edge_types key, e.g. is_deployed_on>",
      "access_type": "read | write | read-write | access (ONLY when type == accesses)",
      "evidence": "<short quote that justifies this relationship>"
    }
  ]
}'''


def node_vocab(items):
    groups = {}
    for key, v in items.items():
        g = v.get("domain") or v.get("layer") or v.get("aspect") or "other"
        groups.setdefault(g, []).append((key, v))
    lines = []
    for g, rows in groups.items():
        lines.append(f"\n**{g}**")
        for key, v in rows:
            anchor = v.get("archimate_type")
            tag = f" [ArchiMate: {anchor}]" if anchor else ""
            lines.append(f"- `{key}` ({v['name']}){tag}: {v['definition']}")
    return "\n".join(lines)


def edge_vocab(items):
    lines = []
    for key, v in items.items():
        st = " | ".join(v.get("source_types", ["*"]))
        tt = " | ".join(v.get("target_types", ["*"]))
        acc = ""
        if v.get("access_types"):
            acc = f"  (access_type: {' | '.join(v['access_types'])})"
        lines.append(f"- `{key}` ({v['name']}): {v['definition']}\n"
                      f"    valid: ({st}) --{key}--> ({tt}){acc}")
    return "\n".join(lines)


def main():
    schema = json.loads(SCHEMA.read_text())
    nodes, edges = schema["node_types"], schema["edge_types"]

    fewshot = "\n".join(f"{i+1}. **Text:** {t}\n   **Extract:** {e}"
                        for i, (t, e) in enumerate(FEWSHOT))

    framework = schema.get("framework", "TOGAF 9.2 Content Metamodel")
    prompt = f"""<!-- GENERATED by scripts/build_extraction_prompt.py from {SCHEMA.name} on {datetime.date.today()}. Do not hand-edit; edit the schema or the generator and re-run. -->
# Prose extraction — system prompt (TOGAF 9.2 metamodel)

You extract an enterprise-architecture graph from a block of source text. You
classify every concept and relationship into the **TOGAF content-metamodel**
vocabulary below ({framework}). This vocabulary is closed: you MUST use one of
these keys and never invent a new type.

## Your task
Given one block of text (a table row, paragraph, or list item), return the
nodes (TOGAF entities) and edges (TOGAF relationships) it states or clearly
implies. Extract only what the text supports; do not infer architecture that is
not there.

## Node types ({len(nodes)} total)
{node_vocab(nodes)}

## Edge types ({len(edges)} total) — each shows its valid (source) --edge--> (target)
{edge_vocab(edges)}

## Rules
1. **Pick exactly one `type` key per node and per edge** from the lists above.
2. **Respect each edge's valid source->target types.** If a link does not fit any
   edge's allowed types, use `associated_with` (the generic fallback).
3. **If a concept is real but matches no entity type**, use `element` (the generic
   node fallback) rather than force a wrong type. Never invent a new type.
4. **Security is cross-cutting — there is NO security node type.** A security
   control is a `requirement` (or `constraint`); a compliance framework/standard
   (ISO 27001, NCA ECC, SAMA) is a `standard` (or `driver` if regulatory pressure).
5. **Logical vs physical:** a described *class* of component is logical; a named
   installed product/instance is physical (e.g. "Oracle 19c on srv-db-01" ->
   physical_technology_component; "relational database platform" -> logical).
6. **Direction matters.** Emit edges in the direction shown above, even when the
   prose reads the other way.
7. **`accesses` edges carry `access_type`** (read | write | read-write | access).
8. **Every node and edge needs an `evidence` quote** copied from the block.
9. **`domain` on a node must match the chosen type's domain** (self-check).
10. Output **only** the JSON object below — no prose, no markdown fences.

## Mapping examples (source phrasing -> standard type)
{fewshot}

## Output format
Return exactly this JSON shape:

{OUTPUT_CONTRACT}

If the block contains no extractable architecture, return
`{{"nodes": [], "edges": []}}`.
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(prompt)
    toks = len(prompt) // 4
    print(f"Wrote {OUT.relative_to(ROOT)}  (~{toks} tokens, {len(prompt)} chars)")


if __name__ == "__main__":
    main()
