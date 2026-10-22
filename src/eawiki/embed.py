"""Step 5 — Embed blocks into a vector index.

The index unit is the **small block** (not the assembled section): small units give
sharper matches and more precise citations. Two refinements from the design:

  * Enrich before embedding (contextual retrieval): each block's text is prefixed
    with its doc + section path, so a lone paragraph is findable and self-explaining.
  * Expand at query time (small -> big): handled at retrieval, not here; we keep the
    block_id / doc_id / section_path / ordinal so neighbours can be pulled later.

Embeddings come from a **pluggable backend**. Production uses the **Pulse API** (the platform
used for all models here — LLM + embeddings); add a `pulse` backend (one class + one line in
`get_embedder`) once its endpoint/auth/model-ids are known. The rest are local-dev fallbacks:
  * `st`     — sentence-transformers, local, CPU-friendly
  * `vertex` — Vertex AI text-embedding (example of a hosted backend)
  * `hash`   — deterministic hashing bag-of-words, no model/deps (PLUMBING TESTS ONLY)

Files stay the system of record. Output is JSONL (one block per line) so it streams,
diffs, and supports incremental re-embed of a single doc later. Step 6 loads it into
ArcadeDB's vector index.

    python -m eawiki.embed --backend st
    python -m eawiki.embed --backend hash          # fast smoke test, no model
    python -m eawiki.embed --backend vertex --model text-embedding-004   # on GCP

Backend + model + dim are configurable by flag or by env var (env is the default, so
the GCP VM sets them once and the command needs no flags):
    EAWIKI_EMBED_BACKEND   EAWIKI_EMBED_MODEL   EAWIKI_EMBED_DIM
To add a different GCP embedder: add one `Embedder` class (set `.model`, `.dim`,
`.encode() -> (n, dim) L2-normalized`) and one line in `get_embedder`. Whatever model
you pick, its `dim` is written to the meta file and Step 6 builds the ArcadeDB vector
index to match — and the SAME model must be used at query time.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Protocol

import numpy as np

from eawiki.blocks import Block, load_blocks

# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------
ST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"   # 384-dim, small, fast
VERTEX_MODEL = "text-embedding-004"                    # 768-dim
HASH_DIM = 384
MAX_CHARS = 1200        # ~300 tokens; only blocks longer than this are split
OVERLAP = 150           # char overlap between chunks of an oversized block
SKIP_TYPES = ("heading",)  # heading text already travels via each block's section_path


# ---------------------------------------------------------------------------
# 1) what text gets embedded — enrichment + chunking
# ---------------------------------------------------------------------------
def enrich(block: Block) -> str:
    """The text to embed: a context header (doc > section path) + the block text.

    The header makes an isolated block self-explaining to the embedder and at
    query time, which is the whole point of contextual retrieval.
    """
    text = (block.text or "").strip()
    if not text:
        return ""
    header = block.doc_id
    if block.section_path:
        header += " > " + " / ".join(block.section_path)
    return f"{header}\n\n{text}"


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP) -> list[str]:
    """Split only oversized text, on paragraph/sentence-ish boundaries, with overlap.
    Short blocks (the vast majority) pass through as a single chunk."""
    if len(text) <= max_chars:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # prefer to break at a newline or space near the limit
            brk = max(text.rfind("\n", start, end), text.rfind(". ", start, end),
                      text.rfind(" ", start, end))
            if brk > start + max_chars // 2:
                end = brk
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def embeddable_units(blocks: Iterable[Block], skip_types=SKIP_TYPES,
                     max_chars: int = MAX_CHARS, overlap: int = OVERLAP) -> list[dict]:
    """Expand blocks into the units that will actually be embedded.

    One short block -> one unit; one oversized block -> several chunk units that
    share the block's identity (id suffixed `#0`, `#1`, ...). Each unit carries the
    provenance needed for retrieval + small->big expansion.
    """
    units: list[dict] = []
    for b in blocks:
        if b.type in skip_types:
            continue
        text = enrich(b)
        if not text:
            continue
        chunks = chunk_text(text, max_chars, overlap)
        for i, c in enumerate(chunks):
            units.append({
                "id": b.block_id if len(chunks) == 1 else f"{b.block_id}#{i}",
                "block_id": b.block_id, "doc_id": b.doc_id, "type": b.type,
                "kind": getattr(b, "kind", "architecture"),
                "section_path": b.section_path, "ordinal": b.ordinal,
                "chunk": i, "n_chunks": len(chunks), "text": c,
            })
    return units


# ---------------------------------------------------------------------------
# 2) pluggable embedder backends
# ---------------------------------------------------------------------------
class Embedder(Protocol):
    name: str
    model: str
    dim: int
    def encode(self, texts: list[str]) -> np.ndarray: ...  # (n, dim), L2-normalized


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (mat / norms).astype(np.float32)


class SentenceTransformerEmbedder:
    """Local embeddings via sentence-transformers (dev default). CPU is fine."""
    name = "st"

    def __init__(self, model: str = ST_MODEL, batch_size: int = 64):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "backend 'st' needs sentence-transformers: pip install sentence-transformers"
            ) from e
        self.model = model
        self._st = SentenceTransformer(model)
        self.dim = int(self._st.get_sentence_embedding_dimension())
        self._bs = batch_size

    def encode(self, texts: list[str]) -> np.ndarray:
        vecs = self._st.encode(texts, batch_size=self._bs, convert_to_numpy=True,
                               normalize_embeddings=True, show_progress_bar=False)
        return vecs.astype(np.float32)


class VertexAIEmbedder:
    """GCP Vertex AI text embeddings (prod). Uses Application Default Credentials
    on the VM (`gcloud auth application-default login`, or the VM service account).
    Does not run without GCP creds; wired so the VM needs no code change."""
    name = "vertex"

    def __init__(self, model: str = VERTEX_MODEL, batch_size: int = 32,
                 project: Optional[str] = None, location: str = "us-central1"):
        try:
            import vertexai
            from vertexai.language_models import TextEmbeddingModel
        except ImportError as e:
            raise ImportError(
                "backend 'vertex' needs google-cloud-aiplatform: "
                "pip install google-cloud-aiplatform"
            ) from e
        vertexai.init(project=project, location=location)
        self.model = model
        self._m = TextEmbeddingModel.from_pretrained(model)
        self._bs = batch_size
        self.dim = 768  # text-embedding-004/005; confirm if you switch models

    def encode(self, texts: list[str]) -> np.ndarray:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._bs):
            batch = texts[i:i + self._bs]
            res = self._m.get_embeddings(batch)
            out.extend(e.values for e in res)
        return _l2_normalize(np.asarray(out, dtype=np.float32))


class HashingEmbedder:
    """Deterministic hashing bag-of-words -> fixed-dim vector. NO semantic quality;
    for testing the embed->load->query plumbing without downloading a model."""
    name = "hash"

    def __init__(self, dim: int = HASH_DIM):
        self.model = f"hashing-bow-{dim}"
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        mat = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, t in enumerate(texts):
            for tok in t.lower().split():
                mat[r, hash(tok) % self.dim] += 1.0
        return _l2_normalize(mat)


def get_embedder(backend: str, model: Optional[str], dim: int,
                 batch_size: int) -> Embedder:
    if backend == "st":
        return SentenceTransformerEmbedder(model or ST_MODEL, batch_size)
    if backend == "vertex":
        return VertexAIEmbedder(model or VERTEX_MODEL, batch_size)
    if backend == "hash":
        return HashingEmbedder(dim)
    raise ValueError(f"unknown embed backend: {backend}")


# ---------------------------------------------------------------------------
# 3) run: embed all units, write JSONL + meta
# ---------------------------------------------------------------------------
def embed_units(units: list[dict], embedder: Embedder) -> list[dict]:
    """Attach an `embedding` (list[float]) to every unit, in place-ish (new dicts)."""
    vecs = embedder.encode([u["text"] for u in units]) if units else np.zeros((0,))
    out = []
    for u, v in zip(units, vecs):
        rec = dict(u)
        rec["embedding"] = [round(float(x), 6) for x in v]
        out.append(rec)
    return out


def write_index(records: list[dict], embedder: Embedder, out_path: Path,
                meta_path: Path, params: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    meta = {
        "backend": embedder.name, "model": embedder.model, "dim": embedder.dim,
        "normalized": True, "count": len(records),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": params,
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 5 — embed blocks into a vector index")
    ap.add_argument("--in", dest="in_dir", default="data/blocks")
    ap.add_argument("--out", dest="out", default="data/graph/embeddings.jsonl")
    ap.add_argument("--meta", dest="meta", default="data/graph/embeddings_meta.json")
    # Backend / model / dim are configurable by flag OR env var (env is the default,
    # so the GCP VM sets them once in the environment — no flags, no code edits):
    #   EAWIKI_EMBED_BACKEND  EAWIKI_EMBED_MODEL  EAWIKI_EMBED_DIM
    ap.add_argument("--backend", default=os.environ.get("EAWIKI_EMBED_BACKEND", "st"),
                    choices=["st", "vertex", "hash"])
    ap.add_argument("--model", default=os.environ.get("EAWIKI_EMBED_MODEL"),
                    help="embedding model name; overrides the backend default (env: EAWIKI_EMBED_MODEL)")
    ap.add_argument("--dim", type=int, default=int(os.environ.get("EAWIKI_EMBED_DIM", HASH_DIM)),
                    help="vector dim for the hash backend (env: EAWIKI_EMBED_DIM)")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    ap.add_argument("--overlap", type=int, default=OVERLAP)
    ap.add_argument("--only-doc", default=None, help="embed only this doc_id (incremental)")
    args = ap.parse_args()

    blocks: list[Block] = []
    for fp in sorted(glob.glob(f"{args.in_dir}/*.blocks.json")):
        blocks += load_blocks(Path(fp))
    if args.only_doc:
        blocks = [b for b in blocks if b.doc_id == args.only_doc]

    units = embeddable_units(blocks, max_chars=args.max_chars, overlap=args.overlap)
    print(f"blocks: {len(blocks)}   embeddable units: {len(units)}   backend: {args.backend}")

    embedder = get_embedder(args.backend, args.model, args.dim, args.batch_size)
    print(f"model: {embedder.model}   dim: {embedder.dim}")

    records = embed_units(units, embedder)
    params = {"max_chars": args.max_chars, "overlap": args.overlap,
              "skip_types": list(SKIP_TYPES), "only_doc": args.only_doc}
    write_index(records, embedder, Path(args.out), Path(args.meta), params)

    n_chunked = sum(1 for r in records if r["n_chunks"] > 1)
    print(f"embedded: {len(records)} vectors  (from oversized/split: {n_chunked})")
    print(f"-> {args.out}\n-> {args.meta}")


if __name__ == "__main__":
    main()
