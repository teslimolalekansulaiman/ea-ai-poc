"""Observability — OpenTelemetry / OpenInference tracing to Arize Phoenix.

`init_tracing()` registers an OTLP exporter pointing at Phoenix
(PHOENIX_COLLECTOR_ENDPOINT, default http://localhost:6006). It is **safe/no-op** when
the libraries aren't installed or tracing is disabled (EAWIKI_TRACING=off), so the
pipeline runs identically with or without Phoenix.

`llm_span(name, prompt, model)` records one model call as an OpenInference LLM span
(input/output) — so every LLM call across extraction, the executor, Ask and guardrails
shows up in Phoenix with its prompt, response and latency.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

_TRACER = None
_READY = False


def init_tracing(project: str = "ea-wiki") -> None:
    global _TRACER, _READY
    if _READY:
        return
    _READY = True
    if os.environ.get("EAWIKI_TRACING", "on").lower() in ("off", "0", "false"):
        return
    try:
        from phoenix.otel import register
        endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006").rstrip("/")
        tp = register(project_name=project, endpoint=endpoint + "/v1/traces", auto_instrument=True)
        _TRACER = tp.get_tracer("eawiki")
    except Exception:
        _TRACER = None       # Phoenix not running / libs missing → tracing simply off


def _tracer():
    if not _READY:
        init_tracing()
    return _TRACER


@contextmanager
def llm_span(name: str, prompt: str, model: str = ""):
    """Record one LLM call. Yields a setter for the output; no-op if tracing is off."""
    t = _tracer()
    if t is None:
        yield (lambda _out: None)
        return
    with t.start_as_current_span(name) as span:
        try:
            span.set_attribute("openinference.span.kind", "LLM")
            if model:
                span.set_attribute("llm.model_name", model)
            span.set_attribute("input.value", (prompt or "")[:4000])
        except Exception:
            pass

        def _set_output(out: str):
            try:
                span.set_attribute("output.value", (out or "")[:4000])
            except Exception:
                pass
        yield _set_output


@contextmanager
def span(name: str, kind: str = "CHAIN", **attrs):
    """A generic span (e.g. a use-case run or a graph node). No-op if tracing is off."""
    t = _tracer()
    if t is None:
        yield
        return
    with t.start_as_current_span(name) as sp:
        try:
            sp.set_attribute("openinference.span.kind", kind)
            for k, v in attrs.items():
                sp.set_attribute(k, v)
        except Exception:
            pass
        yield
