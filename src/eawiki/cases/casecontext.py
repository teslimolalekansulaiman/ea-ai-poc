"""The context a follow-up question on a case is asked in.

A follow-up is the architect asking about a case that has run: why was this recommended, who owns that, what is the contract for the
system the second demand names. It is answered by the same pipeline as a question on the wiki (retrieval from the documents, the graph
and the wiki pages), with this text added in front of what was retrieved, so the answer can rest on what the case decided and on the
documents, and say which is which.

The text holds everything the case knows, in the order a person would read it:

  THE REQUEST          each demand as it was registered, every field
  <each stage>         what was decided for each demand, property by property, with what is still open; what was written once for
                       the whole request; and the first check's verdict
  THE DRAFTS           each draft as it stands now (the architect's own words where they edited it), and where it is in review
  OPEN QUESTIONS       what the case is still waiting on, and from whom

Every stage is in it. When the whole is too long, the values are shortened, all of them by the same step, and never a stage dropped: a
tail that is simply cut would lose the last phase, which is the one most follow-ups are about. Nothing here is computed by a model.
"""

from __future__ import annotations

from typing import Optional

from eawiki.cases.document import OPEN
from eawiki.cases.engine import phase_id

LIMIT = 24000
CAPS = (900, 500, 300, 160, 90)          # the longest a single value may be, tried in turn until the whole fits


def _one_line(v, cap: int) -> str:
    t = "; ".join(str(x) for x in v) if isinstance(v, list) else ("" if v is None else str(v))
    t = " ".join(t.split())
    return t if len(t) <= cap else t[: cap - 1].rstrip() + "…"


def digest(ctx: str, n: int = 1800) -> str:
    """The request part of the context (what it is about), for reading a short question against: everything before the first stage."""
    head = ctx.split("\n## ", 1)[0]
    return head if len(head) <= n else head[:n].rstrip() + "…"


def _request(case: dict, cap: int) -> list[str]:
    spec = case["spec"]
    inp = spec.get("input") or {}
    fields = [f for f in inp.get("item_fields") or [] if isinstance(f, dict) and f.get("name")]
    title_field = inp.get("title_field") or "title"
    out = [f"# THE REQUEST: {case.get('name') or ''} ({len(case['items'])} {'item' if len(case['items']) == 1 else 'items'})"]
    for it in case["items"]:
        out.append(f"### {it['_id']} · {_one_line(it.get(title_field) or '', cap)}")
        shown = {title_field}
        for f in fields:
            if f["name"] in shown:
                continue
            v = it.get(f["name"])
            if v not in (None, "", []):
                out.append(f"- {f.get('label') or f['name']}: {_one_line(v, cap)}")
            shown.add(f["name"])
        for k, v in it.items():                                        # a field the sheet had that the use case does not declare
            if k not in shown and not k.startswith("_") and v not in (None, "", []):
                out.append(f"- {k}: {_one_line(v, cap)}")
    return out


def _stage(case: dict, stage: dict, by: dict, request: dict, gate: Optional[str], cap: int) -> list[str]:
    pid = phase_id(stage)
    title_field = (case["spec"].get("input") or {}).get("title_field") or "title"
    out = [f"## STAGE: {stage.get('name')}"]
    for it in case["items"]:
        cs = by.get((pid, it["_id"]))
        if not cs:
            continue
        out.append(f"### {it['_id']} · {_one_line(it.get(title_field) or '', cap)}")
        for col, cell in cs.items():
            v = _one_line(cell.get("value"), cap)
            tag = ""
            if col == gate:
                tag = " (the first check)"
            elif cell.get("status") in OPEN:
                tag = f" [{cell['status']}]"
            need = f"  [needs: {_one_line(cell['need'], cap)}]" if cell.get("need") else ""
            out.append(f"- {col}{tag}: {v or '(not decided)'}{need}")
    if request:
        out.append("### Written once for the whole request")
        for col, cell in request.items():
            out.append(f"- {col}: {_one_line(cell.get('value'), cap) or '(not written)'}")
    return out


def _drafts(drafts: dict, cap: int) -> list[str]:
    out = []
    for stage_name, entries in drafts.items():
        for e in entries:
            d = e.get("doc") or {}
            status = e.get("status") or "draft"
            out.append(f"## DRAFT ({stage_name}): {d.get('title') or e.get('item_id')} [{status}{', edited by the architect' if e.get('edited') else ''}]")
            if e.get("note"):
                out.append(f"Returned with this note: {_one_line(e['note'], cap)}")
            rec = d.get("rec") or {}
            if rec.get("body"):
                out.append(f"{rec.get('title') or 'Recommendation'}: {_one_line(rec['body'], cap * 2)}")
            for s in d.get("sections") or []:
                if s.get("body"):
                    out.append(f"- {_one_line(s.get('title'), 120)}: {_one_line(s['body'], cap * 2)}")
    return out


def _questions(questions: list, cap: int) -> list[str]:
    out = []
    for q in questions:
        if q.get("status") != "open":
            continue
        who = q.get("item_id") or ""
        out.append(f"- {who + ' · ' if who and who != '_request' else ''}{q.get('column') or ''}: {_one_line(q.get('text') or '', cap)}")
    return out


def build(case: dict, cells: list[dict], request_cells: Optional[dict] = None, drafts: Optional[dict] = None, questions: Optional[list] = None,
          focus: Optional[str] = None, limit: int = LIMIT) -> str:
    """The case as plain text. `request_cells` is {phase id: {property: cell}}, `drafts` is {stage name: [document entries]}."""
    from eawiki.cases.engine import gate_column
    spec = case["spec"]
    gate = gate_column(spec)
    by: dict = {}
    for c in cells:
        by.setdefault((c["phase_id"], c["item_id"]), {})[c["column"]] = c
    blocks: list[list[str]] = []
    for n, cap in enumerate(CAPS):
        blocks = []
        head = []
        if focus and any(i["_id"] == focus for i in case["items"]):
            head.append(f"The architect has {focus} open: a question without a demand number is about it.")
        blocks.append(head + _request(case, cap))
        for stage in spec["stages"]:
            blocks.append(_stage(case, stage, by, (request_cells or {}).get(phase_id(stage)) or {}, gate, cap))
        d = _drafts(drafts or {}, cap)
        if d:
            blocks.append(["# THE DRAFTS, as they stand"] + d)
        q = _questions(questions or [], cap)
        if q:
            blocks.append(["# OPEN QUESTIONS (the case is waiting on these)"] + q)
        text = "\n".join(ln for b in blocks for ln in b)
        if len(text) <= limit:
            return text
    return _share(blocks, limit)


def _share(blocks: list[list[str]], limit: int) -> str:
    """Still too long with every value at its shortest: each part (the request, each stage, the drafts) keeps an equal share of what fits,
    or all of itself if it is smaller, and says how many lines it lost. No part is dropped, and none takes the room of the others."""
    sizes = [sum(len(ln) + 1 for ln in b) for b in blocks]
    room, left = limit, len(blocks)
    out = []
    for i in sorted(range(len(blocks)), key=lambda k: sizes[k]):
        share = room // left
        keep, used = [], 0
        for ln in blocks[i]:
            if used + len(ln) + 1 > share - 60 and keep:
                break
            keep.append(ln)
            used += len(ln) + 1
        if len(keep) < len(blocks[i]):
            keep.append(f"[… {len(blocks[i]) - len(keep)} more lines cut: ask about one demand at a time]")
            used += 70
        out.append((i, keep))
        room -= min(used, share)
        left -= 1
    return "\n".join(ln for _, keep in sorted(out) for ln in keep)
