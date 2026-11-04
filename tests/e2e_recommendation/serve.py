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
import shutil  # noqa: E402
import tempfile  # noqa: E402
from eawiki import usecases  # noqa: E402
_tmp = Path(tempfile.mkdtemp(prefix="uc-"))
shutil.copytree(ROOT / "use_cases", _tmp / "use_cases")
usecases.DIR = _tmp / "use_cases"            # what the screen saves goes here, never into the repo
if os.environ.get("EA_E2E_OLD_SECOND_STAGE"):      # a database copy from before the update: the second stage as it stood, for trying the update on the Config screen
    import json
    f = usecases.DIR / "demand-management.json"
    spec = json.loads(f.read_text(encoding="utf-8"))
    spec["stages"][1] = json.loads((ROOT / "tests" / "fixtures" / "phase2_stage.json").read_text(encoding="utf-8"))
    f.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
from eawiki.cases.engine import Engine  # noqa: E402
from eawiki.cases.store import store  # noqa: E402


MESSAGE = ("Please do not raise a new demand. We recommend you extend the existing platform to cover this need.\n\n"
           "What you asked for\nA mobile way to book leave.\n\nWhy\nThe platform already covers most of it, and the current licence runs until March 2027.\n\n"
           "Risks and conditions\nThe cyber team has not yet confirmed access control.\n\nNext steps\n1. The cyber team reviews access control.")
CANNED = {"Overlaps with": ["HR system"], "Consolidate with demand(s)": ["None"], "Contract / licence match": "Covered by the current licence until March 2027.",
          "Security fit": "Under the existing identity control; a review is still needed.", "Recommended owner": "HR Systems Lead",
          "Recommendation type": "Enhancement", "Risks and conditions": ["The cyber team has not yet confirmed access control."],
          "Next steps": ["The cyber team reviews access control."], "Recommendation": MESSAGE}


def tools():
    t = base.fake_tools()
    inner = t.llm_json

    def llm(prompt):
        m = re.search(r"PROPERTY: (.+?)  \[", prompt)
        name = m.group(1) if m else ""
        ids = re.findall(r"\[([^\]\s]+:\d+)\]", prompt)
        if name in CANNED and "INSTRUCTIONS FOR THIS STAGE" in prompt:                # only the second stage's properties
            return {"value": CANNED[name], "status": "answered", "evidence": ids[:1], "needs": "", "note": "n"}
        return inner(prompt)
    t.llm_json = llm
    return t


cases_api.set_engine(Engine(store(), tools, workers=2))
uvicorn.run(appmod.app, host="127.0.0.1", port=int(os.environ.get("PORT", "8766")), log_level="warning")
