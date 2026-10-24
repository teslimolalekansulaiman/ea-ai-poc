"""Keep an authoring instance's local data durable on Cloud Run.

The pipeline reads and writes local folders (data/, docs/samples). Cloud Run's disk is
ephemeral, so an authoring instance restores those folders from buckets at start-up and
pushes them back when a re-ingest changes them. Nothing here runs unless both variables
are set, so local development is unchanged:

    EAWIKI_SYNC_BUCKET   the knowledge-base bucket (same layout the serving app reads)
    EAWIKI_SYNC_STATE    gs://bucket/prefix holding the source documents (sources/) and
                         the per-step caches (cache/) — kept OUT of the KB bucket, which
                         the serving app mirrors exactly.

A push mirrors exactly (it deletes remote files that are not local), so it is refused when
the start-up restore did not complete: pushing from an empty folder would erase the bucket.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("eawiki.sync")

DATA = Path(os.environ.get("EAWIKI_DATA", "data"))
SAMPLES = Path(os.environ.get("EAWIKI_SAMPLES", "docs/samples"))
CACHE_DIRS = ("desc_cache", "pages_cache", "subject_cache", "plan_cache")   # under data/graph
_NOT_PUBLISHED = {"app.db", ".reingest_needed"}

_state: dict = {"enabled": False, "pulled": False, "error": None}


def _split(uri: str) -> tuple[str, str]:
    bucket, _, prefix = uri.removeprefix("gs://").strip("/").partition("/")
    return bucket, prefix.strip("/")


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode()


def _walk(root: Path, keep=lambda rel: True) -> dict[str, Path]:
    out: dict[str, Path] = {}
    if root.exists():
        for p in root.rglob("*"):
            rel = p.relative_to(root).as_posix()
            if p.is_file() and "__pycache__" not in rel and keep(rel):
                out[rel] = p
    return out


def _is_cache(rel: str) -> bool:
    return rel.startswith(tuple(f"graph/{c}/" for c in CACHE_DIRS))


class Sync:
    def __init__(self, kb_bucket: str, state_uri: str, client=None):
        if client is None:
            from google.cloud import storage     # lazy: only on an authoring instance
            client = storage.Client()
        self.client = client
        self.kb = (kb_bucket, "")
        sb, sp = _split(state_uri)
        self.sources = (sb, f"{sp}/sources" if sp else "sources")
        self.cache = (sb, f"{sp}/cache" if sp else "cache")
        self.pulled = False

    # -- primitives ----------------------------------------------------------
    def _list(self, where: tuple[str, str]) -> dict:
        bucket, prefix = where
        pre = prefix + "/" if prefix else ""
        return {b.name[len(pre):]: b for b in self.client.list_blobs(bucket, prefix=pre)
                if not b.name.endswith("/")}

    def _download(self, where, root: Path) -> int:
        n = 0
        for rel, blob in self._list(where).items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(target))
            n += 1
        return n

    def _mirror(self, where, files: dict[str, Path]) -> tuple[int, int]:
        bucket, prefix = where
        pre = prefix + "/" if prefix else ""
        remote = self._list(where)
        b = self.client.bucket(bucket)
        up = rm = 0
        for rel, p in files.items():
            cur = remote.get(rel)
            if cur is None or cur.md5_hash != _md5(p):
                b.blob(pre + rel).upload_from_filename(str(p))
                up += 1
        for rel, blob in remote.items():
            if rel not in files:
                blob.delete()
                rm += 1
        return up, rm

    # -- operations ----------------------------------------------------------
    def pull(self) -> dict:
        n_kb = self._download(self.kb, DATA)
        n_src = self._download(self.sources, SAMPLES)
        n_cache = self._download(self.cache, DATA / "graph")
        self.pulled = True
        return {"kb": n_kb, "sources": n_src, "cache": n_cache}

    def _ready(self) -> None:
        if not self.pulled:
            raise RuntimeError("start-up restore from the bucket did not complete; "
                               "refusing to overwrite it from local state")

    def push_sources(self) -> tuple[int, int]:
        self._ready()
        return self._mirror(self.sources, _walk(SAMPLES))

    def push_results(self) -> dict:
        self._ready()
        data = _walk(DATA, lambda rel: rel not in _NOT_PUBLISHED and not _is_cache(rel))
        caches = {rel[len("graph/"):]: p for rel, p in
                  _walk(DATA, _is_cache).items()}
        return {"kb": self._mirror(self.kb, data), "cache": self._mirror(self.cache, caches)}


_sync: Optional[Sync] = None


def enabled() -> bool:
    return bool(os.environ.get("EAWIKI_SYNC_BUCKET") and os.environ.get("EAWIKI_SYNC_STATE"))


def _get() -> Sync:
    global _sync
    if _sync is None:
        _sync = Sync(os.environ["EAWIKI_SYNC_BUCKET"], os.environ["EAWIKI_SYNC_STATE"])
    return _sync


def pull_if_enabled() -> None:
    _state["enabled"] = enabled()
    if not enabled():
        return
    try:
        counts = _get().pull()
        _state.update(pulled=True, error=None, restored=counts)
        log.info("restored from buckets: %s", counts)
    except Exception as e:                  # keep serving; pushes stay refused
        _state.update(pulled=False, error=f"{type(e).__name__}: {e}")
        log.exception("restore failed")


def push_sources() -> None:
    if enabled():
        _get().push_sources()


def push_results() -> None:
    if enabled():
        _get().push_results()


def status() -> dict:
    return dict(_state)
