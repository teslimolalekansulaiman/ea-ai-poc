"""Candidate duplicate entities found by MEANING of their names.

The string rules in `dedupe` compare spellings, so "Oracle DB" and "Oracle Database" (word
overlap 0.5, no shared neighbour) are never even compared. Here every entity name is embedded
with the same embedder the search index uses, and close pairs are proposed. This only PROPOSES
candidates: whether two names are the same thing is decided afterwards (the Tier-3 adjudicator,
or a human override), because a vector cannot tell "Endpoint detection" from "Network detection".

Vectors are cached on disk, keyed by embedding model + name, so a re-run embeds only new names.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _load(path: Path) -> dict[str, np.ndarray]:
    if not path.exists():
        return {}
    try:
        z = np.load(path, allow_pickle=False)
        return {str(k): v.astype(np.float32) for k, v in zip(z["keys"], z["vecs"])}
    except Exception:
        return {}


def _save(path: Path, cache: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted(cache)
    np.savez_compressed(path, keys=np.array(keys),
                        vecs=np.stack([cache[k] for k in keys]).astype(np.float16))


def embed_names(names: list[str], embedder, cache_dir: Path) -> np.ndarray:
    """One unit-length vector per name (rows follow `names`), embedding only what is not cached."""
    path = Path(cache_dir) / "vectors.npz"
    cache = _load(path)
    model = getattr(embedder, "model", "?")
    ck = [f"{model}|{n}" for n in names]
    missing = sorted({n for n, k in zip(names, ck) if k not in cache})
    if missing:
        vecs = embedder.encode(missing)
        for n, v in zip(missing, vecs):
            cache[f"{model}|{n}"] = np.asarray(v, dtype=np.float32)
        _save(path, cache)
    out = np.stack([cache[k] for k in ck]).astype(np.float32)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(norms == 0, 1.0, norms)


def similar_pairs(keys: list[tuple], vecs: np.ndarray, threshold: float = 0.85,
                  top_k: int = 3, chunk: int = 512) -> list[tuple]:
    """[(key_a, key_b, cosine)] for names that are close in meaning and could be the same kind
    of thing: the same type, or one side the generic `element` (type unknown). Each entity
    contributes at most `top_k` partners."""
    n = len(keys)
    types = [k[1] for k in keys]
    found: dict[tuple, float] = {}
    for lo in range(0, n, chunk):
        sims = vecs[lo:lo + chunk] @ vecs.T
        for r in range(sims.shape[0]):
            i = lo + r
            row = sims[r]
            order = np.argsort(-row)
            taken = 0
            for j in order:
                j = int(j)
                if row[j] < threshold or taken >= top_k:
                    break
                if j == i or keys[j][0] == keys[i][0]:
                    continue                      # itself, or same name (handled by the type rules)
                ti, tj = types[i], types[j]
                if ti != tj and "element" not in (ti, tj):
                    continue
                pair = (i, j) if i < j else (j, i)
                found[pair] = max(found.get(pair, 0.0), float(row[j]))
                taken += 1
    return sorted(((keys[i], keys[j], s) for (i, j), s in found.items()),
                  key=lambda p: -p[2])
