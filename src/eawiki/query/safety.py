"""NeMo Guardrails wrapper — input/output moderation for the AI layer.

Loads the rails config (query/nemo) once and drives it with our BackendLLM
(claude -p locally, Pulse/OpenAI-compatible via env in prod). Exposes two checks the
LangGraph guard nodes call:
  check_input(question)  -> {"allowed": bool, "reason": str}
  check_output(answer)   -> {"allowed": bool, "reason": str}

A fast deterministic pre-filter (query.guardrails) runs before NeMo so the obvious
injection/jailbreak/toxicity is blocked with no model call; NeMo catches the nuance.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from eawiki.query import guardrails as det
from eawiki.query.llm import BackendLLM

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "nemo")
_REFUSAL = "I'm sorry, I can't respond to that."


@lru_cache(maxsize=4)
def _rails(backend: str, model: Optional[str]):
    from nemoguardrails import LLMRails, RailsConfig
    cfg = RailsConfig.from_path(_CONFIG_DIR)
    return LLMRails(cfg, llm=BackendLLM(backend=backend, model=model))


def _content(res) -> str:
    # rails.generate() returns a GenerationResponse; unwrap .response -> messages
    resp = getattr(res, "response", res)
    if isinstance(resp, list) and resp:
        last = resp[-1]
        return (last.get("content") if isinstance(last, dict) else str(last) or "").strip()
    if isinstance(resp, dict):
        return (resp.get("content") or "").strip()
    return str(resp).strip()


def _is_refusal(text: str) -> bool:
    return text.strip().lower().startswith("i'm sorry, i can't respond")


class NeMoGuard:
    def __init__(self, backend: str = "cli", model: Optional[str] = None,
                 use_deterministic: bool = True):
        self.backend, self.model = backend, model
        self.use_det = use_deterministic

    def check_input(self, question: str) -> dict:
        # layer 1: deterministic (no model) — fast, catches the obvious
        if self.use_det:
            d = det.check_input_deterministic(question)
            if not d["allowed"]:
                return {"allowed": False, "category": d["category"],
                        "reason": d["reason"], "layer": "deterministic"}
        # layer 2: NeMo self-check input (nuanced)
        rails = _rails(self.backend, self.model)
        res = rails.generate(messages=[{"role": "user", "content": question}],
                             options={"rails": ["input"]})
        blocked = _is_refusal(_content(res))        # allowed echoes input; blocked -> refusal
        return {"allowed": not blocked,
                "category": "unsafe" if blocked else "ok",
                "reason": "blocked by NeMo input rail" if blocked else "",
                "layer": "nemo"}

    def check_output(self, answer: str) -> dict:
        rails = _rails(self.backend, self.model)
        res = rails.generate(
            messages=[{"role": "user", "content": "(answer)"},
                      {"role": "assistant", "content": answer}],
            options={"rails": ["output"]})
        blocked = _is_refusal(_content(res))
        return {"allowed": not blocked,
                "reason": "blocked by NeMo output rail" if blocked else "",
                "layer": "nemo"}
