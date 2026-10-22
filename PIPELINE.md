# GraphRAG Wiki for Enterprise Architecture Docs — Build Pipeline

Locked design. We build step by step. No step starts before its predecessor (see
**Hard orderings** at the bottom).

## Build status (updated 2026-10-21)
Schema is now **TOGAF 9.2** (`data/togaf92_metamodel.json`), not `menu.json`. All LLM calls
run through the pluggable **`claude -p` CLI backend** (no SDK/key needed); the Step 1b keyword
fallback has been **removed** — the LLM is the path.

- ✅ **Step 1 — Parse** (+ figure image export to `data/images/`)
- ✅ **Step 1b — Tables** (LLM-only; hybrid = deterministic apply + full-read; triple-validated)
- ✅ **Step 2 — Subjects** (section-based grouping, figure attachment, coverage report)
- ✅ **Step 3a (vision half)** — graph facts from figure images (`figures.py` → `facts_figures.json`)
- ✅ **Step 3a (text half)** — 53 pages + prose triples (`pages.py` → `facts_3a.json`); schema widened (`is_owned_by`, `is_supplied_by`) cut `associated_with` 45%→35%
- ✅ **Step 4 — Reconcile** (`reconcile.py` + `dedupe.py` → `graph.json`): hybrid node resolution (deterministic Tiers 1–2 + optional Tier-3 LLM on flagged pairs), edge dedupe with cross-source corroboration, isolated-node + merge reports
- ✅ **Step 5 — Embed** (`embed.py` → `embeddings.jsonl` + `_meta.json`): block-level, context-enriched, **pluggable embedder** (st / vertex / hash), configurable by flag or env
- ✅ **Step 6 — Load (ArcadeDB)** — `store.py` + `load.py` project `graph.json` + `embeddings.jsonl` into ArcadeDB (Entity/REL + Block with an LSM_VECTOR index + CITES provenance links); verified live (vector search + graph traversal)
- ✅ **Steps 7–9 — Community / landscape layer** (`community.py` Louvain + domain tag → 17 communities; `summaries.py` grounded summaries; `landscape.py` → 9 landscape pages; projected to ArcadeDB `Community`/`IN_COMMUNITY`)
- ⬜ **Step 3c — Recall** (optional, can fold in later) · ⬜ Wire **Pulse** (OpenAI-compatible: base_url swap) to replace `claude -p` + hash placeholders
- ⚡ All three LLM steps (`pages`/`figures`/`tables`) now take `--workers N` (default 6) for concurrent `claude -p` calls.

## Governing principle
The **wiki is the main product.** Each page is a full LLM reading/synthesis of the source
blocks — summary, explanation, rationale, thematic arrangement — exactly like a normal LLM
wiki. The **graph is a thin structured layer extracted *alongside* the page, from the same
reading** — it is *not* the source of the page and does *not* limit what the page can say.
The graph exists only to answer the questions prose can't answer reliably (dependencies,
impact, coverage, visualization) and to power the community layer.

The graph is extracted from **source blocks, not generated prose**. The page and its
grounded relationships are produced **together** in one pass (Step 3a), each relationship
carrying its source-block id and a quoted span. This gives provenance and anti-hallucination
without a heavy entity-resolution stage, and is why the ordering is safe.

### Wiki vs graph — what each holds
- **Wiki (the product):** summaries, explanations, design rationale, context, risks,
  thematic narrative — the full content of the documents, grounded with citations. This is
  the superset of content and carries far more than the graph.
- **Graph (an extracted index):** only the structured relationships (`A depends_on B`,
  `owned_by team`, …), used for traversal/coverage/visualization queries and community
  detection. It is an add-on, not a cage.

---

## Build-time pipeline

### Step 1 — Parse into structural blocks  ✅
Layout-aware parsing. Keep tables and diagrams as their own blocks (do **not** flatten to
text). Every block keeps a provenance pointer back to its source doc + location, and a
stable block id. Each block is also stamped with a **document `kind`** (`architecture` |
`motivation` | `governance` | `reference`) — set by `--kind` or a kind-named subfolder
(`docs/governance/*.docx`), defaulting to `architecture`. The kind is **carried through the
whole pipeline** (block → fact → node/edge → store → query) so architecture *facts* stay
separable from *motivation*/*governance* material and queries can scope to one class (e.g.
answer from `architecture` only, so a governance *principle* is never returned as a *fact*).
This is how non-architecture docs (EA Framework, strategy) can be ingested for Q&A without
polluting the entity graph. **Figure images are exported to files** (`parse.py --images` →
`data/images/*.png`, path stored on the figure block) so the Step 3a vision pass can read
them — the only genuine re-ingest needed (for pixels; sectioning never requires one).

### Step 1b — Table interpretation (LLM structure + hybrid apply)  ✅
Real documents contain *any* kind of table, so we do **not** hardcode which column is
the subject. Per table, two phases:
- **Interpret (one decision per table):** classify it — `catalogue | matrix | key_value |
  process | other` (each kind is **defined in the prompt**) — and, for a catalogue, decide
  which column is the subject and what each other column means, mapping everything onto the
  schema (`data/togaf92_metamodel.json`; edge vs attribute, typed). The **LLM** does this via
  the `claude -p` CLI backend — **there is no keyword fallback** (removed; the LLM is the
  path). The result is a small JSON **plan**, **cached** by header shape and written to
  `table_plans.json` for **human review**.
- **Apply (hybrid):** a clean catalogue/matrix is executed **deterministically** across every
  row (code copies cells, exact `block_id + row + column`, no LLM on values); a **complex or
  low-confidence** table is escalated to a **full LLM read** of the whole table. Either way,
  every emitted edge is **validated against the schema's `source → target` triples** (invalid
  ones demote to `associated_with`). `--mode {deterministic|hybrid|llm}` controls routing.

This scales to unseen tables while keeping exact provenance and low cost (one structural call
per table, not per row). Runs early because its output seeds Step 2 and is injected into
Step 3a. Diagrams are handled by the 3a vision pass (now built — see Step 3a).
→ must finish before Step 2 and Step 3a.

### Step 2 — Subject discovery  ✅
Build the list of subjects (the pages that will exist), seeded by the Step 1b catalogue
(every card = a subject); the LLM only finds the extra prose-mentioned ones. **Group blocks
by subject in code**, and beyond name/heading mentions do **section-based expansion**: once a
subject is mentioned anywhere in a leaf section, pull in that whole section — so pronoun-only
paragraphs and captionless figures travel with it (this covers the coreference gap of literal
name-matching). **Orphan figures are attached** to the subjects in their section so no diagram
is lost, and a **coverage report** (`data/graph/coverage.json`) lists any block no subject
claimed (headings are expected orphans; anything else is flagged for review). Subjects are
**not only graph entities** — a subject can be a **theme/topic** (e.g. "Integration Strategy")
that reads across many docs, so the wiki can summarize and arrange content freely.
→ must follow 1b; must precede 3a.

### Step 3a — Single-pass subject extraction (main path)
Two halves:
- **Text half (⬜ TODO — the main path):** for each subject, one LLM call over its grouped
  blocks — with 1b facts injected and already-built pages in view — produces **two things from
  one reading**: (1) the **wiki page**, a full synthesis of the blocks (summary, explanation,
  rationale, arrangement), and (2) the **grounded relationship triples** extracted alongside
  (each with a source-block id and a quoted span). **The page is the product; the graph is the
  byproduct** — the page is not limited to what the graph captures. Identity resolves by
  construction. Prompt: `prompts/extraction_system_prompt.md` (generated from the schema).
- **Vision half (✅ DONE — `figures.py` → `data/graph/facts_figures.json`):** for each figure
  with an exported image, a vision LLM reads the **diagram + its context** and emits
  schema-valid `{nodes, edges}` — triple-validated, each with an evidence note, via the same
  `claude -p` backend. An edge is emitted only when a real arrow/line is visible (no inventing
  connections from layout). Diagram nodes typically **confirm** entities already found in
  tables/prose (merge in Step 4) and surface a few diagram-only ones.
→ must follow 2.

### Step 3c — Targeted recall pass
Scoped to the gaps 3a left: only the subjects/edge types 3a didn't cover, only the
completeness-critical edges (`depends_on`, `sends_data_to`, reads/writes on sensitive
data), each requiring a quote. Insures recall without re-scanning everything.
→ must follow 3a.

### Step 4 — Reconcile into the clean graph  ✅
Merge nodes/edges from **1b + 3a (text) + the figure vision facts** (and 3c, when run) into
one deduplicated graph. Built as `reconcile.py` (orchestrator) + `dedupe.py` (node identity),
on the agreed **hybrid** design — deterministic tiers shrink the problem to a certain core plus
a tiny uncertain remainder; the LLM resolves only that remainder:

- **Tier 1 (deterministic, ~90%):** group by `normalize(name) + type` → one node, auto-merged.
  Provenance (origins, block_ids, evidence) is merged into the node.
- **Tier 2a/2b (deterministic):** same-type candidates by token-Dice **and** by **edge-overlap**
  (shared `(relation, neighbour)` sets). High name-similarity **and** a shared neighbour →
  auto-merge; everything else → **flag** for Tier 3. 2b catches semantic aliases that don't
  string-match (e.g. `K8S-PROD` vs `Kubernetes Production`) via shared neighbours.
- **Tier 2c (deterministic):** identical name but **conflicting type** across passes → **flag**
  (never auto-merge — the type choice is a real modelling decision). This surfaces the main
  real-world duplication: the passes disagree on an entity's type (e.g. `SMS Gateway` typed as
  application vs technology component), which the type-gate would otherwise split silently.
- **Tier 3 (optional LLM, `--adjudicate cli`):** one scoped `claude -p` call per flagged pair,
  given each node's type/evidence/edges, decides merge vs separate. The reasoning is a reviewable
  prompt asset (`dedupe.adjudication_prompt`).

**Type is always the gate**, so same-name/different-*type* nodes (the `SMS Gateway` app vs the
`Replace SMS Gateway` work_package) never falsely merge. **Edges** are then rewritten onto
resolved node ids, deduped by `(source_id, relation, target_id[, access_type])` with provenance
merged (`source_count` = cross-source corroboration — a table + a diagram asserting the same
edge), and **re-validated** against the schema triples. **Edgeless nodes are KEPT** (a node is a
page and a real entity; "no edges" is a valid coverage answer) and listed in
`isolated_nodes.json`; every auto-merge and flagged pair is written to `merge_report.json` for
audit. Outputs: `graph.json`, `isolated_nodes.json`, `merge_report.json`.
→ must follow 3a (3c optional).

### Step 5 — Embed blocks → vector index  ✅
Built as `embed.py` → `data/graph/embeddings.jsonl` (one unit per line) + `embeddings_meta.json`.
Embed the **small blocks** directly (split only oversized ones) — small units give sharper
matching and more precise citations than a coarse section would, so the small block is the
index unit (not the assembled block). Implemented:
- **Enrich before embedding (contextual retrieval):** each block's text is prefixed with a
  `doc > section / path` header (`enrich()`), so a lone paragraph is self-explaining. Heading
  blocks are skipped as standalone units — their text already travels via every block's
  `section_path`.
- **Chunk only oversized blocks** (`chunk_text()`, default 1200 chars + 150 overlap); short
  blocks (the vast majority) pass through whole. Chunks keep the block id, suffixed `#0/#1`.
- **Pluggable embedder backend** (`Embedder` protocol). **Production uses the Pulse API** (the
  platform used for *all* models, LLM + embeddings); a `pulse` backend is added as one `Embedder`
  class + one line in `get_embedder` once its endpoint/auth/model-ids are known. `st`
  (sentence-transformers) and `hash` ship only as local-dev fallbacks. **Configurable by flag or
  env** (`EAWIKI_EMBED_BACKEND` / `EAWIKI_EMBED_MODEL` / `EAWIKI_EMBED_DIM`). Vectors are
  **L2-normalized** (cosine == dot). The model's **`dim` is written to the meta file** so Step 6
  sizes the vector index to match — swapping models is config, not a schema change.
- **Expand at query time (small → big):** each unit keeps `block_id / doc_id / section_path /
  ordinal`, so retrieval pulls neighbours/section around a matched block. (Query-time, not here.)
- **Incremental-friendly:** JSONL + `--only-doc <doc_id>` lets one doc be re-embedded/appended
  without rebuilding the rest (ties into the per-`doc_id` incremental-ingestion plan).

NOTE: the embeddings currently on disk are **hash placeholders** (plumbing proof); regenerate
with the real GCP backend once wired. Runs in parallel with everything above, any time after
Step 1.

### Step 6 — Load the store (as a projection)  ✅
Files (pages + blocks) are the system of record. Load the graph + vectors into the store
from them, so it stays droppable/rebuildable. Behind a backend interface (`store.py`;
ArcadeDB default, Neo4j optional). `load.py` reads `graph.json` + `embeddings.jsonl` +
`embeddings_meta.json` and projects them (re-runnable; `--reset` drops & rebuilds):
- **`Entity`** vertices (one per resolved node) + **`REL`** edges (relation on `REL.relation`,
  with `source_count`/`origins`/`evidence`). Generic types on purpose — the metamodel evolves,
  the DB schema shouldn't.
- **`Block`** vertices carry each embedding; a **`LSM_VECTOR`** index on `Block.embedding` is
  sized from the meta `dim`/`similarity` (so swapping the GCP embedder needs no code change).
- **`CITES`** edges link `Entity -> Block` (a vector hit jumps to the entity/page it evidences).
- Connection is env-configurable (`EAWIKI_ARCADE_URL/DB/USER/PASSWORD`) — local and the GCP VM
  differ only by environment. Store runs via `docker-compose.yml` (see `docker/README-arcadedb.md`).

Working query patterns on this ArcadeDB build (HTTP API): vertex-centric traversal
(`SELECT out('REL').name FROM Entity WHERE node_id=…`, `out('CITES').block_id`, `in('REL')`)
and vector search (`SELECT expand(vector.neighbors('Block[embedding]', :vec, :k))`). The
edge-wise `SELECT … in.name FROM REL WHERE out.node_id=…` form does not deref linked-vertex
props here; use `MATCH` or vertex traversal at query time (Step A–C).

**Where the community layer lives.** Same two-tier rule as everything else:
- **System of record = files.** Community membership + each community summary are written as
  files alongside the pages (`data/graph/communities.json` for membership, and the Step 9
  landscape pages as normal wiki pages with citations). Rebuildable by re-running 7–9.
- **Query projection = the store.** Loaded into ArcadeDB as **community nodes** with
  `in_community` membership edges over the subject nodes, so a global question can traverse
  "give me everything in the Payments community" in one hop, and the summary text sits on the
  community node. Dropping and reloading the DB loses nothing — it all re-projects from files.

### Steps 7–9 — Community layer (a thin add-on, NOT the foundation)
**This is where we deliberately diverge from classic (Microsoft) GraphRAG.** There, the
graph is clustered, each community is LLM-summarized, and **those summaries become the
knowledge** — answers are map-reduced over summaries and the source documents disappear
behind the graph. **We do the opposite.** The wiki pages (Step 3a) are the product and are
written directly from source blocks; the community layer below is a *thin add-on* that exists
only to answer the **global / cross-cutting** question type (e.g. "summarize the whole
payments landscape", "coverage across the BDAT domains") that no single subject page can
answer. A local or per-subject question never touches it — it reads the subject page + graph.

#### Step 7 — Community detection  ✅ (`community.py`)
Group the resolved graph. Grouping is driven **primarily by intrinsic structure** —
ArchiMate layers, catalogue sections, and TOGAF BDAT domains — because the EA material is
already organized that way. **Leiden clustering is only a refinement / sanity-check** on top
of that structure, never the primary grouping. Output: community nodes + membership edges
over the Step 4 graph.
→ must follow 4.

#### Step 8 — Community summaries  ✅ (`summaries.py`)
LLM-summarize each community into a short narrative. These summaries serve **global
questions only**; they do **not** feed or constrain the Step 3a subject pages. Each summary
is still **grounded — it cites the member subjects and their source blocks**, so it never
floats free of the documents the way classic GraphRAG summaries do.
→ must follow 7.

#### Step 9 — Overview/landscape wiki pages  ✅ (`landscape.py` → `data/pages/landscape-*.md`)
Narrative synthesis pages for whole areas, generated from community summaries + member
nodes + linked blocks, **cited to source blocks** the same way entity pages are. These power
the UI's Landscape/Map and Coverage sections.
→ must follow 8.

---

## Query-time  🟡 (scaffold built — `src/eawiki/query/`)
Implemented as a small explicit Python package (no agent framework — the flow is a
DAG; LangGraph only if it becomes an agent). Model calls route through the same
pluggable backends, so **Pulse** slots into one place. See `src/eawiki/query/README.md`.

- **A. Route** (`route.py`) the question: vector (local/pointed) · graph traversal
  (dependencies/coverage) · community summary (global) · wiki page (browsable). Rule-based
  now; LLM router later.
- **B. Assemble** (`retrieve.py` + `answer.assemble_context`) the scoped context (blocks, a
  subgraph, or a summary + its blocks); small→big: `expand()` a retrieved block to its
  neighbours. Verified live: vector search + typed graph traversal (`MATCH` over ArcadeDB).
- **C. Answer** (`answer.py`) with the LLM, citing source blocks. Entry point: `ask.py`
  (`python -m eawiki.query.ask "..."`).

NOTE: retrieval *plumbing* works today; retrieval *quality* is real only once the Pulse
embedder replaces the hash placeholders (re-run `embed` + `load`).

---

## Hard orderings (everything else can parallelize)
```
1 → 1b → 2 → 3a → 3c → 4 → 7 → 8 → 9
      (5 Embed blocks — runs in parallel, any time after 1)
```

## EA schema
The authoritative schema (all node kinds and edge types, with exact implemented names) lives
in **`data/togaf92_metamodel.json`** — the **TOGAF 9.2** content metamodel (38 node types, 25
edge types), each with a definition and an ArchiMate export anchor, and each edge carrying its
allowed `source_types`/`target_types` triples (the Step 1b/4 validator). Names used in this
doc are illustrative; the schema governs and uses lowercase TOGAF names (e.g.
`logical_application_component`, `organization_unit`, `is_owned_by`, `is_deployed_on`,
`accesses`). **Security is cross-cutting** (no security domain): a security control →
`requirement`, a framework → `standard`.

**Schema-coverage tuning (2026-10-21):** a first full 3a run showed ~45% of prose edges
demoting to the generic `associated_with` — not model laziness, but the LLM correctly avoiding
triples the schema didn't allow. Two edits closed the biggest gaps: **`is_owned_by` widened**
to accept `process` and `physical_application_component` / `physical_technology_component` as
sources (the docs state ownership of physical apps and processes, not just logical ones), and a
new **`is_supplied_by`** edge (`application|technology component → actor`, ArchiMate anchor
*Serving*) to capture vendor/host links (e.g. "Customer Portal … Oracle"). Gap→app transition
links and weak cross-domain links are left as honest `associated_with`. When the schema changes,
the prompts are **regenerated** (`scripts/build_extraction_prompt.py`) and 3a is re-run. The earlier `menu.json` and
`data/archimate32_schema.json` are **superseded**. The extraction/interpret prompts are
generated from this schema (`scripts/build_extraction_prompt.py`). Official TOGAF/ArchiMate
specs sit behind an Open Group login; this metamodel was reconstructed from open references
(cross-check against the official figures if membership is available).
