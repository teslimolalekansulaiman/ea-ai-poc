"""HTTP routes for a request: the demands gathered before a case exists (see eawiki.cases.request).

The existing case routes are untouched. A request ends by calling the same step a sheet always used to start a case.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from eawiki import usecases
from eawiki.cases import attachments, intake, intake_agent
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
    except (intake_agent.AgentError, attachments.AttachmentError) as e:
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
    answer: Optional[dict] = None          # a button: {value, scope: "all" | [ids]}, {decline: true, scope} or {decline_all: true}
    field: Optional[str] = None            # the open question the person is looking at, when it is not the first
    answers: Optional[list] = None         # several answers sent at once, one per open question: [{field, value | decline, scope}]


@router.post("/requests/{rid}/messages")
def message(rid: str, body: TurnBody):
    """One step with the agent: what the person typed (or the button they pressed), what changed, and the next question."""
    if body.answers is not None:
        return _call(intake_agent.answer_sheet, store(), rid, llm_factory(), body.answers)
    return _call(intake_agent.turn, store(), rid, llm_factory(), text=body.text, answer=body.answer, field=body.field)


MAX_FILES = 5


def _read_files(files: list[UploadFile]) -> list[dict]:
    """The attached files, read to text. A sheet is not one of them: it starts a request on its own (see /requests/from-file)."""
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"At most {MAX_FILES} files at a time.")
    out = []
    for f in files:
        try:
            out.append(attachments.read(f.filename or "", f.file.read(attachments.MAX_BYTES + 1)))
        except attachments.AttachmentError as e:
            raise HTTPException(400, str(e))
    return out


@router.post("/requests/from-sources")
def from_sources(use_case_id: str = Form(...), text: str = Form(""), files: list[UploadFile] = File(default=[])):
    """A request from what a person wrote and the email, Word, PowerPoint, PDF or text files they attached."""
    spec = _spec(use_case_id)
    read = _read_files(files)
    return _call(intake_agent.start_from_sources, store(), spec, llm_factory(), text, read)


@router.post("/requests/{rid}/sources")
def add_sources(rid: str, text: str = Form(""), files: list[UploadFile] = File(default=[])):
    """Files added to a request that already has demands: what they say about the gaps is read, and the reply says which file each value came from."""
    _call(rq.get, store(), rid)                                            # a missing request is a 404 before any file is read
    read = _read_files(files)
    return _call(intake_agent.add_sources, store(), rid, llm_factory(), text, read)
