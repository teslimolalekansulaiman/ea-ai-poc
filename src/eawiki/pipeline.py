"""Re-ingest orchestrator — re-run the build pipeline after a schema change.

Runs the steps as subprocesses in a background thread, tracking status so the UI can
poll. Triggered by the 'Re-ingest' button after the metamodel is edited (a schema change
invalidates the extracted graph). LLM steps use the `openrouter` backend; the server's
environment (keys, ArcadeDB password, PYTHONPATH) is inherited.

Note: the figure (vision) step is skipped here — the OpenAI-compatible path is text-only;
re-run `eawiki.figures` separately with a vision-capable setup if diagrams changed.
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
import threading
import time

_STATUS: dict = {"running": False, "done": False, "error": None, "steps": [], "started": None}

# Per-item outputs that parse/pages WRITE but never clean up. Clearing them before a
# rebuild keeps the projection consistent: parse regenerates a block file only for each
# .docx still in docs/samples/, and pages regenerates a page only for each current
# subject — so a removed document's blocks and wiki page disappear instead of lingering.
_CLEAN_GLOBS = ("data/blocks/*.blocks.json", "data/pages/*.md")


def _clean_derived() -> None:
    for pat in _CLEAN_GLOBS:
        for f in glob.glob(pat):
            try:
                os.remove(f)
            except OSError:
                pass

STEPS = [
    ("parse",     [sys.executable, "-m", "eawiki.parse"]),
    ("tables",    [sys.executable, "-m", "eawiki.tables", "--backend", "openrouter"]),
    ("subjects",  [sys.executable, "-m", "eawiki.subjects", "--backend", "openrouter"]),
    ("pages",     [sys.executable, "-m", "eawiki.pages", "--backend", "openrouter", "--workers", "8"]),
    ("reconcile", [sys.executable, "-m", "eawiki.reconcile"]),
    ("describe",  [sys.executable, "-m", "eawiki.describe", "--backend", "openrouter"]),
    ("embed",     [sys.executable, "-m", "eawiki.embed", "--backend", "openrouter"]),
    ("load",      [sys.executable, "-m", "eawiki.load"]),
    # Steps 7-9 (PIPELINE.md): the community layer. Needs the graph already in ArcadeDB
    # (community projects Community vertices onto it), hence after `load`.
    ("community", [sys.executable, "-m", "eawiki.community"]),
    ("summaries", [sys.executable, "-m", "eawiki.summaries", "--backend", "openrouter",
                   "--min-size", "3", "--workers", "6"]),
    # Step 9 (landscape pages, one per community of >= 4 members) is deliberately not run: it
    # only feeds the Map view's optional page list, and costs one long generation per
    # community. To bring it back, add:
    #   ("landscape", [sys.executable, "-m", "eawiki.landscape", "--backend", "openrouter",
    #                  "--workers", "6"]),
]


def _note(name: str, out: str) -> str:
    """One line the UI shows next to a step: how much came from cache."""
    lines = (out or "").splitlines()
    for line in reversed(lines):
        if line.startswith("cache:"):
            return line[len("cache:"):].strip()
    if name == "parse":
        docs = [l for l in lines if " blocks " in l and "->" in l]
        if docs:
            return f"{sum('(cached)' in l for l in docs)} of {len(docs)} documents from cache"
    return ""


def _log_step(name: str, ms: int, r) -> None:
    """Step output used to be captured and discarded, so a slow or failing step left no
    trace. Put the tail of it in the server log (Cloud Run logging)."""
    tail = lambda t: "\n".join((t or "").strip().splitlines()[-15:])    # noqa: E731
    print(f"[ingest] {name}: {ms / 1000:.1f}s exit {r.returncode}\n{tail(r.stdout)}"
          + (f"\n--- stderr ---\n{tail(r.stderr)}" if (r.stderr or "").strip() else ""), flush=True)


def status() -> dict:
    return _STATUS


def run_async() -> dict:
    if _STATUS["running"]:
        return _STATUS

    def _run():
        _STATUS.update(running=True, done=False, error=None,
                       steps=[{"step": n, "state": "pending"} for n, _ in STEPS],
                       started=time.time())
        from eawiki import sync
        try:
            sync.push_sources()   # authoring instance: make the add/remove durable first
        except Exception as e:
            _STATUS.update(running=False, done=True, error=f"sync sources: {e}")
            return
        _clean_derived()   # start from a clean slate so removed docs leave nothing behind
        env = {**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "src")}
        for i, (name, cmd) in enumerate(STEPS):
            _STATUS["steps"][i]["state"] = "running"
            t = time.monotonic()
            r = subprocess.run(cmd, env=env, capture_output=True, text=True)
            _STATUS["steps"][i]["ms"] = int((time.monotonic() - t) * 1000)
            _STATUS["steps"][i]["note"] = _note(name, r.stdout)
            _log_step(name, _STATUS["steps"][i]["ms"], r)
            if r.returncode != 0:
                _STATUS["steps"][i]["state"] = "failed"
                _STATUS.update(running=False, done=True, error=f"{name}: {r.stderr.strip()[-300:]}")
                try:
                    sync.push_caches()   # keep the model work done so far; the next run resumes
                except Exception:
                    pass
                return
            _STATUS["steps"][i]["state"] = "ok"
        try:
            from eawiki import metamodel
            metamodel.clear_flag()
        except Exception:
            pass
        try:
            sync.push_results()   # authoring instance: publish the rebuilt KB to the bucket
        except Exception as e:
            _STATUS.update(running=False, done=True, error=f"sync results: {e}")
            return
        _STATUS.update(running=False, done=True)

    threading.Thread(target=_run, daemon=True).start()
    return _STATUS
