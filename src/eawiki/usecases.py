"""Use-case registry — load/validate/save use-case specs as files.

A use case is a DECLARATIVE spec (data, not code) authored from the UI: name,
description, input fields, a validation gate (intake questions), and ordered stages,
each with instructions + output columns (the table). It does NOT declare data sources —
the executor picks those automatically at query time. One file per use case
(use_cases/<id>.json) = system of record; CRUD is add/overwrite/remove a file.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DIR = Path("use_cases")
COLUMN_TYPES = {"text", "textarea", "list", "enum", "citations", "bool", "number"}
# A column or input field may carry a free-text description: what the property means and how
# to resolve it. It is written by the EA team and read by the model, so it is bounded.
MAX_DESCRIPTION = 1500


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "use-case"


def validate(spec: dict) -> list[str]:
    """Return a list of human-readable errors (empty = valid)."""
    errs: list[str] = []
    if not (spec.get("name") or "").strip():
        errs.append("Name is required.")
    stages = spec.get("stages") or []
    if not stages:
        errs.append("At least one stage is required.")
    for i, s in enumerate(stages, 1):
        if not (s.get("name") or "").strip():
            errs.append(f"Stage {i}: name is required.")
        cols = ((s.get("output") or {}).get("columns")) or []
        if not cols:
            errs.append(f"Stage {i}: at least one output column is required.")
        for c in cols:
            if c.get("type") not in COLUMN_TYPES:
                errs.append(f"Stage {i}: column '{c.get('name','?')}' has invalid type '{c.get('type')}'.")
            if c.get("type") == "enum" and not (c.get("values") or []):
                errs.append(f"Stage {i}: enum column '{c.get('name','?')}' needs at least one value.")
    for f in (spec.get("input") or {}).get("item_fields") or []:
        errs += _description_errors(f"Input field '{f.get('name', '?')}'", f)
    for i, s in enumerate(stages, 1):
        for c in ((s.get("output") or {}).get("columns")) or []:
            errs += _description_errors(f"Stage {i}: column '{c.get('name', '?')}'", c)
    v = spec.get("validation") or {}
    if v.get("enabled") and not (v.get("questions") or []):
        errs.append("Validation is enabled but has no intake questions.")
    return errs


def _description_errors(where: str, item: dict) -> list[str]:
    d = item.get("description")
    if d is None:
        return []
    if not isinstance(d, str):
        return [f"{where}: description must be text."]
    if len(d.strip()) > MAX_DESCRIPTION:
        return [f"{where}: description is longer than {MAX_DESCRIPTION} characters."]
    return []


def _tidy_descriptions(spec: dict) -> None:
    """Trim descriptions and drop empty ones, so a blank box in the form leaves no key behind."""
    items = list((spec.get("input") or {}).get("item_fields") or [])
    for s in spec.get("stages") or []:
        items += list((s.get("output") or {}).get("columns") or [])
    for it in items:
        d = (it.get("description") or "").strip()
        if d:
            it["description"] = d
        else:
            it.pop("description", None)


def list_specs() -> list[dict]:
    if not DIR.exists():
        return []
    out = []
    for fp in sorted(DIR.glob("*.json")):
        try:
            out.append(json.loads(fp.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def get(uc_id: str) -> Optional[dict]:
    fp = DIR / f"{uc_id}.json"
    return json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else None


def save(spec: dict, uc_id: Optional[str] = None) -> dict:
    """Validate and write. Returns the stored spec. Raises ValueError on invalid."""
    errs = validate(spec)
    if errs:
        raise ValueError("; ".join(errs))
    spec = json.loads(json.dumps(spec))      # copy, so tidying never edits the caller's object
    _tidy_descriptions(spec)
    spec["id"] = uc_id or spec.get("id") or _slug(spec["name"])
    spec.setdefault("enabled", True)
    spec["version"] = int(spec.get("version", 0)) + 1
    spec["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{spec['id']}.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    return spec


def delete(uc_id: str) -> bool:
    fp = DIR / f"{uc_id}.json"
    if fp.exists():
        fp.unlink()
        return True
    return False
