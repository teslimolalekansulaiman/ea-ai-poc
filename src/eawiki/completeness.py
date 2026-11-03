"""Which required input fields of a demand are still empty.

Pure code: no model, and no assumption about what any field means. A use case says which of its input fields
are required; a field with no text in it is missing. The request flow (before a case exists) and the engine's gate
(when it runs) both ask this one question, so they cannot disagree about what "incomplete" is.
"""

from __future__ import annotations


def input_fields(spec: dict) -> list[dict]:
    return [f for f in (spec.get("input") or {}).get("item_fields") or [] if f.get("name")]


def is_empty(value) -> bool:
    return not str(value if value is not None else "").strip()


def missing_fields(spec: dict, item: dict) -> list[dict]:
    """[{name, label}] of the required fields with no value, in the order the use case lists them."""
    return [{"name": f["name"], "label": f.get("label") or f["name"]}
            for f in input_fields(spec) if f.get("required") and is_empty(item.get(f["name"]))]
