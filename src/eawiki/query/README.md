# Query layer (`eawiki.query`)

The **serving side** — ask a question, get a grounded answer. Separate from the build
pipeline (`parse → … → load`). The build side writes files + the ArcadeDB projection;
this side reads them to answer.

## Why not LangGraph (yet)
The flow is a **DAG** — `route → retrieve → assemble → answer` — no loops, no agent
state. Plain Python keeps it debuggable, dependency-light, and portable to the GCP VM,
and it matches the rest of the codebase. LangGraph earns its place only if this becomes
a genuine **agent** (iterative retrieval, self-correction, tool loops); at that point
these same functions get wrapped — nothing here is thrown away.

## Modules (capabilities)
| file | role |
|---|---|
| `retrieve.py` | `Retriever`: vector search + graph traversal over ArcadeDB; `expand()` = small→big |
| `route.py` | `route(question)` → `vector` / `graph` / `global` / `browse` (rule-based; LLM later) |
| `answer.py` | `assemble_context()` + `answer()` — grounded answer with `[block]` citations |
| `ask.py` | one entry point / CLI tying it together |

## Model backend (Pulse)
Every model call goes through one place:
- **query embedding** → `embed.get_embedder()` (same backend/model/dim as the index, read
  from `embeddings_meta.json` — a query must use the index's embedder);
- **answer generation** → `subjects.llm_text(prompt, backend, model)`.

So pointing the query layer at **Pulse** = add the `pulse` backend in those two spots
(same change the build side needs). `--backend` selects it per call.

## Use cases → skills (later)
Each use case becomes a **skill** whose instructions call these functions:
- *Q&A with citations* → `ask()`
- *Impact analysis* → `Retriever.subgraph()` over a seed entity
- *Coverage* → graph + `isolated_nodes.json`
- *Landscape summary* → the community layer (Steps 7–9)

The query package stays the **capabilities**; skills are the **packaged use-case entry
points**. Plain functions make that wrapping trivial.

## Run
```bash
export EAWIKI_ARCADE_PASSWORD=...        # same as docker .env
python -m eawiki.query.ask "where is applicant data stored?"
python -m eawiki.query.ask "what depends on the Payment Gateway?" --no-llm   # retrieval only
```

> Current vectors are **hash placeholders** — retrieval quality is only real once the
> Pulse embedder is wired and `embed` + `load` are re-run. The plumbing (routing,
> traversal, assembly, citations) works today.
