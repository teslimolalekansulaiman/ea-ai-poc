"""Updates shipped with the code for a use case that already lives in the database.

The file in use_cases/ only seeds a use case the database has never seen; after that the database wins, so a change to the
shipped file never reaches a use case the owner has been editing. An update carries such a change as a few steps that are
careful with the owner's own work:

  rename_property   a property keeps its answers' meaning under a new name; everything that refers to it follows
  remove_property   a property goes, and so does every reference to it
  ensure_property   a property is added when it is not there; one that is there is never touched
  fill_property     wording and settings the owner has not written are filled in; what they wrote is kept, and said so
  set_stage         the stage's own settings (how the results are shown, the summary property, the tag)
  append_text       a sentence is added to a stage's instructions, unless it is already there
  order             properties are put in an order

`plan` works on a copy and returns what would change; nothing is stored. `apply` stores it as a new version (the earlier one stays
in the history) and records the update's id on the use case, so it is offered once. Updates are data: use_cases/updates/<use case>/<id>.json.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Optional

from eawiki import usecases

APPLIED_KEY = "updates_applied"
REF_LISTS = ("uses", "sees_others")                 # a property's lists of other properties


class UpdateError(ValueError):
    """The update cannot be applied to this use case: say why."""


def _dir(uc_id: str) -> Path:
    return usecases.DIR / "updates" / uc_id


def shipped(uc_id: str) -> list[dict]:
    d = _dir(uc_id)
    out = []
    for fp in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            u = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(u, dict) and u.get("id") and isinstance(u.get("ops"), list):
            out.append(u)
    return out


def _stage(spec: dict, name: str) -> dict:
    st = next((s for s in spec.get("stages") or [] if s.get("name") == name), None)
    if st is None:
        raise UpdateError(f"There is no stage named '{name}'. The stages are: " + ", ".join(repr(s.get("name")) for s in spec.get("stages") or []) + ".")
    return st


def _cols(stage: dict) -> list:
    return stage["output"]["columns"]


def _find(stage: dict, name: str) -> Optional[dict]:
    return next((c for c in _cols(stage) if c.get("name") == name), None)


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _replace_refs(spec: dict, stage: dict, old: str, new: Optional[str]) -> None:
    """Everything that names the property `old` follows it to `new`, or loses it when `new` is None."""
    def swap(lst):
        out = [new if x == old else x for x in lst]
        return [x for x in dict.fromkeys(out) if x is not None]
    for s in spec["stages"]:
        same = s is stage
        for c in _cols(s):
            for key in REF_LISTS:
                if isinstance(c.get(key), list) and old in c[key] and (same or key == "sees_others"):
                    c[key] = swap(c[key])
                    if not c[key]:
                        c.pop(key)
            for lk in c.get("lookups") or []:
                if new is not None and isinstance(lk, dict) and lk.get("from") == f"{usecases.RESULT_PREFIX}{old}":
                    lk["from"] = f"{usecases.RESULT_PREFIX}{new}"        # a removed property a lookup starts from is left for the checks to report
    if isinstance(stage.get("summary_columns"), list):
        stage["summary_columns"] = swap(stage["summary_columns"])
    res = stage.get("result")
    if isinstance(res, dict) and res.get("row_tag") == old:
        if new is None:
            res.pop("row_tag")
        else:
            res["row_tag"] = new
    doc = (stage.get("output") or {}).get("document")
    if isinstance(doc, dict):
        if doc.get("statement") == old:
            if new is None:
                doc.pop("statement")
            else:
                doc["statement"] = new
        for key in ("facts", "internal"):
            if isinstance(doc.get(key), list) and old in doc[key]:
                doc[key] = swap(doc[key])


def _set_path(obj: dict, path: str, value) -> bool:
    """Set a dotted path; True when it changed."""
    keys = path.split(".")
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    if obj.get(keys[-1]) == value:
        return False
    obj[keys[-1]] = copy.deepcopy(value)
    return True


def plan(spec: dict, update: dict) -> dict:
    """{spec, changes, kept, errors}: the use case as it would become, what changes, what of the owner's was left as it is."""
    new = copy.deepcopy(spec)
    changes, kept, errors = [], [], []
    try:
        for op in update["ops"]:
            kind, stage = op.get("op"), _stage(new, op.get("stage", ""))
            sn = stage.get("name")
            if kind == "rename_property":
                old, to = op["from"], op["to"]
                c = _find(stage, old)
                if c is not None and _find(stage, to) is None:
                    c["name"] = to
                    _replace_refs(new, stage, old, to)
                    changes.append(f"{sn}: the property '{old}' is renamed '{to}'; what refers to it follows.")
            elif kind == "remove_property":
                c = _find(stage, op["name"])
                if c is not None:
                    _cols(stage).remove(c)
                    _replace_refs(new, stage, op["name"], None)
                    changes.append(f"{sn}: the property '{op['name']}' is removed.")
            elif kind == "ensure_property":
                prop = op["property"]
                if _find(stage, prop["name"]) is None:
                    cols = _cols(stage)
                    at = next((i for i, c in enumerate(cols) if c.get("name") == op.get("after")), None)
                    cols.insert(len(cols) if at is None else at + 1, copy.deepcopy(prop))
                    changes.append(f"{sn}: the property '{prop['name']}' is added.")
            elif kind == "fill_property":
                c = _find(stage, op["name"])
                if c is None:
                    errors.append(f"{sn}: there is no property '{op['name']}' to fill in.")
                    continue
                for k, v in op["fields"].items():
                    if _empty(c.get(k)):
                        c[k] = copy.deepcopy(v)
                        changes.append(f"{sn}: '{op['name']}': {k.replace('_', ' ')} was empty and is filled in.")
                    elif c.get(k) != v:
                        kept.append(f"{sn}: '{op['name']}': your {k.replace('_', ' ')} is kept as it is.")
            elif kind == "set_stage":
                for path, v in op["fields"].items():
                    if _set_path(stage, path, v):
                        changes.append(f"{sn}: {path.replace('_', ' ').replace('.', ' / ')} is set.")
            elif kind == "append_text":
                cur = (stage.get(op["field"]) or "").strip()
                if op["contains"] not in cur:
                    stage[op["field"]] = (cur + "\n\n" if cur else "") + op["text"]
                    changes.append(f"{sn}: a sentence is added to the {op['field']}.")
            elif kind == "order":
                cols = _cols(stage)
                head = [c for n in op["names"] for c in cols if c.get("name") == n]
                rest = [c for c in cols if c not in head]
                if [c.get("name") for c in cols] != [c.get("name") for c in head + rest]:
                    stage["output"]["columns"] = head + rest
                    changes.append(f"{sn}: the properties are put in order.")
            else:
                errors.append(f"Unknown step '{kind}'.")
    except UpdateError as e:
        errors.append(str(e))
    except KeyError as e:
        errors.append(f"A step is missing {e}.")
    if not errors:
        errors += usecases.validate(new, usecases.relation_names())
    return {"spec": new, "changes": changes, "kept": list(dict.fromkeys(kept)), "errors": errors}


def available(uc_id: str) -> list[dict]:
    """Each update shipped for the use case: its title, whether it has been applied, and for one not yet applied what it would do."""
    spec = usecases.get(uc_id)
    if spec is None:
        raise LookupError(f"no use case '{uc_id}'")
    done = spec.get(APPLIED_KEY) or []
    out = []
    for u in shipped(uc_id):
        entry = {"id": u["id"], "title": u.get("title") or u["id"], "note": u.get("note") or "", "applied": u["id"] in done,
                 "changes": [], "kept": [], "errors": []}
        if not entry["applied"]:
            p = plan(spec, u)
            entry.update(changes=p["changes"], kept=p["kept"], errors=p["errors"])
        out.append(entry)
    return out


def apply(uc_id: str, update_id: str) -> dict:
    """Store the update as a new version of the use case, as it is stored now. Nothing is stored when it cannot be applied."""
    spec = usecases.get(uc_id)
    if spec is None:
        raise LookupError(f"no use case '{uc_id}'")
    u = next((x for x in shipped(uc_id) if x["id"] == update_id), None)
    if u is None:
        raise LookupError(f"no update '{update_id}' for '{uc_id}'")
    if update_id in (spec.get(APPLIED_KEY) or []):
        raise UpdateError("This update was already applied.")
    p = plan(spec, u)
    if p["errors"]:
        raise UpdateError("It cannot be applied: " + " ".join(p["errors"]))
    new = p["spec"]
    new[APPLIED_KEY] = [*(spec.get(APPLIED_KEY) or []), update_id]
    saved = usecases.save(new, uc_id, note=f"update: {u.get('title') or update_id}")
    return {"changes": p["changes"], "kept": p["kept"], "version": saved.get("version")}
