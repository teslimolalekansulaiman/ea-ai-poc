"""Step 2 — Subject discovery.

Decide which pages the wiki will have, and gather the blocks each page is
written from. Three moves:

  1. SEED from the Step 1b catalogue subjects (free, already extracted).
  2. DISCOVER the rest from prose — one LLM call per document over its headings /
     paragraphs / lists finds subjects no table names: entities mentioned only in
     text, and THEMES (cross-cutting topics like "Integration Strategy"). Each
     must be grounded in real blocks. The LLM only *names* subjects — it extracts
     no relationships (that is Step 3a).
  3. GROUP every block under its subject(s) in CODE (deterministic): catalogue
     membership + name mentions + heading/section match + the LLM's block hints.

Output: a reviewable `subjects.json` — the subject list, each with its block-ids
(the "full context" window Step 3a reads).

LLM backend is pluggable: `cli` shells out to `claude -p` (works now, no SDK/key
needed); `sdk` uses the Anthropic SDK (switch to this on the sandbox).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from eawiki.blocks import Block, content_hash, load_blocks

PROSE_TYPES = {"heading", "paragraph", "list_item", "caption"}


# ---------------------------------------------------------------------------
# pluggable LLM backend
# ---------------------------------------------------------------------------
def _ssl_ctx():
    """SSL context with a real CA bundle (macOS system Python often lacks one)."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def effective_model(model: Optional[str]) -> str:
    """The model a call will actually use: the explicit one, else VLM_MODEL. Cache keys use
    this, so switching VLM_MODEL regenerates results instead of silently reusing the old
    model's output (the keys used to read only the --model flag, which is usually empty)."""
    return model or os.environ.get("VLM_MODEL") or ""


def _openai_env(model: Optional[str] = None):
    """(url, key, model) for the OpenAI-compatible backend, from env."""
    url = os.environ.get("VLM_PROXY_URL", "")
    key = (os.environ.get("VLM_PROXY_KEY") or os.environ.get("VLM_API_KEY")
           or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY") or "")
    mdl = model or os.environ.get("VLM_MODEL") or "openai/gpt-4o-mini"
    return url, key, mdl


def _image_data_url(image_path: str) -> str:
    import base64
    import mimetypes
    from pathlib import Path
    mt = mimetypes.guess_type(image_path)[0] or "image/png"
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
    return f"data:{mt};base64,{b64}"


# At most this many model/embedding requests are in flight per process. A probe of Pulse
# showed 2 of 8 simultaneous requests failing at the network level, and steps run thread
# pools of 6-8, so unbounded concurrency turned into silent failures.
_LLM_SLOTS = threading.BoundedSemaphore(int(os.environ.get("EAWIKI_LLM_CONCURRENCY", 4)))
_RETRY_CODES = {408, 425, 429, 500, 502, 503, 504}


def _transient(code: int, body: str) -> bool:
    # A 403 with an HTML body is a gateway/firewall page; a real API auth failure is JSON.
    return code in _RETRY_CODES or (code == 403 and body.lstrip()[:1] == "<")


def post_json(req: urllib.request.Request, timeout: int, what: str):
    """Send `req`, return the parsed JSON body. Bounded concurrency, and transient failures
    (gateway 403 pages, 429/5xx, dropped connections) are retried with backoff before the
    error is raised — callers like llm_json turn an exception into 'no result', so a
    transient blip must not reach them."""
    attempts = int(os.environ.get("EAWIKI_LLM_RETRIES", 4))
    for i in range(attempts + 1):
        with _LLM_SLOTS:
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                if not _transient(e.code, body) or i == attempts:
                    raise RuntimeError(f"{what} HTTP {e.code}: {body[:200]}") from None
                why = f"HTTP {e.code}"
            except OSError as e:          # URLError, timeouts, resets
                if i == attempts:
                    raise RuntimeError(f"{what} failed: {type(e).__name__}: {e}") from None
                why = type(e).__name__
        time.sleep(min(30, 2 ** (i + 1)) + random.random())
        print(f"  {what}: {why}; retry {i + 1}/{attempts}", file=sys.stderr, flush=True)


def _openai_chat(prompt: str, url: str, key: str, model: str, timeout: int = 300,
                 response_format: Optional[dict] = None, image_path: Optional[str] = None) -> str:
    """One OpenAI-compatible /chat/completions call (OpenRouter locally, Pulse in
    prod — same wire format). Plain urllib, no SDK. `response_format` enables
    structured outputs; `image_path` sends a base64 image for vision models."""
    if not url:
        raise RuntimeError("openai backend: set VLM_PROXY_URL (the /chat/completions URL)")
    if image_path:
        content = [{"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}}]
    else:
        content = prompt
    payload = {"model": model, "messages": [{"role": "user", "content": content}]}
    if response_format:
        payload["response_format"] = response_format
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    from eawiki import obs
    with obs.llm_span("llm.openai", prompt, model) as set_out:
        data = post_json(req, timeout, "openai chat")
        content = (data["choices"][0]["message"]["content"] or "").strip()
        set_out(content)
        return content


def llm_text(prompt: str, backend: str = "cli", model: Optional[str] = None) -> str:
    if backend == "cli":
        cmd = ["claude", "-p"]
        if model:
            cmd += ["--model", model]
        from eawiki import obs
        with obs.llm_span("llm.claude-cli", prompt, model or "claude -p") as set_out:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"claude CLI failed: {r.stderr.strip()[:200]}")
            set_out(r.stdout.strip())
            return r.stdout.strip()
    if backend in ("openai", "openrouter", "pulse"):
        # OpenAI-compatible endpoint (OpenRouter now, Pulse in prod — base_url swap)
        url, key, mdl = _openai_env(model)
        return _openai_chat(prompt, url, key, mdl)
    if backend == "sdk":
        from anthropic import Anthropic
        client = Anthropic()
        resp = client.messages.create(
            model=model or "claude-opus-5-5", max_tokens=2000,
            messages=[{"role": "user", "content": prompt}])
        return resp.content[0].text.strip()
    raise ValueError(f"unknown backend: {backend}")


def llm_vision(prompt: str, image_path: str, backend: str = "cli", model: Optional[str] = None) -> str:
    """Describe/read an image. OpenAI-compatible backends send the image as base64
    (works with Pulse/OpenRouter vision models); the cli backend reads the file by path."""
    if backend in ("openai", "openrouter", "pulse"):
        url, key, mdl = _openai_env(model)
        return _openai_chat(prompt, url, key, mdl, image_path=image_path).strip()
    return llm_text(f"{prompt}\n\nRead the image file at: {image_path}", backend, model).strip()


def llm_json(prompt: str, backend: str = "cli", model: Optional[str] = None,
             schema: Optional[dict] = None):
    """Return parsed JSON from the model. On OpenAI-compatible backends this uses
    **structured outputs** — a json_schema when `schema` is given, else json_object
    mode — so the reply is guaranteed valid JSON (no markdown fences / truncation to
    reparse). Falls back to lenient text extraction on cli/sdk, or if the provider
    rejects response_format. Returns None if nothing parseable comes back."""
    if backend in ("openai", "openrouter", "pulse"):
        url, key, mdl = _openai_env(model)
        rf = ({"type": "json_schema", "json_schema": {"name": "extraction", "strict": True, "schema": schema}}
              if schema else {"type": "json_object"})
        try:
            return json.loads(_openai_chat(prompt, url, key, mdl, response_format=rf))
        except Exception:
            try:    # provider may not support response_format -> plain call + lenient parse
                return _extract_json(_openai_chat(prompt, url, key, mdl))
            except Exception as e:
                print(f"  llm_json: no result ({type(e).__name__}: {str(e)[:120]})",
                      file=sys.stderr, flush=True)
                return None
    return _extract_json(llm_text(prompt, backend, model))


def _extract_json(text: str) -> Any:
    """Pull the first JSON array/object out of an LLM reply."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        t = t[4:].strip() if t.lower().startswith("json") else t.strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"(\[.*\]|\{.*\})", t, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        raise


# ---------------------------------------------------------------------------
# discovery (one call per document)
# ---------------------------------------------------------------------------
def _prose_preview(blocks: list[Block], limit: int = 320) -> str:
    lines = []
    for b in blocks:
        if b.type not in PROSE_TYPES or not b.text.strip():
            continue
        sec = " > ".join(b.section_path) if b.section_path else "-"
        txt = b.text.strip().replace("\n", " ")
        if len(txt) > limit:
            txt = txt[:limit] + "…"
        lines.append(f"[{b.block_id}] ({b.type} | {sec}) {txt}")
    return "\n".join(lines)


def discover_in_doc(blocks: list[Block], seed_names: list[str], menu: dict,
                    backend: str, model: Optional[str]) -> list[dict]:
    preview = _prose_preview(blocks)
    if not preview.strip():
        return []
    node_types = ", ".join(sorted(menu["node_types"]))
    seeds = ", ".join(sorted(seed_names)) or "(none)"
    prompt = f"""You are discovering the SUBJECTS of an enterprise-architecture wiki from one document's prose.
A subject is anything that deserves its own wiki page: an ENTITY (a typed thing) or a THEME (a cross-cutting topic such as "Integration Strategy" or "2027 Roadmap").

Allowed entity types (from the schema): {node_types}

Subjects ALREADY known from catalogue tables (do NOT repeat these): {seeds}

Document prose blocks (id, type, section path, text):
{preview}

Return ONLY a JSON array of ADDITIONAL subjects found in this prose. Each item:
{{"name": "<subject name>",
  "kind": "entity" | "theme",
  "type": "<an allowed entity type, or 'theme'>",
  "block_ids": ["<ids of blocks that discuss it>"],
  "reason": "<one short line of why it is a subject>"}}

Rules:
- Only include subjects that are genuinely discussed here (grounded in the listed blocks).
- Skip document scaffolding headings like "Purpose", "Overview", "Process Flow".
- Skip anything already in the known list above.
- A theme needs a heading about it or repeated discussion across blocks.
- If there are none, return []."""
    try:
        data = llm_json(prompt, backend, model)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  ! discovery failed for a doc ({type(e).__name__}: {str(e)[:120]}) — skipping its prose subjects")
        return []


# ---------------------------------------------------------------------------
# grouping (deterministic, in code)
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _bid_key(bid: str):
    return (bid.split(":")[0], int(bid.split(":")[1]))


def group_blocks(subject: dict, all_blocks: list[Block], llm_block_ids: set[str]) -> list[str]:
    """Gather the blocks a subject is written from. Beyond direct name/heading
    mentions, do SECTION-BASED expansion: once the subject is mentioned anywhere
    in a (leaf) section, pull in every block of that section — so pronoun-only
    paragraphs and captionless figures in the same section travel with it."""
    name = _norm(subject["name"])
    ids: set[str] = set(llm_block_ids)
    if subject.get("catalogue_block"):
        ids.add(subject["catalogue_block"])

    hit_sections: set[tuple] = set()
    for b in all_blocks:
        hit = False
        if name and name in _norm(b.text):                       # ③ named in the text
            hit = True
        if any(name == _norm(h) for h in b.section_path):        # ④ under a heading of its name
            hit = True
        if b.type == "figure" and name and name in _norm((b.figure or {}).get("caption", "")):
            hit = True                                           # named in a figure caption
        if hit:
            ids.add(b.block_id)
            if b.section_path:
                hit_sections.add(tuple(b.section_path))

    if hit_sections:                                             # ⑤ section-based expansion
        for b in all_blocks:
            if b.section_path and tuple(b.section_path) in hit_sections:
                ids.add(b.block_id)

    return sorted(ids, key=_bid_key)


def attach_orphan_figures(subjects_list: list[dict], all_blocks: list[Block]) -> list[dict]:
    """Guarantee every figure lands in some subject so the Step 3a vision pass
    will read it. Figures already pulled into a subject (via section expansion or
    a caption match) are left alone; each remaining orphan figure becomes its own
    'diagram' subject, grouped with the other blocks in its section. The figure's
    image_ref is carried through (the pixels still need exporting at parse time)."""
    covered = {bid for s in subjects_list for bid in s["block_ids"]}
    by_section: dict[tuple, list[Block]] = {}
    for b in all_blocks:
        by_section.setdefault(tuple(b.section_path), []).append(b)

    new: dict[str, dict] = {}
    for b in all_blocks:
        if b.type != "figure" or b.block_id in covered:
            continue
        sect = tuple(b.section_path)
        name = ((b.figure or {}).get("caption") or (b.section_path[-1] if b.section_path else "")
                or f"Figure {b.ordinal}").strip()
        key = _norm(name)
        block_ids = sorted({x.block_id for x in by_section.get(sect, [])} | {b.block_id}, key=_bid_key)
        if key in new:
            new[key]["block_ids"] = sorted(set(new[key]["block_ids"]) | set(block_ids), key=_bid_key)
            new[key]["image_refs"].append((b.figure or {}).get("image_ref"))
        else:
            new[key] = {"name": name, "type": "theme", "kind": "figure", "source": "figure",
                        "evidence": f"diagram in section {' / '.join(b.section_path) or '(root)'}",
                        "image_refs": [(b.figure or {}).get("image_ref")],
                        "block_ids": block_ids}
    for v in new.values():
        v["n_blocks"] = len(v["block_ids"])
    return list(new.values())


def coverage_report(all_blocks: list[Block], subjects_list: list[dict]) -> dict:
    """What no subject claimed. Headings are expected orphans (navigation); the
    rest are flagged for review so a silent miss becomes a visible list."""
    covered = {bid for s in subjects_list for bid in s["block_ids"]}
    orphans = [b for b in all_blocks if b.block_id not in covered]
    review = [b for b in orphans if b.type != "heading"]
    return {
        "total_blocks": len(all_blocks),
        "covered": len(covered),
        "orphans": len(orphans),
        "orphan_headings_ignorable": sum(1 for b in orphans if b.type == "heading"),
        "orphans_to_review": [
            {"block_id": b.block_id, "type": b.type,
             "section_path": b.section_path, "text": (b.text or "")[:120]}
            for b in sorted(review, key=lambda b: _bid_key(b.block_id))
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Step 2 — subject discovery")
    ap.add_argument("--in", dest="in_dir", default="data/blocks")
    ap.add_argument("--facts", dest="facts", default="data/graph/facts_1b.json")
    ap.add_argument("--menu", dest="menu", default="menu.json")
    ap.add_argument("--out", dest="out", default="data/graph/subjects.json")
    ap.add_argument("--coverage", dest="coverage", default="data/graph/coverage.json")
    ap.add_argument("--backend", default="cli", choices=["cli", "sdk", "openai", "openrouter", "pulse"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--cache-dir", default="data/graph/subject_cache",
                    help="cache prose discovery per doc so unchanged docs aren't re-discovered")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    menu = json.loads(Path(args.menu).read_text(encoding="utf-8"))
    facts = json.loads(Path(args.facts).read_text(encoding="utf-8"))

    # load all blocks, keep per-doc order
    docs: dict[str, list[Block]] = {}
    all_blocks: list[Block] = []
    for fp in sorted(glob.glob(f"{args.in_dir}/*.blocks.json")):
        bs = load_blocks(Path(fp))
        if bs:
            docs[bs[0].doc_id] = bs
            all_blocks += bs

    # 1) SEED subjects from catalogue (dedupe by name)
    subjects: dict[str, dict] = {}
    for s in facts["subjects"]:
        key = _norm(s["name"])
        if key not in subjects:
            subjects[key] = {"name": s["name"], "type": s["type"], "kind": "entity",
                             "source": "catalogue", "evidence": f"catalogue {s['block_id']}",
                             "catalogue_block": s["block_id"], "_llm_blocks": set()}
    seed_names = [v["name"] for v in subjects.values()]

    # 2) DISCOVER from prose, per document (cached by the doc's prose + schema, so an
    # unchanged document is not re-discovered on re-ingest — the key deliberately excludes
    # the global seed list, so adding one doc doesn't bust every other doc's cache; any
    # overlap with a new seed just merges below).
    cdir = Path(args.cache_dir)
    node_types_sig = ", ".join(sorted(menu["node_types"]))

    def _disc_key(blocks):
        return content_hash(_prose_preview(blocks), node_types_sig, args.backend,
                            effective_model(args.model))

    def _discover(doc_id, blocks):
        if args.no_cache:
            return discover_in_doc(blocks, seed_names, menu, args.backend, args.model), False
        cf = cdir / f"{_disc_key(blocks)}.json"
        if cf.exists():
            try:
                return json.loads(cf.read_text(encoding="utf-8")), True
            except Exception:
                pass
        ds = discover_in_doc(blocks, seed_names, menu, args.backend, args.model)
        cdir.mkdir(parents=True, exist_ok=True)
        cf.write_text(json.dumps(ds, ensure_ascii=False), encoding="utf-8")
        return ds, False

    print(f"discovering prose subjects via backend={args.backend} over {len(docs)} docs…")
    discovered = 0
    n_cached = 0
    for doc_id, blocks in docs.items():
        ds, hit = _discover(doc_id, blocks)
        n_cached += 1 if hit else 0
        for d in ds:
            name = d.get("name", "").strip()
            if not name:
                continue
            key = _norm(name)
            if key in subjects:  # merge into existing (seed or earlier doc)
                subjects[key]["_llm_blocks"].update(d.get("block_ids", []))
                if subjects[key]["source"] == "catalogue":
                    subjects[key]["source"] = "catalogue+prose"
            else:
                subjects[key] = {"name": name, "type": d.get("type", "theme"),
                                 "kind": d.get("kind", "theme"), "source": "prose",
                                 "evidence": d.get("reason", ""), "catalogue_block": None,
                                 "_llm_blocks": set(d.get("block_ids", []))}
                discovered += 1

    # 3) GROUP blocks under each subject (code, with section-based expansion)
    out_list = []
    for v in subjects.values():
        block_ids = group_blocks(v, all_blocks, v.pop("_llm_blocks"))
        v.pop("catalogue_block", None)
        v["block_ids"] = block_ids
        v["n_blocks"] = len(block_ids)
        out_list.append(v)

    # 3b) ATTACH orphan figures so no diagram is lost (each becomes a 'diagram' subject)
    fig_subjects = attach_orphan_figures(out_list, all_blocks)
    out_list += fig_subjects
    out_list.sort(key=lambda x: (x["kind"] != "entity", x["name"]))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out_list, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3c) COVERAGE report — what no subject claimed (silent miss -> visible list)
    cov = coverage_report(all_blocks, out_list)
    Path(args.coverage).write_text(json.dumps(cov, indent=2, ensure_ascii=False), encoding="utf-8")

    n_theme = sum(1 for s in out_list if s["kind"] == "theme")
    print(f"\nsubjects: {len(out_list)}  (seeds {len(seed_names)}, +{discovered} from prose, "
          f"+{len(fig_subjects)} diagrams; {n_theme} themes)  [discovery: {n_cached}/{len(docs)} docs from cache]")
    print(f"-> {args.out}  (reviewable)")
    print(f"coverage: {cov['covered']}/{cov['total_blocks']} blocks covered, "
          f"{cov['orphans']} orphan ({cov['orphan_headings_ignorable']} headings ignorable, "
          f"{len(cov['orphans_to_review'])} to review)")
    print(f"-> {args.coverage}")
    if cov["orphans_to_review"]:
        print("  orphans to review:")
        for o in cov["orphans_to_review"]:
            print(f"    {o['block_id']:<20} [{o['type']:<9}] {o['text'][:60]}")
    print("\nnew prose/theme/diagram subjects:")
    for s in out_list:
        if s["source"] != "catalogue":
            print(f"  {s['name']:30s} [{s['kind']}/{s['type']}]  {s['n_blocks']} blocks  — {s['evidence'][:55]}")


if __name__ == "__main__":
    main()
