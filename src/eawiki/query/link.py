"""Link a question to the graph's own words.

A person writes "Oracle Database"; the documents say "Oracle DB". String matching cannot join them,
and a catalogue of bare names gives the model nothing to choose between near-identical names (it
copied the one that matched exactly, an entity with no links). So, for a structural question:

  1. the entity / relationship vector index SHORTLISTS candidates (the vector only proposes);
  2. one model call is shown the shortlist with each entity's type and number of links, and the
     relation vocabulary, and returns the question rewritten in the graph's wording plus the entity
     ids it means. It never writes a query and never invents an entity: every id is checked against
     the shortlist in code;
  3. whether the reading is uncertain is decided HERE, from facts, never from a model's own
     confidence: it listed alternatives, or a chosen entity has no links, or one mention spans
     entities of different types. An uncertain reading is shown prominently so the user can correct it.

The rewritten text is only for lookup. The user's own question is what the answer addresses.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from contextlib import contextmanager
from typing import Callable, Optional

from eawiki.query import graphquery as gq

MAX_CANDIDATES = 40
_cache: "OrderedDict[str, dict]" = OrderedDict()


def _degree(g: "gq._Graph", nid: str) -> int:
    return len(g.out.get(nid, [])) + len(g.inc.get(nid, []))


def _lexical(question: str, g: "gq._Graph", limit: int = 12) -> list[str]:
    """Entities whose whole name appears in the question, and entities sharing a rare word with it
    (a word found in at most 6 names), so an exact mention is never lost to the vector ranking."""
    q = question.lower()
    whole = [nid for nid, n in g.by_id.items()
             if len(n.get("name", "")) >= 3 and n["name"].lower() in q]
    toks = {t for t in re.findall(r"[^\W_]{3,}", q)}
    by_tok: dict[str, list[str]] = {}
    for nid, n in g.by_id.items():
        for t in set(re.findall(r"[^\W_]{3,}", n.get("name", "").lower())) & toks:
            by_tok.setdefault(t, []).append(nid)
    rare = [nid for t, ids in by_tok.items() if len(ids) <= 6 for nid in ids]
    return list(dict.fromkeys(whole + rare))[:limit]


def candidates(question: str, g: "gq._Graph", index, qvec) -> tuple[list[str], list[tuple]]:
    """Shortlist entity ids (and the closest relationships, as hints). With no index (an older KB)
    every entity that has a link is offered, which still works at this size."""
    if index is None or qvec is None:
        ids = [nid for nid in g.by_id if _degree(g, nid)]
        return ids[:1500], []
    near = [nid for nid, _ in index.nearest_nodes(qvec, 25)]
    edges = [k for k, _ in index.nearest_edges(qvec, 10)]
    ends = [x for (s, _r, t) in edges for x in (s, t)]
    ids = list(dict.fromkeys(_lexical(question, g) + near + ends))
    return [i for i in ids if i in g.by_id][:MAX_CANDIDATES], edges


def _prompt(question: str, g: "gq._Graph", ids: list[str], edge_hints: list[tuple]) -> str:
    rels = sorted({e.get("relation", "") for e in g.edges if e.get("relation")})
    lines = []
    for nid in ids:
        n = g.by_id[nid]
        al = [a for a in (n.get("aliases") or []) if a != n.get("name")][:3]
        lines.append(f"{nid} | {n.get('name', '')} | {n.get('type', '')} | {_degree(g, nid)} links"
                     + (f" | also: {'; '.join(al)}" if al else ""))
    hints = [f"{g.name(s)} --{r}--> {g.name(t)}" for (s, r, t) in edge_hints if s in g.by_id and t in g.by_id]
    return f"""You help an enterprise-architecture assistant understand a question in the graph's own words. Output ONE JSON object, nothing else.

Rewrite the question using the exact entity names and relation words below, so a lookup can find them. Keep the meaning and the shape of the question; do not answer it and do not add facts. Choose, by id, every candidate the question refers to. A product and its versions or variants (for example "Oracle DB" and "Oracle Database 11") are all meant when the question is about the product. Prefer a candidate that has links over one that has none. Choose only from the candidates; if none fits a mention, leave it out.

RELATIONS: {', '.join(rels)}

CANDIDATES (id | name | type | links):
{chr(10).join(lines)}

RELATED FACTS (for context):
{chr(10).join(hints) if hints else '(none)'}

Question: {question}

JSON: {{"rewritten": "<the question in the graph's wording>", "entities": [{{"mention": "<words in the question>", "ids": ["<candidate id>", ...], "why": "<short reason>"}}], "considered_but_rejected": [{{"id": "<candidate id>", "why": "<short reason>"}}]}}"""


def link(question: str, backend: str = "cli", model=None, *, graph: Optional["gq._Graph"] = None,
         index=None, embed: Optional[Callable[[str], list]] = None,
         llm: Callable = None) -> Optional[dict]:
    """Return {rewritten, original, entities[], considered[], flags[], uncertain, note, map} or None
    when nothing could be linked (the caller then continues exactly as before)."""
    g = graph or gq._load()
    llm = llm or gq.llm_json
    if index is None:
        try:
            from eawiki.entity_index import load_index
            index = load_index()
        except Exception:
            index = None
    qvec = None
    if index is not None and embed is not None:
        try:
            qvec = embed(question)
        except Exception:
            qvec = None
    ids, edge_hints = candidates(question, g, index, qvec)
    if not ids:
        return None
    ck = hashlib.sha1(json.dumps([question, ids, str(model)]).encode()).hexdigest()
    if ck in _cache:
        return _cache[ck]
    try:
        out = llm(_prompt(question, g, ids, edge_hints), backend, model)
    except Exception:
        return None
    res = _validate(out, question, g, set(ids))
    if res is not None:
        _cache[ck] = res
        while len(_cache) > 256:
            _cache.popitem(last=False)
    return res


def _validate(out, question: str, g: "gq._Graph", allowed: set) -> Optional[dict]:
    if not isinstance(out, dict):
        return None
    rewritten = out.get("rewritten")
    rewritten = rewritten.strip() if isinstance(rewritten, str) and rewritten.strip() else question
    entities, chosen = [], []
    for e in out.get("entities") or []:
        if not isinstance(e, dict):
            continue
        ids = [i for i in (e.get("ids") or []) if isinstance(i, str) and i in allowed]
        if not ids:
            continue
        ids.sort(key=lambda i: -_degree(g, i))            # most connected first
        entities.append({"mention": str(e.get("mention") or "")[:80], "ids": ids,
                         "names": [g.name(i) for i in ids], "why": str(e.get("why") or "")[:160]})
        chosen += ids
    if not entities:
        return None
    considered = []
    for c in out.get("considered_but_rejected") or []:
        if isinstance(c, dict) and c.get("id") in allowed and c["id"] not in chosen:
            considered.append({"id": c["id"], "name": g.name(c["id"]), "links": _degree(g, c["id"]),
                               "why": str(c.get("why") or "")[:120]})
    flags = []
    if any(not _degree(g, i) for i in chosen):
        flags.append("a chosen entity has no links")
    if considered:
        flags.append("other candidates were considered")
    if any(len({g.by_id[i].get("type") for i in e["ids"]}) > 1 for e in entities):
        flags.append("one mention spans entities of different types")
    return {"original": question, "rewritten": rewritten, "entities": entities,
            "considered": considered, "flags": flags, "uncertain": bool(flags),
            "note": _note(question, rewritten, entities, considered),
            "map": _map(entities, g)}


def _note(question: str, rewritten: str, entities: list[dict], considered: list[dict]) -> str:
    read = "; ".join(f"“{e['mention']}” as {', '.join(e['names'])}" if e["mention"] else ", ".join(e["names"])
                     for e in entities)
    text = f"Interpreted as: {rewritten}" if rewritten.strip().lower() != question.strip().lower() else "Interpreted as asked"
    text += f" ({read})."
    if considered:
        text += " Also considered: " + "; ".join(
            f"{c['name']} ({c['links']} links)" for c in considered[:4]) + "."
    return text


def _map(entities: list[dict], g: "gq._Graph") -> dict:
    """name or mention (lower case) -> the entity ids it stands for, used to seed the graph templates."""
    m: dict[str, list[str]] = {}
    for e in entities:
        for key in [e["mention"]] + e["names"]:
            if key:
                m.setdefault(key.strip().lower(), [])
                for i in e["ids"]:
                    if i not in m[key.strip().lower()]:
                        m[key.strip().lower()].append(i)
    return m


@contextmanager
def seeded(link_result: Optional[dict]):
    """While active, the graph templates resolve a linked name to ALL the ids chosen for it."""
    token = gq.LINKS.set((link_result or {}).get("map") or {})
    try:
        yield
    finally:
        gq.LINKS.reset(token)


def evidence_block_ids(link_result: Optional[dict], g: "gq._Graph", limit: int = 12) -> list[str]:
    """Blocks the linked entities were extracted from: found through the entity, not the wording."""
    if not link_result:
        return []
    out: list[str] = []
    for e in link_result.get("entities", []):
        for i in e["ids"]:
            out += g.by_id.get(i, {}).get("block_ids", []) or []
    return list(dict.fromkeys(out))[:limit]
