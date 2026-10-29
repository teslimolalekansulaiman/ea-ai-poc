"""The source documents of the knowledge base: what may be added, and how a batch of changes is applied.

A file is checked and saved on its own, with a verdict the screen can show next to its name; nothing is rebuilt until the batch is applied.
That is the point of a bulk change: one rebuild for the whole batch, not one per file (and no waiting for the previous one to finish).

A document's `kind` is the class of the document (architecture | motivation | governance | reference). It is stamped on every block by the
parse step, which reads it from the name of the sub-folder the file sits in; so a file of any kind but `architecture` is saved in a folder of
that name, and an architecture file stays at the top, as it always did.
"""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from pathlib import Path

EXTS = (".docx", ".pptx")
DEFAULT_KIND = "architecture"
KINDS = {
    "architecture": "What exists: capabilities, applications, data, technology, security. Feeds the wiki pages and the graph.",
    "motivation": "Why: strategy, drivers, goals and objectives.",
    "governance": "The rules: principles, standards, policies and decisions. Kept apart so a principle is never read as a fact about the landscape.",
    "reference": "Background and frameworks. Answers questions; kept apart from the architecture facts.",
}
LIMITS = {"max_file_mb": int(os.environ.get("EAWIKI_MAX_UPLOAD_MB", "25")), "max_batch_files": 20, "max_batch_mb": 100}


def sources(samples: Path) -> list[Path]:
    return sorted(p for ext in EXTS for p in Path(samples).rglob(f"*{ext}"))


def kind_of(path: Path) -> str:
    return path.parent.name if path.parent.name in KINDS else DEFAULT_KIND


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _no(name: str, reason: str, status: int = 400) -> dict:
    return {"name": name, "doc_id": Path(name).stem, "state": "rejected", "reason": reason, "status": status}


def save(samples: Path, name: str, data: bytes, kind: str = DEFAULT_KIND, max_bytes: int | None = None) -> dict:
    """Check one file and save it. {'state': 'added' | 'replaced' | 'unchanged' | 'rejected', 'reason', 'kind', 'doc_id', 'name'}."""
    samples = Path(samples)
    name = Path(name or "").name                              # no path components
    limit = (max_bytes if max_bytes is not None else LIMITS["max_file_mb"] * 1024 * 1024)
    if not name.lower().endswith(EXTS):
        return _no(name, "Only .docx and .pptx documents are supported.")
    if kind not in KINDS:
        return _no(name, f"'{kind}' is not a kind of document (use {', '.join(KINDS)}).")
    if not data:
        return _no(name, "The file is empty.")
    if len(data) > limit:
        return _no(name, f"The file is larger than {limit // (1024 * 1024)} MB.", 413)
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return _no(name, "It cannot be opened as a Word or PowerPoint file (a .docx or .pptx is a zip of XML).")
    folder = samples if kind == DEFAULT_KIND else samples / kind
    target = folder / name
    have = sources(samples)
    for p in have:
        if p.stem == target.stem and p != target:
            return _no(name, f"'{p.name}' ({kind_of(p)}) already uses the name '{target.stem}'; rename the new file.", 409)
    digest = hashlib.sha256(data).hexdigest()
    for p in have:
        if p != target and p.stat().st_size == len(data) and _sha(p) == digest:
            return _no(name, f"Same content as '{p.name}', which is already in the knowledge base.", 409)
    if target.exists() and _sha(target) == digest:
        return {"name": name, "doc_id": target.stem, "kind": kind, "state": "unchanged", "reason": "Already in the knowledge base, unchanged."}
    replaced = target.exists()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{name}.part"
    tmp.write_bytes(data)
    os.replace(tmp, target)                                   # a file is whole or not there: never half written
    return {"name": name, "doc_id": target.stem, "kind": kind, "state": "replaced" if replaced else "added",
            "reason": "Replaces the file of the same name." if replaced else ""}


def archive(samples: Path, archive_dir: Path, doc_ids: list[str], adding: int = 0) -> list[str]:
    """Move the sources of these documents out of the ingest set. Raises LookupError for an unknown document and ValueError when
    nothing would be left (`adding` files just saved count as left)."""
    have = sources(samples)
    ids = [Path(d).name for d in doc_ids]
    unknown = [d for d in ids if not any(p.stem == d for p in have)]
    if unknown:
        raise LookupError(f"no source document '{unknown[0]}'")
    going = [p for p in have if p.stem in ids]
    if len(have) - len(going) + max(adding, 0) < 1:
        raise ValueError("Cannot remove the last document — the knowledge base would be empty.")
    Path(archive_dir).mkdir(parents=True, exist_ok=True)
    for p in going:
        p.rename(Path(archive_dir) / p.name)
    return [p.name for p in going]
