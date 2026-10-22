"""Store backend — ArcadeDB client + schema for the EA graph + vectors.

Thin wrapper over ArcadeDB's HTTP API (so no driver dependency), behind a small
surface the loader uses: reset, create_schema, upsert vertices/edges, vector search.
Swapping to another backend (e.g. Neo4j) means another class with the same methods.

Connection is env-configurable (same spirit as the embedder), so local and the GCP
VM differ only by environment:
    EAWIKI_ARCADE_URL   (default http://localhost:2480)
    EAWIKI_ARCADE_DB    (default eawiki)
    EAWIKI_ARCADE_USER  (default root)
    EAWIKI_ARCADE_PASSWORD

Graph model (kept generic on purpose — the metamodel evolves, the DB schema shouldn't):
    vertex Entity { node_id(unique), name, type, aliases[], origins[], attributes }
    vertex Block  { id(unique), block_id, doc_id, btype, section, text, embedding[] }
    edge   REL    { relation, source_count, origins[], evidence[] }   Entity -> Entity
    edge   CITES  { }                                                 Entity -> Block
The relation name lives on REL.relation (queryable); the vector index lives on
Block.embedding, sized from the embeddings meta `dim`.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional


class ArcadeDBStore:
    def __init__(self, url: Optional[str] = None, database: Optional[str] = None,
                 user: Optional[str] = None, password: Optional[str] = None):
        self.base = (url or os.environ.get("EAWIKI_ARCADE_URL", "http://localhost:2480")).rstrip("/")
        self.db = database or os.environ.get("EAWIKI_ARCADE_DB", "eawiki")
        user = user or os.environ.get("EAWIKI_ARCADE_USER", "root")
        password = password or os.environ.get("EAWIKI_ARCADE_PASSWORD", "")
        self._auth = base64.b64encode(f"{user}:{password}".encode()).decode()

    # --- low-level HTTP --------------------------------------------------
    def _post(self, endpoint: str, command: str, params: Optional[dict] = None) -> Any:
        payload: dict = {"language": "sql", "command": command}
        if params:
            payload["params"] = params
        req = urllib.request.Request(
            f"{self.base}/api/v1/{endpoint}/{self.db}",
            data=json.dumps(payload).encode(), method="POST")
        req.add_header("Authorization", f"Basic {self._auth}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read().decode()).get("result")
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:400]
            raise RuntimeError(f"ArcadeDB {endpoint} HTTP {e.code}: {body}\n  SQL: {command[:160]}") from None

    def command(self, sql: str, params: Optional[dict] = None) -> Any:
        return self._post("command", sql, params)

    def query(self, sql: str, params: Optional[dict] = None) -> Any:
        return self._post("query", sql, params)

    def ping(self) -> str:
        return self.query("SELECT 1 AS ok") and "ok"

    # --- schema ----------------------------------------------------------
    def reset(self) -> None:
        """Drop the projection types so the load rebuilds from files (idempotent)."""
        for t in ("CITES", "REL", "Block", "Entity"):
            self.command(f"DROP TYPE {t} IF EXISTS UNSAFE")

    def create_schema(self, dim: int, similarity: str = "COSINE") -> None:
        self.command("CREATE VERTEX TYPE Entity IF NOT EXISTS")
        self.command("CREATE VERTEX TYPE Block IF NOT EXISTS")
        self.command("CREATE EDGE TYPE REL IF NOT EXISTS")
        self.command("CREATE EDGE TYPE CITES IF NOT EXISTS")
        self.command("CREATE PROPERTY Entity.node_id IF NOT EXISTS STRING")
        self.command("CREATE PROPERTY Block.id IF NOT EXISTS STRING")
        self.command("CREATE PROPERTY Block.embedding IF NOT EXISTS LIST OF FLOAT")
        self.command("CREATE INDEX IF NOT EXISTS ON Entity (node_id) UNIQUE")
        self.command("CREATE INDEX IF NOT EXISTS ON Block (id) UNIQUE")
        self._dim, self._sim = dim, similarity

    def create_vector_index(self, dim: int, similarity: str = "COSINE") -> None:
        """Create the HNSW/LSM vector index on Block.embedding (after bulk insert)."""
        self.command(
            f"CREATE INDEX IF NOT EXISTS ON Block (embedding) LSM_VECTOR "
            f"METADATA {{ \"dimensions\": {int(dim)}, \"similarity\": \"{similarity}\" }}")

    # --- data ------------------------------------------------------------
    def insert(self, vtype: str, doc: dict) -> None:
        self.command(f"INSERT INTO {vtype} CONTENT {json.dumps(doc, ensure_ascii=False)}")

    def add_edge(self, etype: str, from_id: str, to_id: str, props: dict,
                 key_from: str = "node_id", from_type: str = "Entity",
                 key_to: str = "node_id", to_type: str = "Entity") -> None:
        sets = f" SET {_set_clause(props)}" if props else ""
        self.command(
            f"CREATE EDGE {etype} "
            f"FROM (SELECT FROM {from_type} WHERE {key_from} = :a) "
            f"TO (SELECT FROM {to_type} WHERE {key_to} = :b){sets}",
            params={"a": from_id, "b": to_id})

    def vector_search(self, query_vec: list[float], k: int = 10) -> list[dict]:
        """k nearest Block vertices to query_vec (expects an embedding of the index dim)."""
        res = self.query(
            "SELECT expand(vector.neighbors('Block[embedding]', :v, :k))",
            params={"v": query_vec, "k": k})
        return res or []


def _set_clause(props: dict) -> str:
    """`k = <json>` pairs for a SET, with values JSON-encoded (safe for our data)."""
    return ", ".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in props.items())
