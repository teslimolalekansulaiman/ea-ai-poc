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
from eawiki.cases.engine import Engine
from eawiki.cases.store import store

def block(prompt, head):
    m = re.search(re.escape(head) + r'\n"""\n(.*?)\n"""', prompt, re.S)
    return m.group(1) if m else ""

def sources(prompt):
    return {m.group(1): m.group(2) for m in re.finditer(r'SOURCE: (.*?)\n"""\n(.*?)\n"""', prompt, re.S)}

def model(prompt):
    if "list the demands in them" in prompt:                              # reading a message and files
        srcs = sources(prompt)
        msg = srcs.get("your message", "")
        if "hello there" in msg.lower():
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

cases_api.set_engine(Engine(store(), base.fake_tools, workers=2))
req_api.llm_factory = lambda: model
uvicorn.run(appmod.app, host="127.0.0.1", port=int(os.environ.get("PORT", "8765")), log_level="warning")
