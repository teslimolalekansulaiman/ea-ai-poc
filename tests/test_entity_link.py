"""A question worded 'Oracle Database' reaches the graph's 'Oracle DB': the index proposes,
the model chooses, the code checks, and the templates seed from everything chosen."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eawiki import embed as embmod  # noqa: E402
from eawiki import entity_index as ei  # noqa: E402
from eawiki.query import graphquery as gq  # noqa: E402
from eawiki.query import link as lk  # noqa: E402

GRAPH = {
    "nodes": [
        {"node_id": "oracle-db", "name": "Oracle DB", "type": "physical_technology_component"},
        {"node_id": "oracle-database", "name": "Oracle Database", "type": "element"},          # no links
        {"node_id": "oracle-database-11", "name": "Oracle Database 11", "type": "physical_technology_component"},
        {"node_id": "crm", "name": "Core CRM", "type": "physical_application_component"},
        {"node_id": "hr", "name": "HR Portal", "type": "physical_application_component"},
        {"node_id": "lib", "name": "Library System", "type": "physical_application_component"},
    ],
    "edges": [
        {"source": "crm", "target": "oracle-db", "relation": "is_deployed_on"},
        {"source": "hr", "target": "oracle-db", "relation": "is_deployed_on"},
        {"source": "lib", "target": "oracle-database-11", "relation": "is_deployed_on"},
    ],
}


def _graph():
    return gq._Graph(GRAPH["nodes"], GRAPH["edges"], {})


class _SynonymEmbedder(embmod.HashingEmbedder):
    """Bag of words that treats 'database' as 'db', so the test can exercise the plumbing the way a
    real embedding model would bridge the two words (the hashing embedder alone has no semantics)."""
    model = "test-synonyms"

    def encode(self, texts):
        return super().encode([t.lower().replace("database", "db") for t in texts])


def _index():
    emb = _SynonymEmbedder(256)
    return ei.build_index(GRAPH, emb, Path(tempfile.mkdtemp()) / "v.npz"), emb


def test_shortlist_offers_the_connected_variant_and_the_empty_one():
    idx, emb = _index()
    q = emb.encode(["Oracle Database"])[0]
    ids = [i for i, _ in idx.nearest_nodes(q, 3)]
    assert set(ids) == {"oracle-db", "oracle-database", "oracle-database-11"}   # not the applications


def test_ids_are_checked_flags_are_computed_and_templates_seed_from_all_chosen():
    g = _graph()
    idx, emb = _index()
    stub = lambda prompt, backend, model: {                       # noqa: E731
        "rewritten": "Which applications are deployed on Oracle DB?",
        "entities": [{"mention": "Oracle Database", "ids": ["oracle-database", "oracle-db", "oracle-database-11", "not-a-node"],
                      "why": "same product"}],
        "considered_but_rejected": [{"id": "crm", "why": "an application"}]}
    res = lk.link("Which applications break if we retire Oracle Database?", graph=g, index=idx,
                  embed=lambda q: emb.encode([q])[0], llm=stub)
    ent = res["entities"][0]
    assert "not-a-node" not in ent["ids"]                          # an invented id is dropped
    assert ent["ids"][0] == "oracle-db"                            # most connected first
    assert res["uncertain"] and "a chosen entity has no links" in res["flags"]
    assert "Interpreted as: Which applications are deployed on Oracle DB?" in res["note"]
    with lk.seeded(res):
        assert g.resolve("Oracle Database") == "oracle-db"
        r = gq.impact(g, "Oracle Database", "in")
    assert {"crm", "hr", "lib"} <= {n["id"] for n in r["nodes"]}   # all three applications reached
    plain = {n["id"] for n in gq.impact(g, "Oracle Database", "in")["nodes"]}
    assert "crm" not in plain and "hr" not in plain              # without linking, "Oracle DB" is missed


def test_no_link_when_the_model_names_nothing_real():
    g = _graph()
    idx, emb = _index()
    stub = lambda *a: {"rewritten": "x", "entities": [{"mention": "m", "ids": ["ghost"]}]}   # noqa: E731
    assert lk.link("anything about oracle", graph=g, index=idx, embed=lambda q: emb.encode([q])[0], llm=stub) is None


def test_without_an_index_every_linked_entity_is_offered():
    g = _graph()
    ids, _ = lk.candidates("Oracle Database", g, None, None)
    assert "oracle-database" not in ids and "oracle-db" in ids      # edgeless entities are not offered


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
