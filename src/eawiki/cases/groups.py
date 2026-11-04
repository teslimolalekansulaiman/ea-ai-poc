"""The groups the items of a request form, worked out in code.

A property of a stage may name other items of the request (the ones it should be combined with). Those answers are made
by a model, one item at a time, so they can disagree: A names B, and B names nobody. This does not ask a model which is right.
It treats a link in either direction as a link, joins the items that are linked into groups, picks each group's lead by an input
field (the earliest wins; an item without a usable value comes after those with one, and ties keep the order the items came in),
and says where the answers disagree, so the architect is shown it.

An item that is linked to no other is a group of one. Nothing in here knows what the items are.
"""

from __future__ import annotations

import re
from typing import Optional

ALONE = "Alone"
_ISO = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")


def _order(value) -> tuple:
    """Sortable for an ISO date (year-month-day); anything else has no order and comes after the dated."""
    m = _ISO.match(str(value or ""))
    return (0, m.group(0).strip()) if m else (1, "")


def links_from(ids: list, texts: dict) -> dict:
    """{id: [the other ids its text names]}: the answers are free text that name items by their ids."""
    if not ids:
        return {}
    pat = re.compile("|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True)))
    return {i: [x for x in dict.fromkeys(pat.findall(texts.get(i) or "")) if x != i] for i in ids}


def of_stage(stage: dict, rows: list, held: dict) -> list[dict]:
    """The groups the stage's derived property forms, from the cells {(item id, property): cell}: [] when the stage derives none."""
    col = next((c for c in stage["output"]["columns"] if c.get("derive")), None)
    if col is None:
        return []
    d = col["derive"]
    ids = [r["_id"] for r in rows]
    texts = {}
    for i in ids:
        c = held.get((i, d["from"]))
        v = c["value"] if c and c["status"] in ("answered", "user") else ""
        texts[i] = "; ".join(map(str, v)) if isinstance(v, list) else str(v or "")
    return form(ids, links_from(ids, texts), {r["_id"]: r.get(d["lead_by"]) for r in rows} if d.get("lead_by") else None)


def form(ids: list, links: dict, lead_by: Optional[dict] = None) -> list[dict]:
    """[{lead, members, disagree}] for every group of two or more. `ids` is the order the items came in; `links` is {id: [ids it names]};
    `lead_by` is {id: the value the lead is chosen by}. Ids that are not in `ids` are ignored, and so is an item naming itself."""
    pos = {i: n for n, i in enumerate(ids)}
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    asked = set()
    for a in ids:
        for b in links.get(a) or []:
            if b in pos and b != a:
                asked.add((a, b))
                parent[find(a)] = find(b)
    comps: dict = {}
    for i in ids:
        comps.setdefault(find(i), []).append(i)
    out = []
    for members in comps.values():
        if len(members) < 2:
            continue
        lead = min(members, key=lambda i: (_order((lead_by or {}).get(i)), pos[i]))
        out.append({"lead": lead, "members": [lead] + [m for m in members if m != lead],
                    "disagree": sorted((a, b) for a, b in asked if find(a) == find(members[0]) and (b, a) not in asked)})
    out.sort(key=lambda g: min(pos[m] for m in g["members"]))
    return out


def describe(groups: list[dict], item_id: str) -> str:
    """What one item reads: "Alone", or "Combined with D-3; lead: D-1", with a note where the answers did not agree."""
    for g in groups:
        if item_id in g["members"]:
            others = [m for m in g["members"] if m != item_id]
            text = "Combined with " + ", ".join(others) + "; lead: " + g["lead"]
            gone = [f"{a} named {b} but {b} did not name {a}" for a, b in g["disagree"] if item_id in (a, b)]
            return text + (" (" + "; ".join(gone) + ")" if gone else "")
    return ALONE
