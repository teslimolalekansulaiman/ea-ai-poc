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

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PAGES = Path(os.environ.get("EAWIKI_PAGES", "data/pages"))
GRAPH = Path(os.environ.get("EAWIKI_GRAPH", "data/graph"))
# Prefer the built React app (ui/dist); fall back to the single-file UI (web/).
_web_env = os.environ.get("EAWIKI_WEB")
WEB = Path(_web_env) if _web_env else (Path("ui/dist") if Path("ui/dist").exists() else Path("web"))
API_BACKEND = os.environ.get("EAWIKI_API_BACKEND", "openrouter")

app = FastAPI(title="EA GraphRAG Wiki API", version="1.0")


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


# --- models --------------------------------------------------------------
class AskReq(BaseModel):
    question: str
    k: int = 8
    kinds: Optional[list[str]] = None
    safety: bool = True


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
              use_llm=True, safety_llm=req.safety)
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


@lru_cache(maxsize=1)
def _block_files():
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


# --- static frontend (mounted last so /api/* wins) -----------------------
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
