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

from eawiki.cases import namelookup as nl
from eawiki.usecases import PROFILE_GROUPS, RESULT_PREFIX

BLOCK_CHARS = 1100          # a table row or paragraph is read whole, not cut to a sentence
MAX_BLOCKS = 14
MAX_WIKI = 8                # wiki pages shown to the answer step
MAX_WHOLE = 8               # passages read from a short document that is read whole
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
    entities: Optional[Callable[[str, Optional[list]], dict]] = None   # name, kinds -> {candidates, other_kinds}
    page: Optional[Callable[[str], Optional[str]]] = None              # wiki page slug -> markdown
    doc_blocks: Optional[Callable[[str, int], list]] = None            # document id, limit -> its passages in order


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


KIND_FAMILY = {"application": "app", "data": "data", "technology": "tech", "security": "security", "role": "role"}


def names_from_result(value) -> list[str]:
    """The names inside an earlier property's value: 'HR system (Peoplex, C-204); payroll' -> HR system, C-204, payroll."""
    vals = value if isinstance(value, list) else re.split(r"[;\n]", str(value or ""))
    out = []
    for v in vals:
        v = str(v).strip()
        if not v or v.casefold() in ("none", "no link found", "not identified", "not in data", "not assessed", "not stated"):
            continue
        head = re.sub(r"\s*\(.*?\)", "", v).strip()
        ids = re.findall(r"\b[A-Z]{1,3}-\d+\b", v)
        out += [x for x in ([head] + ids) if x]
    return list(dict.fromkeys(out))


def _kinds_of(lk: dict) -> Optional[list]:
    return [KIND_FAMILY[t] for t in lk.get("types") or [] if t in KIND_FAMILY] or None


def _resolve(tools: Tools, m: str, lk: dict) -> dict:
    return tools.entities(m, _kinds_of(lk)) if tools.entities else {"candidates": [], "other_kinds": []}


def _name_lookup(tools: Tools, m: str, lk: dict, prefer: list, strict: bool, ent: Optional[dict] = None) -> dict:
    """One name, looked up everywhere a name can be found: entities (with their wiki page), the graph and the
    catalog passages. It reports candidates; it never picks the one the demand means."""
    ent = ent if ent is not None else _resolve(tools, m, lk)
    cands = ent.get("candidates") or []
    for i, c in enumerate(cands):
        c["digest"] = None
        if i < 3 and tools.page and c.get("slug"):
            md = tools.page(c["slug"])
            c["digest"] = nl.digest_page(md) if md else None
    facts = ""
    if cands and cands[0]["strong"] and tools.graph_facts:
        try:
            facts = (tools.graph_facts([cands[0]["id"]]) or {}).get("facts", "")[:600]
        except Exception:
            facts = ""
    hits = _search(tools, m, PER_MENTION, prefer, strict)
    # With an entity index the entity says what has a name of its own, so a passage counts as naming the
    # mention only when its first words ARE the name; without one, the mention inside the first sentence is the best signal there is.
    named = [b for b in hits if (nl.names_head(_head(b.get("text", "")), m) if tools.entities
                                 else nl.core(m) and nl.core(m) <= nl.core(_head(b.get("text", ""))))]
    said = [b for b in hits if b not in named and _toks(m) <= _toks(b.get("text", ""))]
    entry = any(c["strong"] for c in cands) or bool(named)
    return {"mention": m, "candidates": cands, "other_kinds": ent.get("other_kinds") or [], "facts": facts,
            "exact": [b["block_id"] for b in named], "mentioned": [b["block_id"] for b in said][:3],
            "closest": [b["block_id"] for b in hits if b not in named and b not in said][:2],
            "none": not entry, "ambiguous": nl.ambiguous(cands), "hits": hits}


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
           decided: Optional[dict] = None) -> dict:
    text = item_text(spec, item)
    ev = {"demand": {}, "blocks": [], "graph": None, "others": [], "allowed": set(), "used": [], "hint": hint,
          "lookups": [], "searched": [], "wiki": []}
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
            frm = lk["from"]
            if lk.get("read_all") and not lk.get("docs"):
                # a document that is read whole but is not ingested: say so, never fall back to a search of something else
                rec["note"] = "not read: no ingested document is named " + " / ".join(lk["in"] or ["(none given)"])
                rec["items"].append({"mention": "the whole document", "exact": [], "mentioned": [], "closest": [], "none": True,
                                     "candidates": [], "ambiguous": False, "other_kinds": [], "facts": ""})
                ev["lookups"].append(rec)
                ev["searched"].append(f"read-whole document {' / '.join(lk['in'])}: not ingested")
                continue
            if lk.get("read_all") and tools.doc_blocks and lk.get("docs"):
                # a short reference document (a standard, a glossary) is read whole, not searched
                got = 0
                for d in lk["docs"]:
                    for b in (tools.doc_blocks(d, MAX_WHOLE) or []):
                        keep(b)
                        got += 1
                rec["items"].append({"mention": "the whole document", "exact": [], "mentioned": [], "closest": [], "none": got == 0,
                                     "candidates": [], "ambiguous": False, "other_kinds": [], "facts": ""})
                ev["lookups"].append(rec)
                ev["searched"].append(f"read {', '.join(lk['docs'])} whole ({got} passages)")
                continue
            if frm.startswith(RESULT_PREFIX):
                ms = names_from_result((decided or {}).get(frm[len(RESULT_PREFIX):], ""))
                if not ms:
                    rec["note"] = f"{frm[len(RESULT_PREFIX):]} found nothing to start from"
            elif frm in PROFILE_GROUPS and usable is not None:
                ms = [m["text"] for m in (usable.get(frm) or [])[:2 * MAX_MENTIONS]]   # the cap applies after the known names are put first
                if not ms:
                    rec["note"] = f"the demand mentions no {frm}"
            else:
                ms = [None]                          # one search on the demand as a whole
            pre = {}
            if lk["match"] == "name" and tools.entities:
                # Names the knowledge base knows are read first: a mention it has never heard of ("spreadsheets") must
                # not use up the evidence budget before the ones that are real.
                for m in ms:
                    if m:
                        pre[m] = _resolve(tools, m, lk)
                ms = sorted(ms, key=lambda m: -max([c["score"] for c in (pre.get(m) or {}).get("candidates", [])] or [0]))
            for m in ms[:MAX_MENTIONS]:
                if m and lk["match"] == "name":
                    it = _name_lookup(tools, m, lk, prefer, strict, pre.get(m))
                    for b in it.pop("hits"):
                        keep(b)
                    for c in it["candidates"][:3]:
                        if c.get("digest") and c["slug"] not in {w["slug"] for w in ev["wiki"]} and len(ev["wiki"]) < MAX_WIKI:
                            ev["wiki"].append({"id": nl.evidence_id(c["slug"]), "slug": c["slug"], "name": c["name"], "type": c["type"],
                                               "digest": c["digest"], "how": c["how"], "matched": c["matched"]})
                            ev["allowed"].add(nl.evidence_id(c["slug"]))
                    if it["facts"]:
                        ev["graph"] = ev["graph"] or {"names": [], "facts": "", "block_ids": []}
                        ev["graph"]["names"] = list(dict.fromkeys(ev["graph"]["names"] + [it["candidates"][0]["name"]]))[:8]
                        ev["graph"]["facts"] = "\n".join(x for x in (ev["graph"]["facts"], it["facts"]) if x)[:3000]
                    rec["items"].append(it)
                else:
                    q = m if m else text
                    hits = _search(tools, q, PER_MENTION if m else 5, prefer, strict)
                    for b in hits:
                        keep(b)
                    rec["items"].append({"mention": m or "the demand as a whole", "by": "meaning" if not m else "text",
                                         "exact": [b["block_id"] for b in hits],
                                         "mentioned": [], "closest": [], "none": not hits, "candidates": [], "ambiguous": False,
                                         "other_kinds": [], "facts": ""})
            ev["lookups"].append(rec)
            for it in rec["items"]:
                strong = [c for c in it["candidates"] if c["strong"]]
                if strong:
                    what = "entry " + ", ".join(f"{c['name']} ({nl.label(c['type'])})" for c in strong[:2]) \
                           + (" [ambiguous]" if it["ambiguous"] else "")
                elif not it["none"]:
                    what = "found " + ", ".join(it["exact"][:2])
                elif [c for c in it["candidates"] if c["score"] >= nl.PARTIAL]:
                    what = "no entry of its own; closest " + ", ".join(c["name"] for c in it["candidates"][:2])
                elif it.get("mentioned"):
                    what = "no entry of its own; only mentioned in " + ", ".join(it["mentioned"][:2])
                else:
                    what = "no match"
                ev["searched"].append(f"{rec['from']} '{it['mention']}' in {where}: {what}")
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
    if "other_demands" in plan["sources"] or any(l["from"] == "other_demands" for l in plan.get("lookups") or []):
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
                cands = it.get("candidates") or []
                lab = lambda c: f"[{nl.evidence_id(c['slug'])}] {c['name']} ({nl.label(c['type'])}; {c['how']}" + (f' "{c["matched"]}"' if c.get("matched") and c["how"] in ("alias", "exact", "id") else "") + ")"
                strong = [c for c in cands if c["strong"]]
                part = [c for c in cands if not c["strong"] and c["score"] >= nl.PARTIAL]
                m = it["mention"]
                if it.get("by"):
                    lines.append(f'     "{m}": ' + (("closest passages: " + ", ".join(f"[{b}]" for b in it["exact"])) if it["exact"] else "no passage came back"))
                elif strong:
                    lines.append(f'     "{m}": HAS AN ENTRY: ' + "; ".join(lab(c) for c in strong[:2])
                                 + (("; also, less closely: " + "; ".join(lab(c) for c in part[:2])) if part else ""))
                elif not it["none"]:
                    lines.append(f'     "{m}": has an entry in the catalog: ' + ", ".join(f"[{b}]" for b in it["exact"][:3]))
                else:
                    why = ("NO entry of its own. Closest, only part of a name: " + "; ".join(lab(c) for c in part[:2])) if part else (
                          "NO entry of its own. It is only mentioned inside: " + ", ".join(f"[{b}]" for b in it["mentioned"])) if it.get("mentioned") else (
                          "NO entry and no passage names it" + ((". Closest, not a confirmed match: " + ", ".join(f"[{b}]" for b in it["closest"])) if it.get("closest") else ""))
                    lines.append(f'     "{m}": {why}')
                if it.get("ambiguous"):
                    lines.append("       AMBIGUOUS: this name fits entities of different kinds. Choose the one the demand means from its wording and say which in your note.")
                if it.get("other_kinds"):
                    lines.append("       Also exists as another kind of thing (not offered as a candidate): "
                                 + "; ".join(f"{c['name']} ({nl.label(c['type'])})" for c in it["other_kinds"]))
        out.append("LOOKUPS (what was searched for, and what came back; the passages are below):\n" + "\n".join(lines))
    if ev.get("wiki"):
        out.append("WIKI PAGES (what the knowledge base says each entity is):\n" + "\n".join(
            f"  [{w['id']}] {w['name']}. Type: {w['digest']['type'] or w['type']}. {w['digest']['summary']}"
            + (f" Related: {w['digest']['related']}" if w["digest"]["related"] else "") for w in ev["wiki"]))
    if ev["blocks"]:
        out.append("SOURCE BLOCKS:\n" + "\n".join(
            f"  [{b['block_id']}] {(b.get('text') or '')[:BLOCK_CHARS]}" for b in ev["blocks"]))
    if ev["graph"] and ev["graph"]["facts"]:
        out.append(f"GRAPH FACTS (entities: {', '.join(ev['graph']['names'])}):\n" + ev["graph"]["facts"][:3000])
    if ev["others"]:
        out.append("THE MOST SIMILAR OTHER DEMANDS IN THE SHEET:\n" + "\n".join(f"  [demand:{o['id']}] {o['text']}" for o in ev["others"]))
    return "\n\n".join(out) or "(no evidence found)"
