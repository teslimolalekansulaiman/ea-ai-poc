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
MAX_DESCRIPTION = 2500
MAX_INFO_NEEDED = 300
MAX_LOOK_IN = 10
MAX_GUIDANCE = 2500        # rules, examples and where-to-look text of one property
MAX_PLAYBOOK = 4000        # the rules that apply to every property of the use case
MAX_LOOKUPS = 6
# What a demand can mention (the profile groups) and how a lookup may use them.
PROFILE_GROUPS = ("systems", "data", "processes", "users", "mandates", "projects", "dates", "tools_today", "requested")
LOOKUP_FROM = PROFILE_GROUPS + ("need", "all_text", "other_demands")
LOOKUP_MATCH = ("name", "meaning", "compare")
MAX_ACTIVITY = 80          # the short sentence the live card shows while a property is worked


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
    pb = spec.get("playbook")
    if pb is not None and (not isinstance(pb, str) or len(pb.strip()) > MAX_PLAYBOOK):
        errs.append(f"The use case rules must be text of at most {MAX_PLAYBOOK} characters.")
    il = (spec.get("input") or {}).get("item_label")
    blank = isinstance(il, dict) and not any(isinstance(il.get(k), str) and il[k].strip() for k in ("singular", "plural"))
    if il is not None and not blank and (not isinstance(il, dict) or any(not isinstance(il.get(k), str) or not il[k].strip() or len(il[k]) > 40
                                                          for k in ("singular", "plural"))):
        errs.append("Input: the item label needs a singular and a plural word of at most 40 characters.")
    for i, s in enumerate(stages, 1):
        cols = ((s.get("output") or {}).get("columns")) or []
        names = [c.get("name") for c in cols]
        for c in cols:
            errs += _column_errors(f"Stage {i}: column '{c.get('name', '?')}'", c, names)
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


def _column_errors(where: str, c: dict, names: list[str]) -> list[str]:
    """The guidance fields of an output column: how to resolve it, where to look, whether a
    cited source is needed, what to ask for when it is missing, and what it builds on."""
    errs = _description_errors(where, c)
    h = c.get("how_to_resolve")
    if h is not None and (not isinstance(h, str) or len(h.strip()) > MAX_DESCRIPTION):
        errs.append(f"{where}: how to resolve must be text of at most {MAX_DESCRIPTION} characters.")
    n = c.get("info_needed")
    if n is not None and (not isinstance(n, str) or len(n.strip()) > MAX_INFO_NEEDED):
        errs.append(f"{where}: info needed must be text of at most {MAX_INFO_NEEDED} characters.")
    li = c.get("look_in")
    if li is not None and (not isinstance(li, list) or len(li) > MAX_LOOK_IN
                           or any(not isinstance(x, str) or len(x) > 120 for x in li)):
        errs.append(f"{where}: look in must be a list of at most {MAX_LOOK_IN} document names.")
    if c.get("evidence_required") is not None and not isinstance(c["evidence_required"], bool):
        errs.append(f"{where}: evidence required must be true or false.")
    a = c.get("activity")
    if a is not None and (not isinstance(a, str) or len(a.strip()) > MAX_ACTIVITY):
        errs.append(f"{where}: activity must be text of at most {MAX_ACTIVITY} characters.")
    for key in ("where_to_look", "rules", "examples"):
        v = c.get(key)
        if v is not None and (not isinstance(v, str) or len(v.strip()) > MAX_GUIDANCE):
            errs.append(f"{where}: {key.replace('_', ' ')} must be text of at most {MAX_GUIDANCE} characters.")
    n2 = c.get("info_needed_source")
    if n2 is not None and (not isinstance(n2, str) or len(n2.strip()) > MAX_INFO_NEEDED):
        errs.append(f"{where}: info needed (source) must be text of at most {MAX_INFO_NEEDED} characters.")
    ms = c.get("min_sources")
    if ms is not None and (isinstance(ms, bool) or not isinstance(ms, int) or not 1 <= ms <= 5):
        errs.append(f"{where}: minimum sources must be a whole number from 1 to 5.")
    errs += _lookup_errors(where, c.get("lookups"))
    uses = c.get("uses")
    if uses is not None:
        if not isinstance(uses, list):
            errs.append(f"{where}: uses must be a list of column names.")
        else:
            for u in uses:
                if u == c.get("name") or u not in names:
                    errs.append(f"{where}: uses '{u}', which is not another column of this stage.")
    return errs


def _lookup_errors(where: str, lookups) -> list[str]:
    """A property's lookups: what to find, from which mention, in which kinds of source, how to match."""
    if lookups is None:
        return []
    if not isinstance(lookups, list) or len(lookups) > MAX_LOOKUPS:
        return [f"{where}: lookups must be a list of at most {MAX_LOOKUPS}."]
    errs = []
    for i, lk in enumerate(lookups, 1):
        if not isinstance(lk, dict) or not isinstance(lk.get("find"), str) or not lk["find"].strip():
            errs.append(f"{where}: lookup {i} needs a 'find' sentence.")
            continue
        if lk.get("from") not in LOOKUP_FROM:
            errs.append(f"{where}: lookup {i}: 'from' must be one of {', '.join(LOOKUP_FROM)}.")
        if lk.get("match") not in LOOKUP_MATCH:
            errs.append(f"{where}: lookup {i}: 'match' must be one of {', '.join(LOOKUP_MATCH)}.")
        li = lk.get("in", [])
        if not isinstance(li, list) or len(li) > 8 or any(not isinstance(x, str) or len(x) > 120 for x in li):
            errs.append(f"{where}: lookup {i}: 'in' must be a list of at most 8 kinds of source.")
    return errs


def _tidy_descriptions(spec: dict) -> None:
    """Trim descriptions and drop empty ones, so a blank box in the form leaves no key behind."""
    if isinstance(spec.get("playbook"), str):
        if spec["playbook"].strip():
            spec["playbook"] = spec["playbook"].strip()
        else:
            spec.pop("playbook")
    il = (spec.get("input") or {}).get("item_label")
    if isinstance(il, dict):
        if any(isinstance(il.get(k), str) and il[k].strip() for k in ("singular", "plural")):
            spec["input"]["item_label"] = {k: il[k].strip() for k in ("singular", "plural")}
        else:
            spec["input"].pop("item_label", None)
    items = list((spec.get("input") or {}).get("item_fields") or [])
    for s in spec.get("stages") or []:
        items += list((s.get("output") or {}).get("columns") or [])
    for it in items:
        for key in ("description", "how_to_resolve", "info_needed", "info_needed_source", "activity", "where_to_look", "rules", "examples"):
            d = (it.get(key) or "").strip() if isinstance(it.get(key), str) else ""
            if d:
                it[key] = d
            else:
                it.pop(key, None)
        li = [x.strip() for x in (it.get("look_in") or []) if isinstance(x, str) and x.strip()]
        if li:
            it["look_in"] = list(dict.fromkeys(li))
        else:
            it.pop("look_in", None)
        if it.get("evidence_required") is not False:
            it.pop("evidence_required", None)          # on by default: only an explicit "no" is stored
        if not it.get("uses"):
            it.pop("uses", None)
        if not it.get("lookups"):
            it.pop("lookups", None)
        if not it.get("min_sources"):
            it.pop("min_sources", None)


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
