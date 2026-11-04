"""The real backend with a rule-based stand-in for the model, for driving the request screen in a real browser (see README.md).

    python tests/e2e_request_chat/serve.py            # port 8765 (PORT=... to change), serves ui/dist: run `npm run build` in ui/ first
"""
import os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)                                        # the app finds ui/dist and use_cases/ from here
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tests"))
import test_cases_engine as base                      # points the history database at a temporary file and gives the engine fake tools
import uvicorn
from eawiki.api import app as appmod, cases as cases_api, requests as req_api
import shutil, tempfile
from eawiki import usecases
_tmp = Path(tempfile.mkdtemp(prefix='uc-'))
shutil.copytree(ROOT / 'use_cases', _tmp / 'use_cases')
usecases.DIR = _tmp / 'use_cases'            # what the screen saves goes here, never into the repo
from eawiki.cases.engine import Engine
from eawiki.cases.store import store

def block(prompt, head):
    m = re.search(re.escape(head) + r'\n"""\n(.*?)\n"""', prompt, re.S)
    return m.group(1) if m else ""

def sources(prompt):
    return {m.group(1): m.group(2) for m in re.finditer(r'SOURCE: (.*?)\n"""\n(.*?)\n"""', prompt, re.S)}

LABELS = {"Demand ID": "demand_id", "Date submitted": "date_submitted", "Requesting department": "department", "Requester role": "requester_role",
          "Business sponsor": "sponsor", "Demand title": "title", "Request type": "request_type", "Requester urgency": "requester_urgency", "Target go-live": "target_go_live"}


def statements(srcs):
    """What a careful reader would take from labelled statements of a demand (a PDF, a typed message): one item for each 'Demand ID:'
    block, each value with the exact words it came from. A rule-based stand-in: it checks the plumbing, not how a real model reads."""
    items = []
    for name, text in srcs.items():
        text = re.sub(r"[#*]+ ?", "", text)
        for block in [p for p in re.split(r"(?m)^(?=\W*Demand request \d+:)", text) if "Demand ID:" in p]:
            f = {}

            def put(field, value, quote):
                if value.strip():
                    f[field] = {"value": value.strip(), "quote": quote.strip(), "source": name}
            m = re.search(r"Demand request \d+:\s*(.+)", block)
            if m:
                put("title", m.group(1), m.group(0))
            for label, field in LABELS.items():
                m = re.search(rf"{re.escape(label)}:\s*([^.\n]+)", block)
                if m:
                    put(field, m.group(1), m.group(0))
            for label, field, stop in (("Business need", "business_need", r"Expected outcome|Request type:"), ("Expected outcome", "expected_outcome", r"Request type:")):
                m = re.search(rf"{label}\s*:?\s*(.*?)(?={stop}|\Z)", block, re.S)
                if m:
                    words = " ".join(m.group(1).split())
                    put(field, words, words)
            items.append({"fields": f})
    return items


def model(prompt):
    if "list the demands in them" in prompt:                              # reading a message and files
        srcs = sources(prompt)
        msg = srcs.get("your message", "")
        structured = statements(srcs)
        if structured:
            return {"items": structured}
        if "need" not in msg.lower() and not any("sponsor is" in t for t in srcs.values()):      # nothing in it says that something is needed
            return {"items": []}
        fields = {}
        if msg:
            fields["business_need"] = {"value": msg, "quote": msg, "source": "your message"}
        for name, text in srcs.items():
            m = re.search(r"sponsor is ([^.\n]+)", text)
            if m and "sponsor" not in fields:
                fields["sponsor"] = {"value": m.group(1).strip(), "quote": "sponsor is " + m.group(1).strip(), "source": name}
        return {"items": [{"fields": fields}]} if fields else {"items": []}
    if "is answering a question" in prompt:                               # reading a reply
        reply = block(prompt, "THEIR REPLY:").strip()
        asked = prompt.split("QUESTION ABOUT")[0].split("IS ABOUT:")[1].split("OTHER")[0] if "IS ABOUT:" in prompt else ""
        n = len(re.findall(r"^- ", asked, re.M))
        if "Earlier they said" in prompt:
            return {"applies_to": "all"}
        every = re.search(r"\b(both|all|everyone)\b", reply.lower())
        return {"value": reply, "quote": reply, "applies_to": "all" if every or n <= 1 else "unclear"}
    if "fill in what is missing" in prompt:                               # reading files for gaps
        srcs = sources(prompt)
        missing = re.findall(r"^- (\S+) \((.*?)\): (.*)$", prompt.split("WHAT IS MISSING")[1].split("RULES")[0], re.M)
        out = []
        for name, text in srcs.items():
            m = re.search(r"sponsor is ([^.\n]+)", text)
            if m:
                for iid, _title, fields in missing:
                    if "sponsor" in fields:
                        out.append({"id": iid, "field": "sponsor", "value": m.group(1).strip(), "quote": "sponsor is " + m.group(1).strip(), "source": name})
        return {"assignments": out}
    if "Write ONE short, plain question" in prompt:                        # wording a question
        label = re.search(r"FIELD: ([^.\n]+)", prompt).group(1)
        ids = re.findall(r"^- (\S+): ", prompt.split("IT IS MISSING FOR:")[1], re.M)
        return {"question": f"What is the {label.lower()} for {', '.join(ids)}?"}
    return None

CANNED = {"Overlaps with": ["HR system"], "Consolidate with demand(s)": ["None"], "Contract / licence match": "Covered by the current licence until March 2027.",
          "Security fit": "Under the existing identity control; a review is still needed.", "Recommended owner": "HR Systems Lead",
          "Recommendation type": "Enhancement of existing", "Risks and conditions": ["The cyber team has not yet confirmed access control."]}


def tools():
    """The engine's fake tools, with answers for the second stage, so a case started here can be taken to its draft."""
    t = base.fake_tools()
    inner = t.llm_json

    def llm(prompt):
        m = re.search(r"PROPERTY: (.+?)  \[", prompt)
        name = m.group(1) if m else ""
        if "INSTRUCTIONS FOR THIS STAGE" in prompt and name in (*CANNED, "Recommendation", "Request overview"):
            who = re.search(r"\[demand:demand_id\] Demand ID: (\S+)", prompt)
            who = who.group(1) if who else ""
            ids = re.findall(r"\[([^\]\s]+:\d+)\]", prompt)
            n = len(re.findall(r"(?m)^- (?!and )\S+ \(", prompt.split("THE DEMANDS IN THIS REQUEST")[1].split("\n\n")[0])) if "THE DEMANDS IN THIS REQUEST" in prompt else 0
            value = (f"We recommend you extend the existing platform to cover {who}.\n\nWhy\nThe platform already covers most of it.\n\nRisks and conditions\n"
                     "The cyber team has not yet confirmed access control.\n\nNext steps\n1. The cyber team reviews access control.") if name == "Recommendation" else \
                (f"The request holds {n} demand{'s' if n != 1 else ''}, and they are handled separately.") if name == "Request overview" else CANNED[name]
            return {"value": value, "status": "answered", "evidence": [] if name == "Request overview" else ids[:1], "needs": "", "note": "n"}
        return inner(prompt)
    t.llm_json = llm
    return t


cases_api.set_engine(Engine(store(), tools, workers=2))
req_api.llm_factory = lambda: model
uvicorn.run(appmod.app, host="127.0.0.1", port=int(os.environ.get("PORT", "8765")), log_level="warning")
