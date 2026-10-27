"""The use case for the by-name group only: six properties, each a settings row over the same lookup.

Built from the production use case (so the input fields and the engine settings are the real ones) with
one stage holding Domain, Impacted application, Data classification, Linked security capability,
Duplicate with existing artefact and Owners. Their guidance is the corrected sheet's where EA wrote
steps and Claude's draft (marked in the text) where they did not. No gate: every demand is tested.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G = json.loads((ROOT / "tests" / "fixtures" / "names_guidance.json").read_text(encoding="utf-8"))

CAT = "Application Catalog"
LK = lambda find, frm, kinds, types=None, match="name", extract="": {"find": find, "from": frm, "match": match, "in": kinds, "extract": extract, **({"types": types} if types else {})}

COLS = [
 dict(name="Data classification", type="enum", values=["Public", "Internal", "Confidential", "Restricted", "Not stated", "Not assessed"], min_sources=1,
      lookups=[LK("what each data set the demand names is and how it is classified", "data", ["Data Catalog", "Data Classification Standard"], ["data"], extract="its classification"),
               LK("the definitions of the data classification levels (Public, Internal, Confidential, Restricted) and the rule when several levels are involved", "need", ["Standards"], match="meaning")]),
 dict(name="Domain", type="list", values=["Business", "Data", "Application", "Technology", "Security"], evidence_required=False, uses=["Data classification"], min_sources=1,
      lookups=[LK("what each system or platform the demand names is, and which domain it belongs to", "systems", [CAT, "Technology Catalog"], ["application", "technology"], extract="its type and domain"),
               LK("what each data set the demand names is", "data", ["Data Catalog"], ["data"], extract="its type"),
               LK("whether the demand touches sign-in, encryption, monitoring or protection of confidential data", "need", ["Security Control Catalog"], match="meaning")]),
 dict(name="Impacted application", type="list", min_sources=1,
      lookups=[LK("which application each name is", "systems", [CAT, "Glossary and Aliases"], ["application"], extract="the application, its ID and owner role"),
               LK("which applications run on, or depend on, each platform the demand names", "systems", ["Technology Catalog"], ["technology"], extract="the applications connected to it")]),
 dict(name="Linked security capability", type="list", uses=["Impacted application", "Data classification"], min_sources=1,
      lookups=[LK("the security controls linked to each impacted application", "result:Impacted application", ["Application to Security Control Matrix"], extract="the controls named"),
               LK("what the demand touches that needs a security capability", "need", ["Security Control Catalog"], match="meaning"),
               LK("what the standard requires for data classified as", "result:Data classification", ["Standards"], match="meaning")]),
 dict(name="Duplicate with existing artefact", type="text", min_sources=1,
      lookups=[LK("whether each system the demand names already has a contract feature or a project", "systems", ["Contract Register", "Initiative Portfolio"], extract="the artefact, its ID, what it covers"),
               LK("whether each system or platform the demand names already has an entry of its own", "systems", [CAT, "Technology Catalog"], ["application", "technology"], extract="the artefact, its ID, what it covers"),
               LK("whether each data set the demand names already exists as a data set or report", "data", ["Data Catalog", "Initiative Portfolio"], ["data"], extract="the data set, its ID, what it covers"),
               LK("whether a project or contract already covers each process the demand changes", "processes", ["Initiative Portfolio", "Contract Register"], match="meaning"),
               LK("whether a project, contract, catalog entry or control already covers the need", "need", ["Initiative Portfolio", "Contract Register", "Data Catalog", "Technology Catalog", "Security Control Catalog"], match="meaning")]),
 dict(name="Owners", type="list", uses=["Impacted application", "Linked security capability"], min_sources=1,
      lookups=[LK("who owns each impacted application", "result:Impacted application", [CAT], ["application"], extract="the owner role"),
               LK("who owns each platform the demand names", "systems", ["Technology Catalog"], ["technology"], extract="the owner role"),
               LK("who owns each data set the demand names", "data", ["Data Catalog"], ["data"], extract="the owner role"),
               LK("who owns each linked security capability", "result:Linked security capability", ["Security Control Catalog"], ["security"], extract="the owner role")]),
]


def build_spec() -> dict:
    spec = json.loads((ROOT / "use_cases" / "demand-management.json").read_text(encoding="utf-8"))
    spec["id"] = "names-test"
    spec["name"] = "Names test"
    spec["validation"] = {"enabled": False}
    spec["stages"] = [{"name": "Names", "id": "names", "instructions": "Fill the properties from what the demand names.",
                       "output": {"columns": [dict(c, reason_first=True, **G[c["name"]]) for c in COLS]}}]
    return spec
