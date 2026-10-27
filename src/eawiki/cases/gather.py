"""Run a property's lookups for one item and return labelled evidence.

A lookup says what to find, starting from which mentions of the demand (see profile), in which kinds
of source, and how to match. The runner searches the mentions ONE AT A TIME, so "HR system" and
"payroll" are each looked up on their own instead of both being lost in the demand's whole text, and
it says outright when a mention matched nothing ("no passage names it"), so "looked and found
nothing" is never confused with "did not look".

Every piece of evidence carries an id the answer may cite, and `allowed` is the set of those ids:
the check that a cited source is real is done against it, in code.

  demand:<field>   one of the item's own fields
  demand:<item id> another item of the sheet
  <block id>       a passage of an ingested document

Named documents are a preference, not a filter: a search of the named kinds comes first and a short
search of everything follows, so a document added later is still found.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional

from eawiki.cases import compare
from eawiki.usecases import PROFILE_GROUPS, RESULT_PREFIX

BLOCK_CHARS = 1100          # a table row or paragraph is read whole, not cut to a sentence
MAX_BLOCKS = 14
MAX_MENTIONS = 6            # mentions searched per lookup
PER_MENTION = 3             # passages kept per mention
GLOBAL_EXTRA = 2            # passages of ANY document added after the named kinds
MAX_OTHERS = 6
HEAD_CHARS = 80             # an entry's name is at the start of its passage


@dataclass
class Tools:
    search: Callable[[str, int, Optional[list]], list]          # (query, k, docs) -> blocks
    blocks_by_ids: Callable[[list], list]
    link: Callable[[str], Optional[dict]]                       # item text -> linked entities
    graph_facts: Callable[[list], dict]                         # entity ids -> {facts, block_ids}
    llm_json: Callable[[str], Optional[dict]]
    doc_ids: Callable[[], list]
    llm_text: Optional[Callable[[str], str]] = None             # the model's plain-text answer, for the comparison of demands


def names_from_result(value) -> list[str]:
    """The names inside an earlier property's answer: 'HR system (Peoplex, C-204); payroll' -> HR system, C-204, payroll."""
    vals = value if isinstance(value, list) else re.split(r"[;\n]", str(value or ""))
    out = []
    for v in vals:
        v = str(v).strip()
        if not v or v.casefold() in ("none", "no link found", "not identified", "not in data", "not assessed", "not stated", "not applicable") or v.startswith("(unknown"):
            continue
        head = re.sub(r"\s*\(.*?\)", "", v).strip()
        out += [x for x in [head] + re.findall(r"\b[A-Z]{1,3}-\d+\b", v) if x]
    return list(dict.fromkeys(out))


def item_text(spec: dict, item: dict) -> str:
    from eawiki.query import executor
    return executor._item_text(spec, item)


def labelled_fields(spec: dict, item: dict) -> dict:
    out = {}
    for f in (spec.get("input") or {}).get("item_fields") or []:
        v = str(item.get(f["name"]) or "").strip()
        if v:
            out[f["name"]] = (f.get("label") or f["name"], v)
    return out


def _toks(s: str) -> set:
    return set(re.findall(r"[^\W_]{3,}", str(s or "").casefold()))


def _fill(template: str, item: dict, text: str) -> str:
    d = defaultdict(str, {k: str(v) for k, v in item.items() if not str(k).startswith("_")})
    d["__text__"] = text
    try:
        return template.format_map(d)
    except Exception:
        return text


def with_hint(plan: dict, hint: dict) -> dict:
    """The plan for one cell when the architect said where to look: their document (if they named
    one) is searched alone, and what they wrote about where in it becomes a lookup of its own."""
    p = dict(plan)
    p["sources"] = list(dict.fromkeys(list(plan["sources"]) + ["documents"]))
    doc = hint.get("document")
    where = (hint.get("where") or "").strip()
    lks = [dict(l, docs=[doc]) if doc else dict(l) for l in plan.get("lookups") or []]
    if where:
        lks.insert(0, {"find": where, "from": "all_text", "match": "meaning", "in": [doc] if doc else [],
                       "docs": [doc] if doc else [], "extract": ""})
    p["lookups"] = lks
    if doc:
        p["documents"] = [doc]
        p["strict"] = True
    return p


def _head(text: str) -> str:
    """The start of a passage that names what it is about: its first sentence, at most HEAD_CHARS."""
    t = str(text or "").strip()
    m = re.search(r"[.!?:;\n]", t)
    return t[:min(m.start() if m else HEAD_CHARS, HEAD_CHARS)]


def _search(tools: Tools, query: str, k: int, prefer: list, strict: bool) -> list:
    """Named kinds first; then a short search of everything, so a new document is never shut out."""
    out, seen = [], set()
    for b in (tools.search(query, k, prefer) if prefer else tools.search(query, k, None)) or []:
        if b["block_id"] not in seen:
            seen.add(b["block_id"])
            out.append(b)
    if prefer and not strict:
        for b in tools.search(query, GLOBAL_EXTRA, None) or []:
            if b["block_id"] not in seen:
                seen.add(b["block_id"])
                out.append(dict(b, outside=True))
    return out


def _rank_others(spec: dict, item: dict, others: list[dict]) -> list[dict]:
    """The other items most like this one, by the words they share (the model reads only these)."""
    mine = _toks(item_text(spec, item))
    scored = []
    for o in others:
        t = item_text(spec, o)
        ov = len(mine & _toks(t))
        scored.append((ov, o, t))
    scored.sort(key=lambda x: -x[0])
    return [(o, t) for ov, o, t in scored[:MAX_OTHERS] if ov > 0]


def gather(tools: Tools, plan: dict, spec: dict, item: dict, others: list[dict],
           link_cache: Optional[dict] = None, hint: Optional[dict] = None, profile: Optional[dict] = None,
           decided: Optional[dict] = None, profiles: Optional[dict] = None) -> dict:
    text = item_text(spec, item)
    ev = {"demand": {}, "blocks": [], "graph": None, "others": [], "allowed": set(), "used": [], "hint": hint,
          "lookups": [], "searched": []}
    if hint:
        plan = with_hint(plan, hint)
    strict = bool(plan.get("strict"))
    if "demand" in plan["sources"]:
        for name, (label, v) in labelled_fields(spec, item).items():
            ev["demand"][name] = (label, v)
            ev["allowed"].add(f"demand:{name}")
        ev["used"].append("the demand's own fields")
    known = {b["block_id"] for b in ev["blocks"]}

    def keep(b: dict) -> None:
        if b["block_id"] not in known and len(ev["blocks"]) < MAX_BLOCKS:
            known.add(b["block_id"])
            ev["blocks"].append(b)
            ev["allowed"].add(b["block_id"])

    if "documents" in plan["sources"]:
        usable = profile if profile and profile.get("origin") == "model" else None
        for lk in plan.get("lookups") or []:
            if lk["from"] == "other_demands":
                continue
            prefer = lk.get("docs") or plan.get("documents") or []
            where = ", ".join(lk["in"]) or "any document"
            rec = {"find": lk["find"], "from": lk["from"], "match": lk["match"], "in": where, "items": []}
            if lk["from"].startswith(RESULT_PREFIX):
                ms = names_from_result((decided or {}).get(lk["from"][len(RESULT_PREFIX):], ""))[:MAX_MENTIONS]
                if not ms:
                    rec["note"] = f"{lk['from'][len(RESULT_PREFIX):]} found nothing to start from"
            elif lk["from"] in PROFILE_GROUPS and usable is not None:
                ms = [m["text"] for m in (usable.get(lk["from"]) or [])[:MAX_MENTIONS]]
                if not ms:
                    rec["note"] = f"the demand mentions no {lk['from']}"
            else:
                ms = [None]                          # one search on the demand as a whole
            for m in ms:
                q = m if m else text
                hits = _search(tools, q, PER_MENTION if m else 5, prefer, strict)
                for b in hits:
                    keep(b)
                if m and lk["match"] == "name":
                    # an entry NAMED m starts with the name (a catalog row begins with what it describes);
                    # a passage that only mentions m is about something else
                    named = [b for b in hits if _toks(m) <= _toks(_head(b.get("text", "")))]
                    said = [b for b in hits if b not in named and _toks(m) <= _toks(b.get("text", ""))]
                    rec["items"].append({"mention": m, "exact": [b["block_id"] for b in named],
                                         "mentioned": [b["block_id"] for b in said][:3],
                                         "closest": [b["block_id"] for b in hits if b not in named and b not in said][:2],
                                         "none": not named})
                else:
                    rec["items"].append({"mention": m or "the demand as a whole", "exact": [b["block_id"] for b in hits],
                                         "mentioned": [], "closest": [], "none": not hits})
            ev["lookups"].append(rec)
            for it in rec["items"]:
                ev["searched"].append(f"{rec['from']} '{it['mention']}' in {where}: " + (
                    ("found " + ", ".join(it["exact"][:2])) if not it["none"]
                    else ("no entry of its own; only mentioned in " + ", ".join(it["mentioned"][:2])) if it.get("mentioned")
                    else "no match"))
        ev["used"].append(("documents: " + ", ".join(plan["documents"])) if plan.get("documents") else "the ingested documents")
    if "graph" in plan["sources"]:
        key = item.get("_id")
        lk = link_cache.get(key) if link_cache is not None else None
        if lk is None:
            try:
                lk = tools.link(text) or {}
            except Exception:
                lk = {}
            if link_cache is not None:
                link_cache[key] = lk
        ids = [i for e in lk.get("entities", []) for i in e["ids"]][:6]
        if ids:
            g = tools.graph_facts(ids) or {}
            ev["graph"] = {"names": [n for e in lk["entities"] for n in e["names"]][:8],
                           "facts": g.get("facts", ""), "block_ids": g.get("block_ids", [])}
            extra = tools.blocks_by_ids(g.get("block_ids", [])[:6]) if g.get("block_ids") else []
            for b in extra:
                keep(b)
            ev["used"].append("the graph: " + ", ".join(ev["graph"]["names"][:4]))
    cmp_lookup = next((l for l in plan.get("lookups") or [] if l["from"] == "other_demands" and l["match"] == "compare"), None)
    if cmp_lookup and tools.llm_text:
        # Compared one by one with the demands most like this one (see compare.py); the plain list of similar demands is not shown.
        cache = link_cache if link_cache is not None else {}
        text_of = lambda o: item_text(spec, o)                                                      # noqa: E731
        sheet = [item] + list(others)
        key = ("compare-sets", tuple(sorted(str(o.get("_id")) for o in sheet)))
        if key not in cache:
            cache[key] = compare.candidate_sets(sheet, text_of, profiles)
        res = compare.run(cmp_lookup["find"], item.get("_id"), text, (profiles or {}).get(item.get("_id")), list(others), text_of, profiles,
                          tools.llm_text, cands=cache[key].get(item.get("_id")))
        title = {o.get("_id"): str(o.get("title") or "") for o in others}
        ev["compared"] = {"question": cmp_lookup["find"], "status": res["status"],
                          "items": [dict(i, title=title.get(i["id"], "")) for i in res["items"]]}
        for i in res["items"]:
            ev["allowed"].add(f"demand:{i['id']}")
        if res["items"]:
            n = {v: sum(1 for i in res["items"] if i["verdict"] == v) for v in ("same", "related", "different", "unread")}
            ev["searched"].append(f"compared with {len(res['items'])} demands: {n['same']} same, {n['related']} related, {n['different']} different"
                                  + (f", {n['unread']} not compared" if n["unread"] else ""))
            ev["used"].append(f"a comparison with the {len(res['items'])} demands most like this one")
        else:
            ev["searched"].append("compared with the other demands: none shares anything with this one")
    elif "other_demands" in plan["sources"] or cmp_lookup or any(l["from"] == "other_demands" for l in plan.get("lookups") or []):
        for o, t in _rank_others(spec, item, others):
            ev["others"].append({"id": o.get("_id"), "text": t[:400]})
            ev["allowed"].add(f"demand:{o.get('_id')}")
        if ev["others"]:
            ev["used"].append(f"the {len(ev['others'])} most similar demands in the sheet")
    ev["looked"] = looked_in(ev, plan, tools)
    return ev


def looked_in(ev: dict, plan: dict, tools: Tools) -> str:
    """What was actually searched, in words the architect can read: what was looked for, the documents
    the passages came from and how many, the graph entities. Built from the results."""
    parts = []
    for rec in ev.get("lookups", []):
        n = sum(1 for i in rec["items"] if not i["none"])
        what = rec["note"] if rec.get("note") else f"{n} of {len(rec['items'])} found"
        parts.append(f"{rec['from']} in {rec['in']}: {what}")
    by_doc: dict = {}
    for b in ev["blocks"]:
        d = b.get("doc_id") or str(b.get("block_id", "")).rsplit(":", 1)[0]
        by_doc[d] = by_doc.get(d, 0) + 1
    if by_doc:
        parts.append(", ".join(f"{n} passage{'s' if n != 1 else ''} of {d}" for d, n in by_doc.items()))
    elif "documents" in plan["sources"]:
        try:
            n = len(tools.doc_ids() or [])
        except Exception:
            n = 0
        parts.append(f"all {n} ingested documents, and nothing relevant came back" if n else "the ingested documents, and nothing relevant came back")
    if ev.get("graph") and ev["graph"].get("names"):
        parts.append("the graph (" + ", ".join(ev["graph"]["names"][:4]) + ")")
    if ev.get("compared"):
        c = ev["compared"]
        parts.append(f"compared with {len(c['items'])} other demands" if c["items"] else "no other demand shares anything with this one")
    if ev["others"]:
        parts.append(f"the {len(ev['others'])} most similar of the other demands")
    if ev["demand"]:
        parts.append("the demand's own fields")
    return "; ".join(parts) or "nothing"


def render(ev: dict) -> str:
    out = []
    h = ev.get("hint")
    if h:
        out.append("THE ARCHITECT POINTED YOU HERE: " + "; ".join(
            x for x in (f"document {h['document']}" if h.get("document") else "", h.get("where") or "") if x)
            + ". Use what the source blocks below say; if they do not answer it, say so.")
    if ev["demand"]:
        out.append("DEMAND FIELDS:\n" + "\n".join(f"  [demand:{k}] {label}: {v}" for k, (label, v) in ev["demand"].items()))
    if ev.get("lookups"):
        lines = []
        for i, rec in enumerate(ev["lookups"], 1):
            lines.append(f"  {i}. Find: {rec['find']}  (from {rec['from']}, in {rec['in']})")
            if rec.get("note"):
                lines.append(f"     {rec['note']}")
            for it in rec["items"]:
                if not it["none"]:
                    lines.append(f"     \"{it['mention']}\": has an entry: " + ", ".join(f"[{b}]" for b in it["exact"][:3]))
                elif it.get("mentioned"):
                    lines.append(f"     \"{it['mention']}\": NO entry of its own. It is only mentioned inside: "
                                 + ", ".join(f"[{b}]" for b in it["mentioned"]))
                else:
                    near = (" Closest, not a confirmed match: " + ", ".join(f"[{b}]" for b in it["closest"])) if it["closest"] else ""
                    lines.append(f"     \"{it['mention']}\": NO passage names it.{near}")
        out.append("LOOKUPS (what was searched for, and what came back; the passages are below):\n" + "\n".join(lines))
    if ev["blocks"]:
        out.append("SOURCE BLOCKS:\n" + "\n".join(
            f"  [{b['block_id']}] {(b.get('text') or '')[:BLOCK_CHARS]}" for b in ev["blocks"]))
    if ev["graph"] and ev["graph"]["facts"]:
        out.append(f"GRAPH FACTS (entities: {', '.join(ev['graph']['names'])}):\n" + ev["graph"]["facts"][:3000])
    if ev.get("compared"):
        c = ev["compared"]
        if not c["items"]:
            out.append("COMPARED WITH THE OTHER DEMANDS OF THE SHEET: no other demand shares a system, a data set, a process or enough words with this one.")
        else:
            lines = []
            for i in c["items"]:
                what = (f"{i['verdict']} - {i['reason']}" if i["reason"] else i["verdict"]) if i["verdict"] != "unread" else "NOT COMPARED (the model gave no answer for it)"
                lines.append(f"  [demand:{i['id']}] {i['id']}" + (f" \"{i['title']}\"" if i.get("title") else "") + f": {what}")
            head = f"COMPARED WITH THE OTHER DEMANDS OF THE SHEET (the question: {c['question']}):"
            if c["status"] != "ok":
                head += "\n  Some of these could not be compared. Do not conclude 'no duplicate' from a demand marked NOT COMPARED."
            out.append(head + "\n" + "\n".join(lines))
    if ev["others"]:
        out.append("THE MOST SIMILAR OTHER DEMANDS IN THE SHEET:\n" + "\n".join(f"  [demand:{o['id']}] {o['text']}" for o in ev["others"]))
    return "\n\n".join(out) or "(no evidence found)"
