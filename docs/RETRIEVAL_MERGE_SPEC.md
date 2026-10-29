# Retrieval merge — specification (draft for review, nothing built yet)

Status: draft, numbers agreed by the owner. **Steps 1 and 2 of section 10 are built** (step 2: `eawiki/lanes.py` and a `types` filter on the vector search, `Retriever.lane_search`). Step 1 (the tags): embedding units, the loaded vertex and the search results carry
`part`, `parts` and the row range; an index loaded before them reads as part 1 of 1. The rest is not built.

## 1. Purpose

A question or a property is answered from five kinds of evidence: tables, wiki pages, the graph, text passages and figures. Today
they are gathered in different places (the case runs in `cases/gather.py`, Ask in `query/graph.py`), are capped first come, first
served, and compete in one vector search. Short labels and captions outranked diagram descriptions; a long table's description
hid its later rows; a table could arrive as part 2 of 8 without saying so.

The merge is one Python module, called by both the case runs and Ask, that decides **what the answer step is shown, in what order,
and how complete each piece is.** It decides structure only. What the evidence means, and which source wins on a given property,
stays with the model and the owner's "combine the evidence" text.

## 2. Lanes

| # | Lane | Searched with | Returns | Citation id | Default results |
|---|---|---|---|---|---|
| 1 | **Tables** | text vector search, filtered to `btype = table` | table windows (parts) | the table's block id | 3 tables **(proposed)** |
| 2 | **Wiki** | page search by title and summary (`cases/pagefinder`), pages read for the question (`cases/wikiread`) | pages, summary and the sections that bear on the question | `wiki:<slug>` | 3 pages **(proposed)** |
| 3 | **Graph** | entities matched by name (`cases/namelookup`), facts for the relationships the lookup names (`cases/graphread`); in Ask, the graph query | facts | the block ids the edges came from | as today (10 facts per entity, 30 per property) |
| 4 | **Text** | text vector search, filtered to paragraphs and list items; label-only hits set aside, what follows a label read (`cases/passages`) | passages | block id | 5 passages **(proposed)** |
| 5 | **Figures** | text vector search over figure descriptions, filtered to `btype = figure`; a caption that is a hit brings its figure | descriptions, and the vision reading when enabled | block id | 3 figures **(proposed)** |

The order of the table is the **priority for room** (section 6). It is not the order of authority.

A lane that is not searched, fails, or finds nothing says so (section 7). No lane is ever silently absent.

## 3. Tags the index must carry

Every row of the index (the `Block` vertex) already has `block_id`, `doc_id`, `btype`, `section`, `text`. To be added and stored:

| Field | Meaning |
|---|---|
| `part` | the number of this unit within its block, from 1 |
| `parts` | how many units the block has (1 for most blocks) |
| `rows_from`, `rows_to`, `rows_total` | for a table window: the first and last row it holds, and the table's row count |

The embedding step already creates the units (`block#0 … block#n`) and records `chunk` and `n_chunks`; these become `part` and
`parts`, and the row range is added. Rows loaded before the change are read as `part = 1, parts = 1`. A re-embed and a re-load of the
index are needed; nothing changes before then.

## 4. The merge, step by step

Input: the results of every lane (each already limited to its default number, with its score), the question, the property's
settings, and the budget. Output: an ordered list of labelled sections and the set of ids the answer may cite. Pure: no model, no
search; those are passed in.

1. **Collect.** Each lane's results, with its lane name, score and tags.
2. **Group table parts** by `block_id`.
3. **Complete tables** (section 5).
4. **Remove duplicates.** The key is `(block_id, part)`, not `block_id`: parts 2 and 3 of one table are both kept. The same block
   found by two lanes (a table by the table lane and by the graph's cited blocks) is shown once, in the highest-priority lane, and
   keeps the note of every lane that found it.
5. **Apply the budget** (section 6).
6. **Order and label** the sections (section 7).
7. **Build the citation set**: the ids of everything shown, and nothing else.

## 5. Completing a table

A table found as one part of several must not reach the model as if it were the whole.

- **Small table** — at most **4 parts** and about **4,000 characters** in all **(proposed)**: all missing parts are added, in order. The
  section says so ("all 3 parts shown").
- **Large table** — more parts than that: add the parts **next to each part found** (one before, one after), keep within the table's
  share of the budget, and let the table view (`cases/tableview`) keep the rows that match the question. The section says what is
  missing: "parts 4 to 6 of 8 shown; rows 61 to 120 of 160".
- **Whole table wanted.** Whether a question needs the whole table cannot be read from its wording without a word list for every
  language, which the project forbids. It is an owner's setting on the property or the lookup: **`whole_tables: true`** (default off).
  With it on, a table is completed whatever its size, up to the table budget, and says so if the budget stopped it.
- Each part already carries the header row, so a part read alone is still a table.

## 6. Budget, and what gives way first

| Item | Default **(proposed)** |
|---|---|
| Results per lane | as in section 2 |
| Tables, in all | 6,000 characters |
| Text | 5 passages, 1,100 characters each (a run read after a label, 1,800) |
| Figures | 3, 2,500 characters each |
| Wiki | 3 pages, 2,500 characters each |
| Whole evidence | 20,000 characters |

When the whole budget is exceeded, the **lowest-priority lane gives up first** (text, then graph, then wiki, then tables), and
within a lane the lowest-scoring result goes first. A table already begun is never cut in the middle of a part. Whatever was dropped
is named in the section's completeness line ("2 text passages not shown").

**Priority for room**, by lane: 1 tables, 2 wiki, 3 graph, 4 text, with figures taking their 3 results before text. Figures sit with
tables because both carry the facts a label search misses.

## 7. What the model is shown

Sections in the priority order, each with a heading that says the lane, and a line that says how complete it is. The question goes
last.

```
TABLES (3 searched; 2 shown)
  [D:36] parts 2 and 3 of 4 shown; rows 21 to 60 of 120 …
WIKI PAGES (3 searched; 3 shown) …
GRAPH FACTS (2 entities; 7 facts shown) …
TEXT (5 searched; 4 shown; 2 labels set aside) …
FIGURES (none found)
```

Completeness lines are one of: *N shown*; *none found*; *could not be searched (error)*; *not searched for this question*; *partial:
what is missing*. The model is told that "none found" means looked and found nothing, and "could not be searched" means nothing can be
concluded.

**Authority is not in the merge.** When a wiki page and a table row disagree, which wins is the property's own "combine the
evidence" text. The merge only makes the kind of each piece visible (a wiki page is written by a model from the documents; a table is a
document).

## 8. Where it lives and what it replaces

- New module `src/eawiki/retrieval/merge.py`: the lane results in, the sections out. The lane limits and the budget are constants at
  its top, and the use case may override them per property.
- `cases/gather.py` calls it in place of the first-come caps (`MAX_BLOCKS`, `MAX_WIKI`) and in place of its own section building.
- `query/graph.py` calls it in `n_retrieve` and `n_relevance` in place of its own context assembly.
- The vector search (`query/retrieve.py`) gains a `btype` filter and returns the tags of section 3.
- "Passages the model was given" on the result screen shows each piece's lane and part ("table, part 2 of 4").
- A use-case flag `merge: true` switches a use case onto it, default **off** until it has been measured.

## 9. Tests and acceptance

Unit tests with fake lanes (no model, no index):
- a small table found as part 2 of 3 arrives complete; a large one arrives with its neighbours and the missing parts named;
- parts 2 and 3 of one table are both kept; the same block from two lanes appears once;
- over budget: text goes before graph before wiki before tables, and the sections say what was dropped;
- an empty lane, a failed lane and a lane not searched each say so in their own words;
- the order and the headings are as in section 7; the citation set is exactly what is shown;
- `whole_tables: true` completes a large table to its budget and reports when the budget stopped it.

End to end:
- the nine-question harness (`tests/e2e_extraction_retrieval.py`), extended with a question per lane;
- **with the real embeddings and the real index**, which cannot be run in the development container. The owner runs the same
  questions before and after switching `merge` on, and compares what the answer step was shown.

## 10. Order of work

1. Add `part`, `parts`, `rows_*` to the embedding units and the index; re-embed and re-load.
2. The `btype` filter and the returned tags in the vector search.
3. The merge module and its unit tests.
4. Wire the case runs behind `merge: true`; compare on the sample sheet.
5. Wire Ask behind the same flag.
6. The result screen shows lane and part.
7. Measure with real embeddings; tune the numbers; make it the default.

## 11. Decisions for the owner

1. The numbers marked **(proposed)**: results per lane, the small-table limit (4 parts, about 4,000 characters), the lane budgets, the
   20,000-character total.
2. `whole_tables` as a property setting: yes or no, and which properties would turn it on.
3. Whether Ask and the case runs use the same budgets.
4. Whether figures keep their own lane or share the text lane's budget.
5. Whether the wiki lane runs for every question or only when the question names no entity the graph can match (it costs model calls).

## 12. Risks

- A real embedding model may rank table windows differently from the test stand-in; the windows may need a different size (a 256-token
  model reads about 700 characters).
- More lanes mean more searches per question: slower, and more text for the model to read. The budget is what limits the second.
- Tags need a re-load of the index; a half-loaded index mixes old rows (`parts = 1`) and new ones, which the merge reads correctly but
  which complete no table until the re-load finishes.
- The lane filter runs after an over-fetch, because the index cannot filter inside the search. A very rare type could be missed; if it
  is, the index is split by type, which is a change to the load step and not to the merge.
