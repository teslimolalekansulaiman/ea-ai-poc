"""FastAPI service for the EA GraphRAG wiki.

Feeds the 5-view UI (ask / wiki / landscape / coverage / kb) and serves the static
frontend from the SAME app — so the whole thing is one Cloud Run service (a React
build or a single-file UI both drop into `web/`). Pages come from files (the system of
record); ask / graph / kb use the query layer over ArcadeDB.

    uvicorn eawiki.api.app:app --reload          # dev
    uvicorn eawiki.api.app:app --host 0.0.0.0 --port 8080   # Cloud Run
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from eawiki.storage import filestore, rel_key, serve_only

# The generated KB is addressed by key relative to the data root (local ./data, or the
# GCS bucket in prod). Reads go through the FileStore; FILE_BACKEND picks local vs gcs.
PAGES_KEY = "pages"
BLOCKS_KEY = "blocks"
MENU_KEY = os.environ.get("EAWIKI_MENU_KEY", "togaf92_metamodel.json")
# Prefer the built React app (ui/dist); fall back to the single-file UI (web/).
_web_env = os.environ.get("EAWIKI_WEB")
WEB = Path(_web_env) if _web_env else (Path("ui/dist") if Path("ui/dist").exists() else Path("web"))
API_BACKEND = os.environ.get("EAWIKI_API_BACKEND", "openrouter")
# Model for answering (Ask, use-case runs). Unset -> VLM_MODEL, the same model the ingest
# pipeline uses; set it to answer with a different model than the one that builds the wiki.
ASK_MODEL = os.environ.get("EAWIKI_ASK_MODEL") or None

@asynccontextmanager
async def _lifespan(_app):
    # Authoring instances (EAWIKI_SYNC_*) restore data/ and docs/ from buckets first;
    # a no-op everywhere else.
    from eawiki import sync
    sync.pull_if_enabled()
    yield


app = FastAPI(title="EA GraphRAG Wiki API", version="1.0", lifespan=_lifespan)

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


@lru_cache(maxsize=1)
def _retriever():
    from eawiki.query.retrieve import Retriever
    return Retriever()


def _load_json(name: str, default):
    txt = filestore().read_text(f"graph/{name}")
    return json.loads(txt) if txt else default


def _require_writable():
    """KB-mutating endpoints are disabled in read-only serving (Cloud Run); ingestion
    runs offline there and the built data/ is published to the bucket."""
    if serve_only():
        raise HTTPException(403, "This deployment is read-only; the knowledge base is "
                                 "built offline and published. KB edits are disabled.")


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
    from eawiki import sync
    return {"ok": True, "backend": API_BACKEND, "ask_model": ASK_MODEL or os.environ.get("VLM_MODEL"),
            "safety_llm": _safety_llm(),
            "sync": sync.status(),
            "pages": len(filestore().list(PAGES_KEY, ".md"))}


def _safety_llm() -> bool:
    """Model-based (NeMo) moderation layer. On by default; set EAWIKI_SAFETY_LLM=0 where the
    serving image does not carry nemoguardrails — the deterministic guard still runs, and
    /api/health reports which layers are active so the gap is visible, not silent."""
    return os.environ.get("EAWIKI_SAFETY_LLM", "1").lower() not in ("0", "false", "no", "off")


@app.post("/api/ask")
def ask(req: AskReq):
    """The guarded AI layer: route -> retrieve -> answer, with NeMo + deterministic guards."""
    from eawiki.query.ask import ask as run
    out = run(req.question, k=req.k, backend=API_BACKEND, model=ASK_MODEL, kinds=req.kinds,
              use_llm=True, safety_llm=req.safety and _safety_llm(), history=req.history)
    # One graph for display, from the SAME result the answer was grounded in (the graph
    # query engine), so the picture and the answer can never disagree. Surface provenance
    # (which template / generated), the query + facts (so a human can verify), and whether
    # a generated query passed back-translation verification.
    gr = out.get("graph_result")
    if gr:
        out["graph"] = {"nodes": gr.get("nodes", []), "edges": gr.get("edges", []),
                        "center": (gr.get("centers") or [None])[0],
                        "template": gr.get("template"), "summary": gr.get("summary"),
                        "facts": gr.get("facts"), "query": gr.get("query"),
                        "verified": gr.get("verified")}
    # Figures the answer actually cited → shown inline under the answer (image + desc),
    # so a diagram shows up in the output, not only in the citation popup.
    answer_text = out.get("answer", "") or ""
    figs, seen = [], set()
    for bid in out.get("blocks", []):
        if bid in seen or bid not in answer_text:
            continue
        seen.add(bid)
        b = _find_block(bid)
        if b and b.get("type") == "figure":
            ip = (b.get("figure") or {}).get("image_path")
            if ip and filestore().exists(rel_key(ip)):
                figs.append({"block_id": bid, "image_url": "/api/image/" + bid,
                             "description": b.get("description"),
                             "section": " / ".join(b.get("section_path", []))})
    if figs:
        out["figures"] = figs
    # The context itself is not returned, but its size is: what the model was actually given,
    # block by block, so "was this table cut off?" can be answered by looking.
    out["context_info"] = {
        "chars": len(out.get("context") or ""),
        "blocks": [{"block_id": b.get("block_id"), "type": b.get("btype"),
                    "chars": len(b.get("text") or "")} for b in out.get("_block_objs", [])]}
    return {k: v for k, v in out.items() if k != "context"}


@app.get("/api/pages")
def pages():
    """Subject wiki pages (the 'wiki' view)."""
    fs = filestore()
    out = []
    for key in fs.list(PAGES_KEY, ".md"):
        slug = Path(key).stem
        if slug.startswith("landscape-"):
            continue
        out.append({"slug": slug, "title": _title(fs.read_text(key) or "", slug)})
    return {"pages": out}


@app.get("/api/pages/{slug}")
def page(slug: str):
    md = filestore().read_text(f"{PAGES_KEY}/{Path(slug).name}.md")
    if md is None:
        # A table-only item has no page of its own: it is listed on its table's catalogue page.
        r = _load_json("page_redirects.json", {}).get(Path(slug).name)
        md = filestore().read_text(f"{PAGES_KEY}/{r['page']}.md") if r else None
        if md is None:
            raise HTTPException(404, f"no page '{slug}'")
        return {"slug": r["page"], "title": _title(md, r["page"]), "markdown": md,
                "listed_item": r["name"]}
    return {"slug": slug, "title": _title(md, slug), "markdown": md}


@app.get("/api/landscape")
def landscape():
    """Communities + their landscape pages (the 'landscape' view)."""
    comms = _load_json("communities.json", {"communities": []}).get("communities", [])
    fs = filestore()
    out = []
    for c in comms:
        has_page = fs.exists(f"{PAGES_KEY}/landscape-{c['slug']}.md")
        out.append({"slug": c["slug"], "name": c["name"], "size": c["size"],
                    "domain": c.get("dominant_domain"), "summary": c.get("summary", ""),
                    "has_page": has_page, "members": c.get("member_names", [])})
    return {"communities": out}


@app.get("/api/landscape/{slug}")
def landscape_page(slug: str):
    md = filestore().read_text(f"{PAGES_KEY}/landscape-{Path(slug).name}.md")
    if md is None:
        raise HTTPException(404, f"no landscape page '{slug}'")
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
    menu_txt = filestore().read_text(MENU_KEY)
    menu = json.loads(menu_txt).get("node_types", {}) if menu_txt else {}
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


# Source .docx + archive live OUTSIDE the data root (local-only; touched only by the
# offline/local ingest path, never in read-only serving).
SAMPLES = Path(os.environ.get("EAWIKI_SAMPLES", "docs/samples"))
ARCHIVE = Path(os.environ.get("EAWIKI_ARCHIVE", "docs/_archive"))


SOURCE_EXTS = (".docx", ".pptx")


def _source_files() -> list[Path]:
    return sorted(p for ext in SOURCE_EXTS for p in SAMPLES.rglob(f"*{ext}"))


def _block_files():
    # Read fresh each call — a re-ingest rewrites these, so caching would serve a stale
    # document list after an add/remove. Returns store keys ("blocks/<doc>.blocks.json").
    return filestore().list(BLOCKS_KEY, ".blocks.json")


@app.get("/api/docs")
def docs():
    """Source documents (the 'knowledge base' view): one card per ingested doc."""
    fs = filestore()
    out = []
    for key in _block_files():
        d = json.loads(fs.read_text(key) or "{}")
        blocks = d.get("blocks", [])
        kind = blocks[0].get("kind", "architecture") if blocks else "architecture"
        out.append({"doc_id": d.get("doc_id", Path(key).stem.replace(".blocks", "")),
                    "file": Path(d.get("source_file") or "").name or None,
                    "blocks": len(blocks), "kind": kind,
                    "counts": d.get("counts", {})})
    return {"docs": out}


@app.post("/api/docs/add")
async def docs_add(file: UploadFile = File(...)):
    """Add a source .docx or .pptx to the ingest set and kick off a (clean) full re-ingest.
    Add is not purely additive: the graph is deduped and the wiki/community summaries
    are cross-document, so everything downstream is rebuilt from the whole set."""
    _require_writable()
    from eawiki import pipeline
    if pipeline.status().get("running"):
        raise HTTPException(409, "A re-ingest is already running; wait for it to finish.")
    name = Path(file.filename or "").name            # strip any path components
    if not name.lower().endswith(SOURCE_EXTS):
        raise HTTPException(400, "Only .docx and .pptx documents are supported.")
    clash = [p.name for p in _source_files() if p.stem == Path(name).stem and p.name != name]
    if clash:
        raise HTTPException(409, f"'{clash[0]}' already uses the name '{Path(name).stem}'; "
                                 "rename the new file.")
    SAMPLES.mkdir(parents=True, exist_ok=True)
    (SAMPLES / name).write_bytes(await file.read())
    return {"ok": True, "doc_id": Path(name).stem, "reingest": pipeline.run_async()}


@app.delete("/api/docs/{doc_id}")
def docs_remove(doc_id: str):
    """Remove a document: archive its source .docx out of the ingest set and rebuild.
    The re-ingest clears derived outputs first, so the doc's blocks, graph contribution
    and wiki page all disappear; shared entities keep their other evidence."""
    _require_writable()
    from eawiki import pipeline
    if pipeline.status().get("running"):
        raise HTTPException(409, "A re-ingest is already running; wait for it to finish.")
    safe = Path(doc_id).name
    matches = [p for p in _source_files() if p.stem == safe]
    if not matches:
        raise HTTPException(404, f"no source document '{doc_id}'")
    remaining = [p for p in _source_files() if p.stem != safe]
    if not remaining:
        raise HTTPException(400, "Cannot remove the last document — the knowledge base would be empty.")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    for p in matches:
        p.rename(ARCHIVE / p.name)
    return {"ok": True, "doc_id": safe, "archived": [p.name for p in matches],
            "reingest": pipeline.run_async()}


def _find_block(block_id: str):
    fs = filestore()
    for key in _block_files():
        for b in json.loads(fs.read_text(key) or "{}").get("blocks", []):
            if b.get("block_id") == block_id:
                return b
    return None


@app.get("/api/block/{block_id:path}")
def block(block_id: str):
    """One source block by id (for citation popups). Figures carry an image_url so the
    popup can show the actual picture, plus the model-generated description."""
    b = _find_block(block_id)
    if not b:
        raise HTTPException(404, f"no block '{block_id}'")
    out = {"block_id": block_id, "doc_id": b.get("doc_id"),
           "file": Path(b.get("source_file") or "").name or None,
           "section": " / ".join(b.get("section_path", [])),
           "type": b.get("type"), "kind": b.get("kind", "architecture"),
           "text": b.get("text", ""), "description": b.get("description")}
    if b.get("type") == "figure" and _usable_image((b.get("figure") or {}).get("image_path")):
        out["image_url"] = "/api/image/" + block_id
    return out


def _usable_image(path) -> bool:
    """True only for a real figure image. These sample .docx diagrams are drawn with
    Office shapes (no embedded raster), so Docling exports a ~21px sliver — we don't show
    those misleading strips. A usable image is at least 40px tall. Reads the bytes through
    the FileStore, so it works against local disk or the GCS bucket alike."""
    try:
        if not path:
            return False
        data = filestore().read_bytes(rel_key(path))
        if data is None:
            return False
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return True                      # non-PNG: assume usable
        import struct
        _, h = struct.unpack(">II", data[16:24])
        return h >= 40
    except Exception:
        return False


_IMG_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}


@app.get("/api/image/{block_id:path}")
def block_image(block_id: str):
    """The actual image for a figure block (referenced by /api/block's image_url). Served
    from bytes (not FileResponse) so GCS-backed images work the same as local ones."""
    from fastapi.responses import Response
    b = _find_block(block_id)
    ip = (b or {}).get("figure", {}).get("image_path") if b else None
    data = filestore().read_bytes(rel_key(ip)) if ip else None
    if data is None:
        raise HTTPException(404, f"no image for '{block_id}'")
    media = _IMG_MEDIA.get(Path(ip).suffix.lower(), "application/octet-stream")
    return Response(content=data, media_type=media)


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
    _require_writable()
    from eawiki import usecases as uc
    try:
        return uc.save(spec)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/usecases/{uc_id}")
def usecase_update(uc_id: str, spec: dict):
    _require_writable()
    from eawiki import usecases as uc
    try:
        return uc.save(spec, uc_id=uc_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/usecases/{uc_id}")
def usecase_delete(uc_id: str):
    _require_writable()
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
        result = executor.run(spec, body.items, backend=API_BACKEND, model=ASK_MODEL, safety_llm=body.safety,
                              k=body.k, context_mode=body.context_mode)
    try:        # persist the run for the audit trail / History view (best-effort)
        from eawiki import history
        status = result.get("status", "done") if isinstance(result, dict) else "done"
        rec = history.save_run(uc_id, body.items, result, status=status)
        if isinstance(result, dict):
            result["run_id"] = rec["id"]
    except Exception:
        pass
    return result


# --- history: chats + runs (operational records, SQLite) -----------------
class ChatBody(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    messages: list


@app.post("/api/chats")
def chat_save(body: ChatBody):
    from eawiki import history
    return history.save_chat(body.messages, chat_id=body.id, title=body.title)


@app.get("/api/chats")
def chat_list():
    from eawiki import history
    return {"chats": history.list_chats()}


@app.get("/api/chats/{chat_id}")
def chat_get(chat_id: str):
    from eawiki import history
    c = history.get_chat(chat_id)
    if not c:
        raise HTTPException(404, f"no chat '{chat_id}'")
    return c


@app.delete("/api/chats/{chat_id}")
def chat_delete(chat_id: str):
    from eawiki import history
    return {"deleted": history.delete_chat(chat_id)}


@app.get("/api/runs")
def runs_list(use_case: Optional[str] = None):
    from eawiki import history
    return {"runs": history.list_runs(use_case)}


@app.get("/api/runs/{run_id}")
def run_get(run_id: str):
    from eawiki import history
    r = history.get_run(run_id)
    if not r:
        raise HTTPException(404, f"no run '{run_id}'")
    return r


# --- metamodel (node & edge types) registry ------------------------------
@app.get("/api/metamodel")
def metamodel_get():
    from eawiki import metamodel as mm
    return mm.view()


@app.put("/api/metamodel/node/{key}")
def metamodel_node_put(key: str, obj: dict):
    _require_writable()
    from eawiki import metamodel as mm
    try:
        mm.upsert_node(key, obj); return mm.view()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/metamodel/node/{key}")
def metamodel_node_del(key: str):
    _require_writable()
    from eawiki import metamodel as mm
    try:
        mm.delete_node(key); return mm.view()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/metamodel/edge/{key}")
def metamodel_edge_put(key: str, obj: dict):
    _require_writable()
    from eawiki import metamodel as mm
    try:
        mm.upsert_edge(key, obj); return mm.view()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/metamodel/edge/{key}")
def metamodel_edge_del(key: str):
    _require_writable()
    from eawiki import metamodel as mm
    mm.delete_edge(key); return mm.view()


@app.get("/api/reingest/status")
def reingest_status():
    from eawiki import pipeline
    return pipeline.status()


@app.post("/api/reingest")
def reingest_run():
    _require_writable()
    from eawiki import pipeline
    return pipeline.run_async()


# --- static frontend (mounted last so /api/* wins) -----------------------
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
