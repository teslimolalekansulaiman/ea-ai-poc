"""Step 1 of the page finder: match what the demand mentions to the entities the knowledge base has.

A mention ("HR system", "Oracle DB", "C-204") is compared with the name, other names and catalog IDs of
every entity in the graph. Each candidate says HOW it matched, so the reader can tell the exact name from
an alias, from a word the mention shares with a longer name, or from a mention that merely contains a name.
Pure code, no model, no knowledge base: `resolve_entities` takes the list of entities, so it is tested on its own.

Rules this module keeps:
  * it finds and labels candidates; it never decides which one the demand means;
  * a partial match is never reported as strong: "payroll" is only part of "HR & Payroll Portal";
  * an entity of a kind the lookup does not accept is reported as "also exists as", not offered;
  * a name that fits entities of different kinds is flagged ambiguous ("HR" the data category, "HR" the application).
"""

from __future__ import annotations

import re
from typing import Optional

# Words that say what KIND of thing a mention is, not which one. They are left out of the name match
# and used to prefer a candidate of the matching kind ("HR system" prefers an application to the HR data).
GENERIC = {
    "system": "app", "systems": "app", "app": "app", "apps": "app", "application": "app", "applications": "app",
    "tool": "app", "tools": "app", "portal": "app", "solution": "app", "software": "app", "service": "app",
    "module": "app", "modules": "app", "component": "app", "feature": "app", "function": "app",
    "platform": "tech", "server": "tech", "servers": "tech", "database": "tech", "databases": "tech", "db": "tech",
    "infrastructure": "tech", "network": "tech", "cloud": "tech",
    "data": "data", "records": "data", "record": "data", "information": "data", "reports": "data", "report": "data",
    "control": "security", "controls": "security",
}
STOP = {"the", "a", "an", "of", "our", "my", "your", "new", "old", "existing", "current", "for", "to", "in", "on", "and", "&", "with"}

FAMILIES = {
    "app": ("application", "information_system_service"),
    "tech": ("technology", "platform_service"),
    "data": ("data_entity", "data_component", "data"),
    "security": ("control",),
    "role": ("role", "organization_unit", "actor"),
}

MIN_SCORE = 0.3        # below this a candidate is noise
PARTIAL = 0.5          # at or above: an entity whose name overlaps the mention
STRONG = 0.75          # at or above: the exact name, an alias, or the same core words


def _stem(t: str) -> str:
    """A light, language-neutral stem so 'reports', 'reporting' and 'report' meet. Used on both sides of a match."""
    if len(t) > 4 and t.endswith("ies"):
        t = t[:-3] + "y"
    elif len(t) > 4 and t.endswith(("sses", "xes", "ches", "shes")):
        t = t[:-2]
    elif len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        t = t[:-1]
    if len(t) - 3 >= 4 and t.endswith("ing"):
        t = t[:-3]
    elif len(t) - 2 >= 4 and t.endswith("ed"):
        t = t[:-2]
    return t


def tokens(s: str) -> list[str]:
    s = str(s or "").casefold().replace("&", " and ")
    return [_stem(t) for t in re.findall(r"[^\W_]+(?:[-.][^\W_]+)*", s) if t not in STOP]


def norm(s: str) -> str:
    return " ".join(tokens(s))


def core(s: str) -> frozenset:
    return frozenset(t for t in tokens(s) if t not in GENERIC)


def hint(s: str) -> Optional[str]:
    """The kind a mention points to through its generic words ('HR system' -> app), if any."""
    kinds = [GENERIC[t] for t in tokens(s) if t in GENERIC]
    return max(set(kinds), key=kinds.count) if kinds else None


LABEL = {"app": "application", "tech": "technology", "data": "data set", "security": "security control", "role": "role"}


def label(node_type: str) -> str:
    """The word a reader uses for a kind of entity ('application'), not the code's short name for it."""
    return LABEL.get(family(node_type) or "", str(node_type or "entity"))


_ID = re.compile(r"\b[A-Za-z]{1,4}-\d+\b")


def is_id(text: str) -> bool:
    """A catalog identifier ('C-204', 'SC-01'): a short code and a number, nothing else."""
    return bool(re.fullmatch(_ID.pattern, str(text or "").strip()))


def family(node_type: str) -> Optional[str]:
    t = str(node_type or "")
    for fam, keys in FAMILIES.items():
        if any(k in t for k in keys):
            return fam
    return None


def _names(node: dict) -> list[tuple[str, str]]:
    """(text, kind) for every way a node can be called: its name, aliases and ids."""
    out = [(node.get("name", ""), "name")]
    out += [(a, "alias") for a in node.get("aliases") or [] if a]
    out += [(i, "id") for i in node.get("ids") or [] if i]
    return [(t, k) for t, k in out if t]


def _score_node(mention: str, node: dict) -> tuple[float, str, str]:
    """(score, how, the name that matched) for one node."""
    mn, mc, mh = norm(mention), core(mention), hint(mention)
    best = (0.0, "", "")
    for text, kind in _names(node):
        tn, tc = norm(text), core(text)
        if not tn:
            continue
        if kind == "id":
            s, how = (1.0, "id") if tn == mn or mn in tn.split() else (0.0, "")
        elif tn == mn:
            s, how = (1.0, "exact") if kind == "name" else (0.97, "alias")
        elif mc and tc and mc == tc:
            s, how = 0.8, "same words"
        elif mc and tc and mc < tc:
            s, how = 0.5 + 0.2 * len(mc) / len(tc), "only part of its name"
        elif mc and tc and tc < mc:
            s, how = 0.45 + 0.2 * len(tc) / len(mc), "its name is inside the mention"
        else:
            continue
        if s > best[0]:
            best = (s, how, text)
    if best[0]:
        fam = family(node.get("type"))
        adj = 0.0
        if mh and fam:
            adj = 0.1 if mh == fam else -0.2
        best = (max(0.0, min(1.0, best[0] + adj)), best[1], best[2])
    return best


def _within_one(a: str, b: str) -> bool:
    """One typo apart: a letter changed, missing, added or two neighbours swapped."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        d = [i for i in range(len(a)) if a[i] != b[i]]
        return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = next((i for i in range(len(short)) if short[i] != long_[i]), len(short))
    return short[i:] == long_[i + 1:]


def correct_spelling(mention: str, nodes: list[dict]) -> tuple[str, bool]:
    """A word of the mention the knowledge base has never seen, one typo away from exactly one word it has
    ('Peoplx' for 'Peoplex'), is read as that word. Only words of five letters or more, and only when the
    nearest word is unique: a short word one letter off is more often another word than a typo."""
    vocab = {t for n in nodes for text, _k in _names(n) for t in tokens(text)}
    out, changed = [], False
    for t in tokens(mention):
        if t in vocab or t in GENERIC or len(t) < 5:
            out.append(t)
            continue
        near = {v for v in vocab if len(v) >= 5 and _within_one(t, v)}
        out.append(next(iter(near)) if len(near) == 1 else t)
        changed = changed or len(near) == 1
    return " ".join(out), changed


def resolve_entities(mention: str, nodes: list[dict], k: int = 4, kinds: Optional[list[str]] = None) -> list[dict]:
    """The entities a mention could mean, best first. Each: id, name, type, family, score, how, matched, strong.
    `nodes` are dicts with node_id, name, type, and optionally aliases and ids."""
    by_id = {n["node_id"]: n for n in nodes}
    cands = {}
    fixed, typo = correct_spelling(mention, nodes)
    for n in nodes:
        s, how, matched = _score_node(mention, n)
        if typo:
            s2, how2, matched2 = _score_node(fixed, n)
            if s2 - 0.05 > s:
                s, how, matched = s2 - 0.05, how2 + ", spelling corrected", matched2
        if s >= MIN_SCORE:
            cands[n["node_id"]] = (s, how, matched)
    out = []
    for nid, (s, how, matched) in cands.items():
        n = by_id[nid]
        fam = family(n.get("type"))
        if kinds and fam not in kinds:
            continue
        out.append({"id": nid, "name": n.get("name", ""), "type": n.get("type", ""), "family": fam, "score": round(s, 2),
                    "how": how, "matched": matched, "strong": s >= STRONG})
    out.sort(key=lambda c: (-c["score"], c["name"]))
    return out[:k]


def other_kinds(mention: str, nodes: list[dict], kinds: list[str]) -> list[dict]:
    """Entities that match the mention strongly but are of a kind the lookup does not accept, so the
    answer can say 'also exists as a data entity' without that entity being offered as a candidate."""
    if not kinds:
        return []
    allc = resolve_entities(mention, nodes, k=8)
    return [c for c in allc if c["family"] not in kinds and c["score"] >= PARTIAL][:2]


def ambiguous(cands: list[dict]) -> bool:
    """The name could mean more than one thing: a rival of ANOTHER kind close behind the best candidate
    ('HR' the data category and 'HR' the application), or two of the same kind almost level. A weaker
    partial match behind a clear winner is not ambiguity; it is shown as a candidate and no more."""
    good = [c for c in cands if c["score"] >= PARTIAL]
    if len(good) < 2:
        return False
    top = good[0]
    for c in good[1:]:
        gap = top["score"] - c["score"]
        if c["family"] != top["family"] and gap < 0.3:
            return True
        if c["family"] == top["family"] and gap < 0.1:
            return True
    return False


