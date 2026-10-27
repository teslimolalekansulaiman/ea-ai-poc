"""The test knowledge base as the tools the case engine reads: search (lexical stand-in), the graph, the pages, the finder's list."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import kb_fixture as kb  # noqa: E402

from eawiki.cases import gather as gmod  # noqa: E402
from eawiki.query import graphquery as gq  # noqa: E402


class FixtureKB:
    def entities(self):
        return kb.NODES

    def graph(self):
        nodes, edges = kb.graph_parts()
        return gq._Graph(nodes, edges, {})

    def page(self, slug):
        return kb.page(slug)

    def wiki_entries(self):
        return kb.page_entries()


def make_tools(llm_json=None, llm_text=None) -> gmod.Tools:
    """The search is lexical: it tests the plumbing and the marking, not the quality of embeddings (the real one is a vector search)."""
    return gmod.Tools(search=kb.search, blocks_by_ids=lambda ids: [dict(b) for b in kb.BLOCKS if b["block_id"] in ids], link=lambda t: {},
                      graph_facts=lambda ids: {}, llm_json=llm_json or (lambda p: None), doc_ids=lambda: list(kb.DOCS), llm_text=llm_text, kb=FixtureKB())
