"""Scoring of the seven properties against the test material's reference answers (judgments, not ground truth).

Security and Owners are scored against what follows from the applications the run itself decided, so one wrong application
is not counted three times. An extra application is allowed when it is connected to a required one or the demand's own words
name it. Where a demand is truly ambiguous, a question is the right answer (gold: ask_ok).
"""
import re

import kb_fixture as kb

from eawiki.cases import namelookup as nl

NAMES = {n["node_id"]: n for n in kb.NODES}
NONE = re.compile(r"^\s*(none|no link found|not identified|not assessed|not stated|n/a)\b", re.I)


def as_list(v):
    if isinstance(v, list):
        return [str(x) for x in v]
    return [x.strip() for x in re.split(r"[;\n]", str(v or "")) if x.strip()]


def ids_in(values):
    """Entity ids a list of answers stands for: an ID written in it, else the best strong match for its name."""
    out = set()
    for v in values:
        if NONE.match(v):
            continue
        found = re.findall(r"\b[A-Z]{1,3}-\d+\b", v)
        if found:
            out |= set(found)
            continue
        head = re.sub(r"\s*\(.*?\)", "", v).strip()
        c = nl.resolve_entities(head, kb.NODES)
        if c and c[0]["strong"]:
            out.add(c[0]["id"])
    return out


def sets_match(got, gold):
    return got == gold, sorted(got - gold), sorted(gold - got)


def neighbours(ids):
    return {b if a in ids else a for a, _r, b in kb.EDGES if a in ids or b in ids}


def named_in(text, all_kinds=False):
    """Entities the demand's own words name, by name or alias: a defensible extra (applications unless all_kinds)."""
    words = nl.core(text)
    return {n["node_id"] for n in kb.NODES if (all_kinds or nl.family(n["type"]) == "app")
            and any(nl.core(x) and nl.core(x) <= words for x in [n["name"]] + n["aliases"])}


def score(name, cell, gold, demand_text="", decided=None):
    """(ok, detail) for one property of one demand. Security and Owners are scored against what follows from the
    applications this run itself decided, so one wrong application is not counted three times."""
    status, value = cell["status"], cell["value"]
    decided = decided or {}
    vals = as_list(value)
    empty = status != "answered" or not vals or all(NONE.match(v) for v in vals)
    g = gold
    if name == "Data classification":
        want = g["classification"]
        if want in ("Not stated", "Not assessed"):
            return (empty or str(value) in ("Not stated", "Not assessed")), f"{value!r} (want {want})"
        if g.get("ask_ok") and status != "answered" and cell.get("question"):
            return True, f"asked: {cell['question'][:100]}"       # the demand really is ambiguous: a question is the right answer
        return str(value) in (g.get("classification_ok") or {want}), f"{value!r} (want {sorted(g.get('classification_ok') or {want})})"
    if name == "Domain":
        want = set(g["domain"] or [])
        if not want:
            return empty, f"{vals} (want none)"
        got = set(vals)
        main = bool(vals) and vals[0] == g["domain"][0]
        return main and want <= got, f"{vals} (want {g['domain']}; first must be {g['domain'][0]}, extras are allowed)"
    if name == "Impacted application":
        want = set(g["apps"])
        if not want:
            return empty, f"{vals} (want none)"
        got = ids_in(vals) & set(NAMES)
        allowed = neighbours(want) | named_in(demand_text)
        extra = sorted(got - want - allowed)
        return not extra and want <= got, f"missing {sorted(want - got)}, unsupported extras {extra}, defensible extras {sorted((got - want) & allowed)}"
    if name == "Linked security capability":
        apps = ids_in(as_list(decided.get("Impacted application"))) & set(NAMES)
        want = {c for a in apps for c in NAMES[a]["controls"]}
        if not want:
            return True, "no application decided: not scored"
        got = ids_in(vals) & {i for i in NAMES if i.startswith("SC-")}
        return want <= got and not (got - want), f"missing {sorted(want - got)} extra {sorted(got - want)} (controls of the applications it decided)"
    if name == "Owners":
        apps = ids_in(as_list(decided.get("Impacted application"))) & set(NAMES)
        techs = {i for m, ids in g["mentions"].items() for i in ids if i.startswith(("T-", "DE-"))}      # platforms and data sets the demand names
        ctrls = ids_in(as_list(decided.get("Linked security capability"))) & set(NAMES)              # the controls this run linked
        want = {NAMES[i]["owner"].casefold() for i in apps | techs | ctrls}
        if not want:
            return empty, f"{vals} (want none)"
        # the guidance also takes the owner of impacted data, platforms and controls: those the demand names or the applications sit on
        near = neighbours(apps) | {c for a in apps for c in NAMES[a]["controls"]} | named_in(demand_text, all_kinds=True)
        extra_ok = {NAMES[i]["owner"].casefold() for i in near if i in NAMES}
        got = {v.casefold().strip() for v in vals if not NONE.match(v)}
        hit = {w for w in want if any(w in x for x in got)}
        extra = [x for x in got if not any(w in x for w in want | extra_ok)]
        return hit == want and not extra, f"missing {sorted(want - hit)} unsupported extra {extra}"
    if name == "Duplicate with existing artefact":
        if name in g.get("ask_ok_for", ()) and status != "answered" and cell.get("question"):
            return True, f"asked: {cell['question'][:100]}"
        text = " ".join(vals) if not empty else ""
        if g["artefact"] is None:
            return empty, f"{vals} (want none)"
        found = {i for i in g["artefact"] if i in text or (not i.startswith("P-") and NAMES[i]["name"].split()[0].casefold() in text.casefold())}
        return found == set(g["artefact"]), f"found {sorted(found)} want {sorted(g['artefact'])}"
    raise KeyError(name)


REAL = {"tools": None}
