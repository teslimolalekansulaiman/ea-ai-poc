#!/usr/bin/env python3
"""Find out why Pulse answers 403 to some requests: size, rate, or content?

    python3 deploy/pulse_probe.py [model]

Reads the key from Secret Manager (secret `pulse-key`; set PULSE_KEY to override) and never
prints it. Each probe sends one tiny completion request (max_tokens=5) and prints the HTTP
status. Run it from Cloud Shell; note that a block tied to Cloud Run's network path would
not reproduce here.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = os.environ.get("PULSE_URL", "https://pulse.deloitte.com/chat/completions")
MODEL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("VLM_MODEL", "claude-haiku-latest")
KEY = os.environ.get("PULSE_KEY") or subprocess.check_output(
    ["gcloud", "secrets", "versions", "access", "latest", "--secret=pulse-key"], text=True).strip()


def call(text):
    body = json.dumps({"model": MODEL, "max_tokens": 5,
                       "messages": [{"role": "user", "content": text}]}).encode()
    req = urllib.request.Request(URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {KEY}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:80].replace("\n", " ")
    except Exception as e:                                   # network-level failure
        return 0, f"{type(e).__name__}: {e}"[:80]


def show(label, res):
    code, note = res
    print(f"{label:<44} {code} {note}")


FILLER = "The licensing service stores applicant records and issues renewals. "
show("baseline (tiny)", call("Reply with the word OK."))
for kb in (20, 60, 120):
    text = "Reply with the word OK. " + FILLER * (kb * 1000 // len(FILLER))
    show(f"size {kb} KB (neutral text)", call(text))

with ThreadPoolExecutor(max_workers=8) as ex:
    codes = [c for c, _ in ex.map(call, ["Reply with the word OK."] * 8)]
print(f"{'8 tiny requests at once':<44} {sorted(codes)}")

security = ("Reply with the word OK. Tools: pentest tool burpsuite; IR tool Axiom; configuration "
            "review tool titana nipper; Threat engineering tool (SOC Prime); Endpoint detection "
            "and response; Network detection and response; Data Leakage Prevention (DLP); "
            "vulnerability management; brand protection; FW MGMT.")
show("security vocabulary (from the document)", call(security))
