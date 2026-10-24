"""Pluggable storage seams, so dev and prod differ only by configuration.

The knowledge base the pipeline GENERATES (wiki pages, graph JSON, block JSON, figure
images) lives under one data root. Locally that root is the `data/` folder; on Cloud Run
it is a Google Cloud Storage bucket. The serving app only ever READS it — ingestion runs
offline (the pipeline writes local files) and the built `data/` is pushed to the bucket.

One env var picks the backend, and `local` is the default, so nothing changes until you
flip the config:

    FILE_BACKEND=local                      # (default) read/write under EAWIKI_DATA (./data)
    FILE_BACKEND=gcs  GCS_BUCKET=<name>     # Cloud Run: read objects from the bucket
                      GCS_PREFIX=<path>      # optional sub-path within the bucket

Keys are POSIX paths relative to the data root — e.g. "pages/foo.md", "graph/graph.json",
"blocks/doc.blocks.json", "images/doc-3.png". A stored path like "data/images/x.png" maps
to the key "images/x.png" via `rel_key` (it strips the data root).

GCS auth on Cloud Run is automatic: the service account is the identity (Application
Default Credentials), so there is NO key to configure — only the bucket name plus an IAM
grant. `google-cloud-storage` is imported lazily, so local dev never needs the dependency.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

DATA_ROOT = os.environ.get("EAWIKI_DATA", "data")


def rel_key(path) -> str:
    """Turn a stored path ('data/images/x.png', or an absolute one) into a store key
    ('images/x.png'). A value already relative to the root is returned unchanged."""
    p = str(path).replace("\\", "/")
    root = DATA_ROOT.rstrip("/") + "/"
    if p.startswith(root):
        return p[len(root):]
    # Absolute or otherwise-rooted path: keep everything after a "/data/" segment if present.
    marker = "/" + DATA_ROOT.strip("/") + "/"
    if marker in p:
        return p.split(marker, 1)[1]
    return p.lstrip("/")


class FileStore:
    """Read/write the generated KB by key. Reads return None when the key is absent, so
    callers can fall back the way the file-based code did (`exists()` for a 404 path)."""

    def read_text(self, key: str) -> Optional[str]: raise NotImplementedError
    def read_bytes(self, key: str) -> Optional[bytes]: raise NotImplementedError
    def exists(self, key: str) -> bool: raise NotImplementedError
    def list(self, prefix: str, suffix: str = "") -> list[str]:
        """Keys of the immediate children of `prefix` (non-recursive, like glob('*.ext'))."""
        raise NotImplementedError
    def write_bytes(self, key: str, data: bytes) -> None: raise NotImplementedError
    def write_text(self, key: str, text: str) -> None:
        self.write_bytes(key, text.encode("utf-8"))
    def delete(self, key: str) -> bool: raise NotImplementedError


class LocalFileStore(FileStore):
    def __init__(self, root: str = DATA_ROOT):
        self.root = Path(root)

    def _p(self, key: str) -> Path:
        return self.root / key.lstrip("/")

    def read_text(self, key):
        p = self._p(key)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def read_bytes(self, key):
        p = self._p(key)
        return p.read_bytes() if p.exists() else None

    def exists(self, key):
        return self._p(key).exists()

    def list(self, prefix, suffix=""):
        d = self._p(prefix)
        if not d.exists():
            return []
        pref = prefix.strip("/")
        return sorted(f"{pref}/{x.name}" for x in d.iterdir()
                      if x.is_file() and x.name.endswith(suffix))

    def write_bytes(self, key, data):
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def delete(self, key):
        p = self._p(key)
        if p.exists():
            p.unlink()
            return True
        return False


class GCSFileStore(FileStore):
    def __init__(self, bucket: str, prefix: str = ""):
        from google.cloud import storage  # lazy: only when FILE_BACKEND=gcs
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)
        self.prefix = prefix.strip("/")

    def _name(self, key: str) -> str:
        key = key.lstrip("/")
        return f"{self.prefix}/{key}" if self.prefix else key

    def _blob(self, key: str):
        return self._bucket.blob(self._name(key))

    def _unprefix(self, name: str) -> str:
        return name[len(self.prefix) + 1:] if self.prefix else name

    def read_text(self, key):
        b = self._blob(key)
        return b.download_as_text(encoding="utf-8") if b.exists() else None

    def read_bytes(self, key):
        b = self._blob(key)
        return b.download_as_bytes() if b.exists() else None

    def exists(self, key):
        return self._blob(key).exists()

    def list(self, prefix, suffix=""):
        pref = prefix.strip("/")
        base = self._name(pref) + "/"
        # delimiter="/" -> only the immediate children of the prefix, like a flat glob.
        out = []
        for bl in self._client.list_blobs(self._bucket, prefix=base, delimiter="/"):
            key = self._unprefix(bl.name)
            if key.endswith(suffix):
                out.append(key)
        return sorted(out)

    def write_bytes(self, key, data):
        self._blob(key).upload_from_string(data)

    def delete(self, key):
        b = self._blob(key)
        if b.exists():
            b.delete()
            return True
        return False


@lru_cache(maxsize=1)
def filestore() -> FileStore:
    """The configured FileStore (one per process). FILE_BACKEND selects it."""
    backend = os.environ.get("FILE_BACKEND", "local").lower()
    if backend == "gcs":
        bucket = os.environ.get("GCS_BUCKET")
        if not bucket:
            raise RuntimeError("FILE_BACKEND=gcs requires GCS_BUCKET to be set.")
        return GCSFileStore(bucket, os.environ.get("GCS_PREFIX", ""))
    if backend != "local":
        raise RuntimeError(f"unknown FILE_BACKEND '{backend}' (expected local|gcs)")
    return LocalFileStore(os.environ.get("EAWIKI_DATA", "data"))


def serve_only() -> bool:
    """Read-only serving: KB-mutating endpoints (add/remove/re-ingest/metamodel) are
    disabled. Set EAWIKI_SERVE_ONLY on Cloud Run, where ingestion runs offline instead."""
    return os.environ.get("EAWIKI_SERVE_ONLY", "").lower() in ("1", "true", "yes", "on")
