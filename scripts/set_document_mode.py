"""Show a stage's results as a draft document per item, on the use case as it is stored now.

It reads the use case from the running service, changes only `output.mode` and `output.document` of the one stage you name,
and writes it back. Nothing else is touched: your other edits stay. Without --apply it only shows what would change.

    python3 scripts/set_document_mode.py BASE USE_CASE_ID "Stage name" "Headline column" [--facts "Column A,Column B"] [--apply]

    BASE        the service address, for example http://localhost:8080 (the address of `gcloud run services proxy`)
                or the Cloud Run URL (then also set TOKEN, below)
    TOKEN       environment variable; when set, it is sent as "Authorization: Bearer $TOKEN"
                  TOKEN=$(gcloud auth print-identity-token) python3 scripts/set_document_mode.py ...

A case keeps the settings it was started with: start a new case to see the drafts.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def call(method: str, url: str, body=None):
    headers = {"Content-Type": "application/json"}
    if os.environ.get("TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["TOKEN"]
    req = urllib.request.Request(url, method=method, headers=headers, data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {url} -> {e.code}: {e.read().decode(errors='replace')[:600]}")
    except urllib.error.URLError as e:
        sys.exit(f"Cannot reach {url}: {e.reason}")


def main(argv: list) -> None:
    apply = "--apply" in argv
    facts = None
    args = [a for a in argv if a != "--apply"]
    if "--facts" in args:
        i = args.index("--facts")
        facts = [x.strip() for x in args[i + 1].split(",") if x.strip()]
        del args[i:i + 2]
    if len(args) != 4:
        sys.exit(__doc__)
    base, uc_id, stage_name, headline = args
    url = f"{base.rstrip('/')}/api/usecases/{urllib.parse.quote(uc_id)}"
    spec = call("GET", url)
    stage = next((s for s in spec.get("stages") or [] if s.get("name") == stage_name), None)
    if stage is None:
        sys.exit(f"No stage named '{stage_name}'. The stages are: " + ", ".join(repr(s.get("name")) for s in spec.get("stages") or []))
    cols = {c.get("name"): c for c in stage["output"]["columns"]}
    if headline not in cols:
        sys.exit(f"The stage has no column named '{headline}'. Add it first (type text) on the Use cases screen. Its columns are: " + ", ".join(cols))
    if cols[headline].get("type") != "text":
        sys.exit(f"'{headline}' is of type {cols[headline].get('type')}; the headline must be a text column.")
    for f in facts or []:
        if f not in cols:
            sys.exit(f"The stage has no column named '{f}' (from --facts).")
    out = stage["output"]
    before = {"mode": out.get("mode") or "table", "document": out.get("document")}
    doc = dict(out.get("document") or {})
    doc["statement"] = headline
    if facts is not None:
        doc["facts"] = facts
    out["mode"], out["document"] = "document", doc
    after = {"mode": out["mode"], "document": out["document"]}
    print(f"Stage '{stage_name}' of '{uc_id}':\n  now:    {json.dumps(before)}\n  after:  {json.dumps(after)}")
    if before == after:
        print("Already set. Nothing to change.")
        return
    if not apply:
        print("Nothing written. Run again with --apply to save it.")
        return
    call("PUT", url, spec)
    saved = call("GET", url)
    got = next(s for s in saved["stages"] if s.get("name") == stage_name)["output"]
    print("Saved. Stored now:", json.dumps({"mode": got.get("mode"), "document": got.get("document")}))
    print("Start a new case to see the drafts: a case keeps the settings it was started with.")


if __name__ == "__main__":
    main(sys.argv[1:])
