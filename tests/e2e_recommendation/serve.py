"""The real backend, with stand-in model answers for the Recommendation phase, for driving the EA's draft review in a real browser.

    python tests/e2e_recommendation/serve.py           # port 8766 (PORT=... to change), serves ui/dist: run `npm run build` in ui/ first
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import test_cases_engine as base  # noqa: E402  (a temporary history database, and the engine's fake tools)
import uvicorn  # noqa: E402
from eawiki.api import app as appmod, cases as cases_api  # noqa: E402
from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import store  # noqa: E402


def tools():
    t = base.fake_tools()
    inner = t.llm_json

    def llm(prompt):
        m = re.search(r"PROPERTY: (.+?)  \[", prompt)
        name = m.group(1) if m else ""
        ids = re.findall(r"\[([^\]\s]+:\d+)\]", prompt)
        if name == "Recommended action":
            return {"value": "Do not raise a new demand. Extend the existing platform to cover this need.", "status": "answered",
                    "evidence": ids[:1], "needs": "", "note": "n"}
        canned = {"Overlaps with": ["HR system"], "Contract / licence match": "Covered by the current licence until March 2027.",
                  "Security fit": "Under the existing identity control; a review is still needed.", "Recommended owner": "HR Systems Lead",
                  "Justification": "The existing platform already covers most of this need.", "Consolidate with demand(s)": ["None"]}
        if name in canned:
            return {"value": canned[name], "status": "answered", "evidence": ids[:1], "needs": "", "note": "n"}
        if name == "Recommendation":
            return {"value": "Merge/CR", "status": "answered", "evidence": ids[:1], "needs": "", "note": "n"}
        return inner(prompt)
    t.llm_json = llm
    return t


cases_api.set_engine(Engine(store(), tools, workers=2))
uvicorn.run(appmod.app, host="127.0.0.1", port=int(os.environ.get("PORT", "8766")), log_level="warning")
