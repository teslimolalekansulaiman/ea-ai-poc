"""The by-name lookup, measured on 14 demands against a synthetic knowledge base (tests/kb_fixture.py).

No model is used. The demand's mentions are the reference ones (what a careful reader would list), so
what is measured is the lookup: does each name resolve to the right entity, are the entities that are
not there reported as not there, and does the evidence shown to the answer step hold every fact that
the answer needs. Whether the model then reads it right is measured by tests/e2e_names.py.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402
import names_spec  # noqa: E402

from eawiki import usecases  # noqa: E402
from eawiki.cases import gather as gmod  # noqa: E402
from eawiki.cases import namelookup as nl  # noqa: E402
from eawiki.cases import plan as pmod  # noqa: E402
from eawiki.cases import profile as profmod  # noqa: E402

SPEC = names_spec.build_spec()
COLS = {c["name"]: c for c in SPEC["stages"][0]["output"]["columns"]}
TOOLS = kb.make_tools()
NAMES = {n["node_id"]: n for n in kb.NODES}


def item_of(d):
    return dict(d["item"], _id=d["item"]["demand_id"])


def profile_of(d):
    """The reference profile, passed through the same validation as a model's answer."""
    raw = {"systems": [m for m, g in d["gold"]["mentions"].items() if not any(i.startswith("DE-") for i in g)],
           "data": [m for m, g in d["gold"]["mentions"].items() if any(i.startswith("DE-") for i in g)]}
    fields = gmod.labelled_fields(SPEC, item_of(d))
    prof = profmod.validate(raw, fields)
    assert prof is not None
    kept = {m["text"] for g in prof.values() for m in g}
    assert kept == set(d["gold"]["mentions"]), (d["item"]["demand_id"], "a reference mention is not in the demand", set(d["gold"]["mentions"]) - kept)
    prof["origin"] = "model"
    return prof


def plan_of(name):
    return pmod.default_plan(COLS[name], kb.DOCS)


def evidence(d, name, decided=None):
    ev = gmod.gather(TOOLS, plan_of(name), SPEC, item_of(d), [], {}, None, profile_of(d), decided or {})
    return ev, gmod.render(ev)


def has(text, *needles):
    low = text.casefold()
    return [n for n in needles if n.casefold() not in low]


def test_spec_is_valid():
    assert usecases.validate(SPEC) == []


def test_every_reference_mention_resolves_to_the_right_entity():
    bad = []
    for d in kb.DEMANDS:
        for m, gold in d["gold"]["mentions"].items():
            kinds = ["data"] if any(i.startswith("DE-") for i in gold) else ["app", "tech"]   # as the lookups ask
            c = kb.entities(m, kinds)["candidates"]
            if gold:
                if not c or c[0]["id"] not in gold:
                    bad.append((d["item"]["demand_id"], m, gold, [x["id"] for x in c]))
            elif any(x["strong"] for x in c):
                bad.append((d["item"]["demand_id"], m, "no entry", [x["id"] for x in c]))
    assert not bad, bad


def test_a_partial_match_is_never_called_an_entry():
    c = kb.entities("payroll", ["app"])
    assert c["candidates"] and not c["candidates"][0]["strong"] and c["candidates"][0]["id"] == "C-207"
    assert [o["id"] for o in c["other_kinds"]] == ["DE-12"]      # the data set of that name is mentioned, not offered
    c = kb.entities("Peoplex payroll module", ["app"])["candidates"]
    assert c[0]["id"] == "C-204" and not c[0]["strong"]


def test_a_name_of_two_kinds_is_flagged_and_a_clear_winner_is_not():
    assert nl.ambiguous(kb.entities("HR")["candidates"])
    for m in ("HR system", "Finance system", "data warehouse", "Oracle DB", "customer data"):
        assert not nl.ambiguous(kb.entities(m)["candidates"]), m


def test_kinds_filter_keeps_data_out_of_applications():
    assert [c["id"] for c in kb.entities("HR system", ["app"])["candidates"]][0] == "C-204"
    assert kb.entities("HR system", ["app"])["other_kinds"][0]["id"] == "DE-01"
    assert kb.entities("HR data", ["data"])["candidates"][0]["id"] == "DE-01"
    assert all(c["family"] == "data" for c in kb.entities("HR", ["data"])["candidates"])


def test_a_name_not_in_the_knowledge_base_is_reported_as_not_there():
    for d in kb.DEMANDS:
        for m, gold in d["gold"]["mentions"].items():
            if gold:
                continue
            ev, text = evidence(d, "Impacted application")
            line = next(ln for ln in text.splitlines() if f'"{m}"' in ln and ("NO entry" in ln or "HAS AN" in ln or "has an entry" in ln))
            assert "HAS AN ENTRY" not in line, (d["item"]["demand_id"], line)


def test_the_vague_demand_looks_up_nothing_and_says_so():
    d = next(x for x in kb.DEMANDS if x["item"]["demand_id"] == "D-112")
    ev, text = evidence(d, "Impacted application")
    assert "the demand mentions no systems" in text
    assert not ev["wiki"]


def test_wiki_pages_are_citable_only_when_shown():
    d = kb.DEMANDS[0]
    ev, text = evidence(d, "Impacted application")
    ids = [w["id"] for w in ev["wiki"]]
    assert "wiki:peoplex-hr-system" in ids and all(i in ev["allowed"] for i in ids)
    assert "wiki:peoplex-hr-system" in text and "Type: application" in text
    assert "wiki:attendance-devices-gateway" in ids


def test_impacted_applications_are_in_the_evidence():
    miss = []
    for d in kb.DEMANDS:
        gold = d["gold"]["apps"]
        ev, text = evidence(d, "Impacted application")
        m = has(text, *[NAMES[i]["name"] for i in gold])
        if d["gold"]["domain"] and "Technology" in d["gold"]["domain"] and len(d["gold"]["domain"]) == 1:
            m = has(text, *[NAMES[i]["name"] for i in gold])        # the apps that run on the platform
        if m:
            miss.append((d["item"]["demand_id"], m))
    assert not miss, miss


def test_domain_evidence_shows_the_kind_of_every_named_thing():
    miss = []
    for d in kb.DEMANDS:
        ev, text = evidence(d, "Domain")
        for m, gold in d["gold"]["mentions"].items():
            for i in gold:
                fam = nl.label(NAMES[i]["type"])
                line = " ".join(ln for ln in text.splitlines() if f'"{m}"' in ln)
                if NAMES[i]["name"] not in line or fam not in line:
                    miss.append((d["item"]["demand_id"], m, i))
    assert not miss, miss


def test_classification_evidence_has_the_data_set_and_the_standard():
    miss = []
    for d in kb.DEMANDS:
        ev, text = evidence(d, "Data classification")
        for m, gold in d["gold"]["mentions"].items():
            for i in gold:
                if i.startswith("DE-") and has(text, NAMES[i]["extra"]):
                    miss.append((d["item"]["demand_id"], i))
        if has(text, "Restricted: information whose release would cause severe harm", "highest classification applies"):
            miss.append((d["item"]["demand_id"], "standard not read whole"))
    assert not miss, miss


def decided_apps(d):
    return {"Impacted application": [f"{NAMES[i]['name']} ({i})" for i in sorted(d["gold"]["apps"])]}


def test_security_controls_of_each_application_are_in_the_evidence():
    miss = []
    for d in kb.DEMANDS:
        gold = d["gold"]["security"]
        if not gold:
            continue
        ev, text = evidence(d, "Linked security capability", dict(decided_apps(d), **{"Data classification": d["gold"]["classification"]}))
        m = has(text, *[NAMES[i]["name"] for i in gold])
        if m:
            miss.append((d["item"]["demand_id"], m))
    assert not miss, miss


def test_nothing_to_start_from_is_said_when_no_application_was_found():
    d = next(x for x in kb.DEMANDS if x["item"]["demand_id"] == "D-111")
    ev, text = evidence(d, "Linked security capability", {"Impacted application": []})
    assert "Impacted application found nothing to start from" in text


def test_existing_artefacts_are_in_the_evidence():
    miss = []
    for d in kb.DEMANDS:
        gold = d["gold"]["artefact"]
        if not gold:
            continue
        ev, text = evidence(d, "Duplicate with existing artefact")
        m = has(text, *[i if i.startswith("P-") else NAMES[i]["name"].split()[0] for i in gold])
        if m:
            miss.append((d["item"]["demand_id"], m))
    assert not miss, miss


def test_owners_of_the_applications_and_platforms_are_in_the_evidence():
    miss = []
    for d in kb.DEMANDS:
        gold = d["gold"]["owners"]
        if not gold:
            continue
        ev, text = evidence(d, "Owners", decided_apps(d))
        m = has(text, *gold)
        if m:
            miss.append((d["item"]["demand_id"], m))
    assert not miss, miss


def test_names_from_a_result_become_the_next_lookups():
    got = gmod.names_from_result(["Peoplex HR System (C-204)", "HR & Payroll Portal (C-207)", "None"])
    assert got == ["Peoplex HR System", "C-204", "HR & Payroll Portal", "C-207"]
    assert gmod.names_from_result("Not identified") == []
    assert kb.entities("C-204")["candidates"][0]["id"] == "C-204"


def test_digest_page_reads_type_summary_and_related():
    dg = nl.digest_page(kb.PAGES["peoplex-hr-system"])
    assert dg["title"] == "Peoplex HR System" and dg["type"] == "application"
    assert "payroll export" in dg["summary"] and "Oracle Database Platform" in dg["related"]
    assert nl.digest_page("")["summary"] == ""


def test_the_evidence_never_names_an_entity_the_knowledge_base_lacks():
    """Everything cited is a block, a wiki page or a demand field that was shown."""
    for d in kb.DEMANDS:
        for name in COLS:
            ev, text = evidence(d, name, decided_apps(d))
            for w in ev["wiki"]:
                assert w["slug"] in kb.PAGES
            for b in ev["blocks"]:
                assert b["block_id"] in ev["allowed"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  passed", name)
    print("ok")
