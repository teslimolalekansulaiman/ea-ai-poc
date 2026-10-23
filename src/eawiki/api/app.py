"""FastAPI service for the EA GraphRAG wiki.

Feeds the 5-view UI (ask / wiki / landscape / coverage / kb) and serves the static
frontend from the SAME app — so the whole thing is one Cloud Run service (a React
build or a single-file UI both drop into `web/`). Pages come from files (the system of
record); ask / graph / kb use the query layer over ArcadeDB.

    uvicorn eawiki.api.app:app --reload          # dev
    uvicorn eawiki.api.app:app --host 0.0.0.0 --port 8080   # Cloud Run
"""

from __future__ import annotations

import glob
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PAGES = Path(os.environ.get("EAWIKI_PAGES", "data/pages"))
GRAPH = Path(os.environ.get("EAWIKI_GRAPH", "data/graph"))
# Prefer the built React app (ui/dist); fall back to the single-file UI (web/).
_web_env = os.environ.get("EAWIKI_WEB")
WEB = Path(_web_env) if _web_env else (Path("ui/dist") if Path("ui/dist").exists() else Path("web"))
API_BACKEND = os.environ.get("EAWIKI_API_BACKEND", "openrouter")

app = FastAPI(title="EA GraphRAG Wiki API", version="1.0")

# OpenTelemetry/OpenInference tracing -> Phoenix (no-op if Phoenix/libs absent).
try:
    from eawiki import obs
    obs.init_tracing()
except Exception:
    pass


# --- helpers -------------------------------------------------------------
def _title(md: str, fallback: str) -> str:
    for line in md.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


@lru_cache(maxsize=1)
def _retriever():
    from eawiki.query.retrieve import Retriever
    return Retriever()


def _load_json(name: str, default):
    p = GRAPH / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _menu_node_types() -> dict:
    mpath = Path(os.environ.get("EAWIKI_MENU", "data/togaf92_metamodel.json"))
    return json.loads(mpath.read_text(encoding="utf-8")).get("node_types", {}) if mpath.exists() else {}


def _subgraph_view(node_id: str):
    """A render-ready 1-hop neighbourhood of `node_id` (same {nodes,edges} shape as
    /api/map) so a graph-routed answer can show the slice of the graph it used. Built
    from graph.json (the source of truth), not the live traversal — the centre node is
    flagged member:1, its neighbours member:0 (drawn as context)."""
    g = _load_json("graph.json", {"nodes": [], "edges": []})
    by_id = {n["node_id"]: n for n in g["nodes"]}
    if node_id not in by_id:
        return None
    menu = _menu_node_types()
    touch = [e for e in g["edges"]
             if (e.get("source") == node_id or e.get("target") == node_id)
             and e.get("source") != e.get("target")]
    ids = {node_id}
    for e in touch:
        ids.update((e["source"], e["target"]))
    nodes = [{"id": nid, "name": by_id[nid].get("name", nid),
              "type": by_id[nid].get("type", "element"),
              "domain": (menu.get(by_id[nid].get("type", ""), {}) or {}).get("domain", "Other"),
              "member": 1 if nid == node_id else 0}
             for nid in ids if nid in by_id]
    edges = [{"source": e["source"], "target": e["target"],
              "relation": e.get("relation", "associated_with")} for e in touch]
    return {"nodes": nodes, "edges": edges, "center": node_id} if len(nodes) > 1 else None


# --- models --------------------------------------------------------------
class AskReq(BaseModel):
    question: str
    k: int = 8
    kinds: Optional[list[str]] = None
    safety: bool = True
    history: Optional[list[dict]] = None   # prior [{role, content}] turns for follow-ups


# --- endpoints -----------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "backend": API_BACKEND,
            "pages": len(list(PAGES.glob("*.md"))) if PAGES.exists() else 0}


@app.post("/api/ask")
def ask(req: AskReq):
    """The guarded AI layer: route -> retrieve -> answer, with NeMo + deterministic guards."""
    from eawiki.query.ask import ask as run
    out = run(req.question, k=req.k, backend=API_BACKEND, kinds=req.kinds,
              use_llm=True, safety_llm=req.safety, history=req.history)
    # One graph for display, from a single source. A structured graph-query result
    # already carries render-ready nodes/edges; otherwise fall back to the 1-hop slice.
    gr = out.get("graph_result")
    if gr and gr.get("nodes"):
        out["graph"] = {"nodes": gr["nodes"], "edges": gr["edges"],
                        "center": (gr.get("centers") or [None])[0],
                        "template": gr.get("template"), "summary": gr.get("summary")}
    else:
        sg = out.get("subgraph") or {}
        if sg.get("node_id"):
            gv = _subgraph_view(sg["node_id"])
            if gv:
                out["graph"] = gv
    return {k: v for k, v in out.items() if k != "context"}


@app.get("/api/pages")
def pages():
    """Subject wiki pages (the 'wiki' view)."""
    out = []
    for fp in sorted(PAGES.glob("*.md")):
        if fp.name.startswith("landscape-"):
            continue
        out.append({"slug": fp.stem, "title": _title(_read(fp), fp.stem)})
    return {"pages": out}


@app.get("/api/pages/{slug}")
def page(slug: str):
    fp = PAGES / f"{slug}.md"
    if not fp.exists():
        raise HTTPException(404, f"no page '{slug}'")
    md = _read(fp)
    return {"slug": slug, "title": _title(md, slug), "markdown": md}


@app.get("/api/landscape")
def landscape():
    """Communities + their landscape pages (the 'landscape' view)."""
    comms = _load_json("communities.json", {"communities": []}).get("communities", [])
    out = []
    for c in comms:
        has_page = (PAGES / f"landscape-{c['slug']}.md").exists()
        out.append({"slug": c["slug"], "name": c["name"], "size": c["size"],
                    "domain": c.get("dominant_domain"), "summary": c.get("summary", ""),
                    "has_page": has_page, "members": c.get("member_names", [])})
    return {"communities": out}


@app.get("/api/landscape/{slug}")
def landscape_page(slug: str):
    fp = PAGES / f"landscape-{slug}.md"
    if not fp.exists():
        raise HTTPException(404, f"no landscape page '{slug}'")
    md = _read(fp)
    return {"slug": slug, "title": _title(md, slug), "markdown": md}


@app.get("/api/coverage")
def coverage():
    """Graph coverage stats (the 'coverage' view)."""
    graph = _load_json("graph.json", {"nodes": [], "edges": []})
    isolated = _load_json("isolated_nodes.json", [])
    comms = _load_json("communities.json", {"communities": []}).get("communities", [])
    kinds: dict[str, int] = {}
    domains: dict[str, int] = {}
    for n in graph["nodes"]:
        for k in n.get("kinds", ["architecture"]):
            kinds[k] = kinds.get(k, 0) + 1
    return {
        "nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
        "communities": len(comms), "isolated_nodes": len(isolated),
        "isolated": [{"name": n["name"], "type": n["type"]} for n in isolated],
        "by_kind": kinds,
    }


@app.get("/api/map")
def graph_map():
    """The whole graph for the Map view: nodes (with domain + community) + edges."""
    g = _load_json("graph.json", {"nodes": [], "edges": []})
    menu = {}
    mpath = Path(os.environ.get("EAWIKI_MENU", "data/togaf92_metamodel.json"))
    if mpath.exists():
        menu = json.loads(mpath.read_text(encoding="utf-8")).get("node_types", {})
    comm_of: dict[str, str] = {}
    for c in _load_json("communities.json", {"communities": []}).get("communities", []):
        for mid in c.get("member_ids", []):
            comm_of[mid] = c["name"]
    nodes = [{"id": n["node_id"], "name": n.get("name", ""), "type": n.get("type", "element"),
              "domain": (menu.get(n.get("type", ""), {}) or {}).get("domain", "Other"),
              "community": comm_of.get(n["node_id"], "")}
             for n in g["nodes"]]
    edges = [{"source": e["source"], "target": e["target"],
              "relation": e.get("relation", "associated_with")}
             for e in g["edges"] if e.get("source") != e.get("target")]
    return {"nodes": nodes, "edges": edges}


@app.get("/api/graph")
def graph(name: str):
    """One-hop subgraph of the entity named (for the wiki/graph view)."""
    r = _retriever()
    ents = r.entities_in_question(name) or r.find_entities(name)
    if not ents:
        raise HTTPException(404, f"no entity matching '{name}'")
    return r.subgraph(ents[0]["node_id"])


@app.get("/api/kb")
def kb(q: str, k: int = 10, kinds: Optional[str] = None):
    """Vector search over blocks (the 'knowledge base' view)."""
    kinds_list = [x.strip() for x in kinds.split(",")] if kinds else None
    return {"results": _retriever().vector_search(q, k=k, kinds=kinds_list)}


BLOCKS_DIR = Path(os.environ.get("EAWIKI_BLOCKS", "data/blocks"))
SAMPLES = Path(os.environ.get("EAWIKI_SAMPLES", "docs/samples"))
ARCHIVE = Path(os.environ.get("EAWIKI_ARCHIVE", "docs/_archive"))


def _block_files():
    # Read fresh each call — a re-ingest rewrites this directory, so caching would
    # serve a stale document list after an add/remove.
    return sorted(glob.glob(f"{BLOCKS_DIR}/*.blocks.json"))


@app.get("/api/docs")
def docs():
    """Source documents (the 'knowledge base' view): one card per ingested doc."""
    out = []
    for fp in _block_files():
        d = json.loads(Path(fp).read_text(encoding="utf-8"))
        blocks = d.get("blocks", [])
        kind = blocks[0].get("kind", "architecture") if blocks else "architecture"
        out.append({"doc_id": d.get("doc_id", Path(fp).stem),
                    "blocks": len(blocks), "kind": kind,
                    "counts": d.get("counts", {})})
    return {"docs": out}


@app.post("/api/docs/add")
async def docs_add(file: UploadFile = File(...)):
    """Add a source .docx to the ingest set and kick off a (clean) full re-ingest.
    Add is not purely additive: the graph is deduped and the wiki/community summaries
    are cross-document, so everything downstream is rebuilt from the whole set."""
    from eawiki import pipeline
    if pipeline.status().get("running"):
        raise HTTPException(409, "A re-ingest is already running; wait for it to finish.")
    name = Path(file.filename or "").name            # strip any path components
    if not name.lower().endswith(".docx"):
        raise HTTPException(400, "Only .docx documents are supported.")
    SAMPLES.mkdir(parents=True, exist_ok=True)
    (SAMPLES / name).write_bytes(await file.read())
    return {"ok": True, "doc_id": Path(name).stem, "reingest": pipeline.run_async()}


@app.delete("/api/docs/{doc_id}")
def docs_remove(doc_id: str):
    """Remove a document: archive its source .docx out of the ingest set and rebuild.
    The re-ingest clears derived outputs first, so the doc's blocks, graph contribution
    and wiki page all disappear; shared entities keep their other evidence."""
    from eawiki import pipeline
    if pipeline.status().get("running"):
        raise HTTPException(409, "A re-ingest is already running; wait for it to finish.")
    safe = Path(doc_id).name
    matches = [p for p in SAMPLES.rglob("*.docx") if p.stem == safe]
    if not matches:
        raise HTTPException(404, f"no source document '{doc_id}'")
    remaining = [p for p in SAMPLES.rglob("*.docx") if p.stem != safe]
    if not remaining:
        raise HTTPException(400, "Cannot remove the last document — the knowledge base would be empty.")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    for p in matches:
        p.rename(ARCHIVE / p.name)
    return {"ok": True, "doc_id": safe, "archived": [p.name for p in matches],
            "reingest": pipeline.run_async()}


@app.get("/api/block/{block_id:path}")
def block(block_id: str):
    """One source block by id (for citation popups)."""
    for fp in _block_files():
        for b in json.loads(Path(fp).read_text(encoding="utf-8")).get("blocks", []):
            if b.get("block_id") == block_id:
                return {"block_id": block_id, "doc_id": b.get("doc_id"),
                        "section": " / ".join(b.get("section_path", [])),
                        "type": b.get("type"), "kind": b.get("kind", "architecture"),
                        "text": b.get("text", "")}
    raise HTTPException(404, f"no block '{block_id}'")


# --- use-case registry (the UI builder's CRUD) ---------------------------
@app.get("/api/usecases")
def usecases_list():
    from eawiki import usecases as uc
    return {"usecases": uc.list_specs()}


@app.get("/api/usecases/{uc_id}")
def usecase_get(uc_id: str):
    from eawiki import usecases as uc
    s = uc.get(uc_id)
    if not s:
        raise HTTPException(404, f"no use case '{uc_id}'")
    return s


@app.post("/api/usecases")
def usecase_create(spec: dict):
    from eawiki import usecases as uc
    try:
        return uc.save(spec)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/usecases/{uc_id}")
def usecase_update(uc_id: str, spec: dict):
    from eawiki import usecases as uc
    try:
        return uc.save(spec, uc_id=uc_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/usecases/{uc_id}")
def usecase_delete(uc_id: str):
    from eawiki import usecases as uc
    return {"deleted": uc.delete(uc_id)}


class RunBody(BaseModel):
    items: list[dict]
    safety: bool = False
    k: int = 8
    context_mode: str = "auto"       # full | retrieval | auto


@app.post("/api/usecases/{uc_id}/run")
def usecase_run(uc_id: str, body: RunBody):
    """Execute a use case over the given input items (the LangGraph engine)."""
    from eawiki import usecases as uc
    from eawiki.query import executor
    spec = uc.get(uc_id)
    if not spec:
        raise HTTPException(404, f"no use case '{uc_id}'")
    from eawiki import obs
    with obs.span(f"usecase:{uc_id}", kind="CHAIN", items=len(body.items)):
        return executor.run(spec, body.items, backend=API_BACKEND, safety_llm=body.safety,
                            k=body.k, context_mode=body.context_mode)


# --- metamodel (node & edge types) registry ------------------------------
@app.get("/api/metamodel")
def metamodel_get():
    from eawiki import metamodel as mm
    return mm.view()


@app.put("/api/metamodel/node/{key}")
def metamodel_node_put(key: str, obj: dict):
    from eawiki import metamodel as mm
    try:
        mm.upsert_node(key, obj); return mm.view()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/metamodel/node/{key}")
def metamodel_node_del(key: str):
    from eawiki import metamodel as mm
    try:
        mm.delete_node(key); return mm.view()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/metamodel/edge/{key}")
def metamodel_edge_put(key: str, obj: dict):
    from eawiki import metamodel as mm
    try:
        mm.upsert_edge(key, obj); return mm.view()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/metamodel/edge/{key}")
def metamodel_edge_del(key: str):
    from eawiki import metamodel as mm
    mm.delete_edge(key); return mm.view()


@app.get("/api/reingest/status")
def reingest_status():
    from eawiki import pipeline
    return pipeline.status()


@app.post("/api/reingest")
def reingest_run():
    from eawiki import pipeline
    return pipeline.run_async()


# --- static frontend (mounted last so /api/* wins) -----------------------
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
