"""Reading an attached file into text the request agent can read.

What is read, and how:
  text       .txt .md                       as written
  email      .eml                           the headers that matter and the body (plain text, else the HTML as text);
                                            files attached INSIDE the email are named, not read
  document   .docx .pptx .pdf               the ingestion parser (Docling), as Markdown; a table stays a table.
                                            Word and PowerPoint are what ingestion reads today. A PDF is tried: a server
                                            whose parser cannot read PDFs says so instead of guessing.
A sheet (.xlsx .xlsm .csv) is not text: it is read as one demand per row, and starts a request on its own.

What a file says is DATA. This only turns it into text; fencing it, and checking that every value taken from it really
appears in it, is the agent's job (intake_agent). Nothing is read that cannot be said to have been read: a file with no text
in it is refused with the reason, and a file longer than the limit says how much of it was read.
"""

from __future__ import annotations

import email
import email.policy
import os
import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 20000                 # of one file
TEXT_EXTS = (".txt", ".md", ".text")
EMAIL_EXTS = (".eml",)
DOC_EXTS = (".docx", ".pptx", ".pdf")
SHEET_EXTS = (".csv", ".xlsx", ".xlsm")
READABLE = TEXT_EXTS + EMAIL_EXTS + DOC_EXTS


class AttachmentError(ValueError):
    """The file cannot be read: say why."""


def safe_name(name: str) -> str:
    """A file name safe to show and to put in a prompt: no path, no quotes, no control characters."""
    n = os.path.basename(str(name or "").replace("\\", "/"))
    n = re.sub(r'["\x00-\x1f\x7f]+', " ", n).strip()
    return n[:80] or "file"


def kind_of(name: str) -> str:
    ext = Path(str(name or "")).suffix.lower()
    if ext in TEXT_EXTS:
        return "text"
    if ext in EMAIL_EXTS:
        return "email"
    if ext in DOC_EXTS:
        return "document"
    if ext in SHEET_EXTS:
        return "sheet"
    return ""


def is_sheet(name: str) -> bool:
    return kind_of(name) == "sheet"


class _Plain(HTMLParser):
    """HTML as text: no scripts or styles, a line break at each block."""
    BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _html_text(html: str) -> str:
    p = _Plain()
    p.feed(html)
    p.close()
    return "".join(p.out)


def _email_text(data: bytes) -> tuple[str, list]:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    head = [f"{h}: {str(msg[h]).strip()}" for h in ("Subject", "From", "To", "Cc", "Date") if msg[h]]
    body = ""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is not None:
        try:
            body = part.get_content()
        except Exception:
            body = ""
        if part.get_content_type() == "text/html":
            body = _html_text(body)
    inside = [str(p.get_filename()) for p in msg.iter_attachments() if p.get_filename()]
    notes = [f"Files attached inside the email were not read: {', '.join(safe_name(x) for x in inside)}."] if inside else []
    return "\n".join(head) + ("\n\n" if head and body else "") + body, notes


_converter = None


def _docling_text(path: str) -> str:
    """The ingestion parser, as Markdown. Raises ImportError when this server's parser cannot read the format."""
    global _converter
    from docling.document_converter import DocumentConverter
    if _converter is None:
        _converter = DocumentConverter()
    return _converter.convert(path).document.export_to_markdown()


def _clean(text: str) -> str:
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def read(name: str, data: bytes, documents: Optional[Callable] = None) -> dict:
    """{name, kind, text, chars, truncated, notes}. `documents(path) -> text` is the reader for Word, PowerPoint and PDF files."""
    shown = safe_name(name)
    kind = kind_of(shown)
    if len(data) > MAX_BYTES:
        raise AttachmentError(f"{shown} is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    if kind == "sheet":
        raise AttachmentError(f"{shown} is a sheet. A sheet is read as one demand per row, so it starts a request on its own.")
    if not kind:
        raise AttachmentError(f"{shown} is not a kind of file I can read. I read: {', '.join(READABLE)}.")
    notes: list = []
    if kind == "text":
        text = data.decode("utf-8-sig", errors="replace")
    elif kind == "email":
        try:
            text, notes = _email_text(data)
        except Exception:
            raise AttachmentError(f"I could not read {shown} as an email.")
    else:
        ext = Path(shown).suffix.lower()
        reader = documents or _docling_text
        fd, tmp = tempfile.mkstemp(suffix=ext)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            text = reader(tmp)
        except ImportError:
            raise AttachmentError(f"This server cannot read {ext} files. Save {shown} as Word, or paste its text.")
        except Exception:
            raise AttachmentError(f"I could not read {shown}. It may be damaged or protected.")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    text = _clean(text)
    if not text:
        raise AttachmentError(f"No text could be read from {shown}. If it is a scan or a picture of text, paste the text instead.")
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS]
        notes.append(f"Only the first {MAX_CHARS} characters of {shown} were read.")
    return {"name": shown, "kind": kind, "text": text, "chars": len(text), "truncated": truncated, "notes": notes}
