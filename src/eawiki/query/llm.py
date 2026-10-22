"""LangChain-compatible LLM over our pluggable backend.

Both LangGraph nodes and NeMo Guardrails take a LangChain LLM; this wraps the single
`subjects.llm_text` call (claude -p locally, Pulse/OpenAI-compatible via env in prod) so
there is still ONE place the model backend is chosen. No LangChain provider SDK needed.
"""

from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.language_models.llms import LLM

from eawiki.subjects import llm_text


class BackendLLM(LLM):
    """A minimal LangChain LLM that delegates to eawiki.subjects.llm_text."""

    backend: str = "cli"
    model: Optional[str] = None

    @property
    def _llm_type(self) -> str:
        return f"eawiki-{self.backend}"

    def _call(self, prompt: str, stop: Optional[List[str]] = None,
              run_manager: Any = None, **kwargs: Any) -> str:
        return llm_text(prompt, self.backend, self.model)
