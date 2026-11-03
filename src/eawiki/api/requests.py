"""HTTP routes for a request: the demands gathered before a case exists (see eawiki.cases.request).

The existing case routes are untouched. A request ends by calling the same step a sheet always used to start a case.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from eawiki import usecases
from eawiki.cases import intake, intake_agent
from eawiki.cases import request as rq
from eawiki.cases.store import store

router = APIRouter(prefix="/api")


def _spec(uc_id: str) -> dict:
    spec = usecases.get(uc_id)
    if not spec:
        raise HTTPException(404, f"no use case '{uc_id}'")
    return spec


def llm_factory():
    """The model the agent reads with: the same adapter, backend and model the engine uses (set in the environment)."""
    import os

    from eawiki.subjects import llm_json
    backend = os.environ.get("EAWIKI_API_BACKEND", "openrouter")
    model = os.environ.get("EAWIKI_ASK_MODEL") or None
    return lambda prompt: llm_json(prompt, backend, model)


def _call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except intake_agent.AgentError as e:
        raise HTTPException(400, str(e))
    except rq.RequestMissing as e:
        raise HTTPException(404, str(e))
    except (rq.RequestLocked, rq.RequestIncomplete) as e:
        raise HTTPException(409, str(e))
    except rq.RequestError as e:
        raise HTTPException(400, str(e))


def _started(spec: dict, parsed: dict, name: str, files: list) -> dict:
    if parsed.get("error"):
        raise HTTPException(400, parsed["error"])
    if not parsed.get("items"):
        raise HTTPException(400, f"No {((spec.get('input') or {}).get('item_label') or {}).get('plural', 'items')} found.")
    rid = rq.start(store(), spec, name=name, items=parsed["items"], files=files, unmatched=parsed.get("unmatched") or [])
    return rq.view(store(), rid)


@router.post("/requests/from-file")
async def from_file(use_case_id: str, file: UploadFile = File(...)):
    spec = _spec(use_case_id)
    fname = file.filename or ""
    parsed = intake.parse_file(spec, fname, await file.read())
    return _started(spec, parsed, fname.rsplit(".", 1)[0] if "." in fname else (fname or "Request"), [fname])


class TextBody(BaseModel):
    use_case_id: str
    text: str


@router.post("/requests/from-text")
def from_text(body: TextBody):
    spec = _spec(body.use_case_id)
    parsed = intake.from_text(spec, body.text)
    first = (parsed.get("items") or [{}])[0]
    title = first.get((spec.get("input") or {}).get("title_field") or "title") or "Request"
    return _started(spec, parsed, str(title)[:60], [])


@router.get("/requests/{rid}")
def get_request(rid: str):
    return _call(rq.view, store(), rid)


class SetBody(BaseModel):
    values: Optional[dict] = None
    declined: Optional[list[str]] = None


@router.put("/requests/{rid}/items/{item}")
def set_item(rid: str, item: str, body: SetBody):
    return _call(rq.set_values, store(), rid, item, body.values, body.declined)


class FillBody(BaseModel):
    field: str
    items: list[str]
    value: Optional[str] = None
    decline: bool = False


@router.post("/requests/{rid}/fill")
def fill(rid: str, body: FillBody):
    return _call(rq.fill, store(), rid, body.field, body.items, body.value, body.decline)


@router.get("/requests/{rid}/gaps")
def gaps(rid: str):
    data, name, media = rq.gaps_file(_call(rq.view, store(), rid))
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


class SubmitBody(BaseModel):
    allow_incomplete: bool = False


def _create(spec: dict, items: list, name: str) -> str:
    from eawiki.api.cases import get_engine
    e = get_engine()
    cid = e.create(spec, items, name or f"{len(items)} demand(s)")
    e.start(cid)
    return cid


@router.post("/requests/{rid}/submit")
def submit(rid: str, body: SubmitBody):
    return _call(rq.submit, store(), _create, rid, body.allow_incomplete)


class MessageBody(BaseModel):
    use_case_id: str
    text: str


@router.post("/requests/from-message")
def from_message(body: MessageBody):
    """A request from what a person wrote. With no demand in it no request is made, and the reply says so."""
    spec = _spec(body.use_case_id)
    return _call(intake_agent.start_from_message, store(), spec, llm_factory(), body.text)


class TurnBody(BaseModel):
    text: Optional[str] = None
    answer: Optional[dict] = None          # a button: {value, scope: "all" | [ids]} or {decline: true, scope}


@router.post("/requests/{rid}/messages")
def message(rid: str, body: TurnBody):
    """One step with the agent: what the person typed (or the button they pressed), what changed, and the next question."""
    return _call(intake_agent.turn, store(), rid, llm_factory(), text=body.text, answer=body.answer)
