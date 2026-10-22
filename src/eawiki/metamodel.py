"""Metamodel registry — read/edit the node & edge types (the EA framework schema).

The schema (`data/togaf92_metamodel.json`) is TOGAF today but the shape is
framework-agnostic, so this is the seam for swapping frameworks later. EA can list,
add, edit and delete node types and edge types here. Any change:
  * is validated (edge source/target types must be real node types; no dangling refs),
  * regenerates the extraction prompt (which is derived from the schema),
  * sets a 'reingest needed' flag — because changing the schema invalidates the
    already-extracted graph, so the documents should be re-ingested.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

PATH = Path("data/togaf92_metamodel.json")
FLAG = Path("data/graph/.reingest_needed")


def _load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def _save(m: dict) -> None:
    PATH.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    FLAG.write_text("schema changed", encoding="utf-8")
    # regenerate the extraction prompt from the schema (best effort)
    try:
        subprocess.run([sys.executable, "scripts/build_extraction_prompt.py"],
                       capture_output=True, timeout=60,
                       env={**__import__("os").environ, "PYTHONPATH": "src"})
    except Exception:
        pass


def view() -> dict:
    """The schema as arrays (key included) for the UI, + the reingest flag."""
    m = _load()
    nt = m.get("node_types", {})
    et = m.get("edge_types", {})
    return {
        "framework": m.get("name", "TOGAF 9.2"),
        "node_types": [{"key": k, **v} for k, v in nt.items()],
        "edge_types": [{"key": k, **v} for k, v in et.items()],
        "reingest_needed": FLAG.exists(),
    }


def _node_keys(m: dict) -> set[str]:
    return set(m.get("node_types", {})) | {"element"}


def validate_edge(edge: dict, node_keys: set[str]) -> list[str]:
    errs = []
    for side in ("source_types", "target_types"):
        bad = [t for t in (edge.get(side) or []) if t not in node_keys and t != "*"]
        if not edge.get(side):
            errs.append(f"{side} is required")
        if bad:
            errs.append(f"{side}: unknown node type(s) {bad}")
    return errs


def upsert_node(key: str, obj: dict) -> None:
    m = _load()
    m.setdefault("node_types", {})[key] = {
        "name": obj.get("name", key), "domain": obj.get("domain", "Other"),
        "archimate_type": obj.get("archimate_type", ""), "definition": obj.get("definition", ""),
    }
    _save(m)


def delete_node(key: str) -> None:
    m = _load()
    refs = [ek for ek, e in m.get("edge_types", {}).items()
            if key in (e.get("source_types") or []) or key in (e.get("target_types") or [])]
    if refs:
        raise ValueError(f"'{key}' is used by edge type(s): {', '.join(refs)}. Edit/remove them first.")
    m.get("node_types", {}).pop(key, None)
    _save(m)


def upsert_edge(key: str, obj: dict) -> None:
    m = _load()
    errs = validate_edge(obj, _node_keys(m))
    if errs:
        raise ValueError("; ".join(errs))
    m.setdefault("edge_types", {})[key] = {
        "name": obj.get("name", key), "archimate_relationship": obj.get("archimate_relationship", ""),
        "source_types": obj["source_types"], "target_types": obj["target_types"],
        "definition": obj.get("definition", ""),
    }
    _save(m)


def delete_edge(key: str) -> None:
    m = _load()
    m.get("edge_types", {}).pop(key, None)
    _save(m)


def clear_flag() -> None:
    FLAG.unlink(missing_ok=True)
