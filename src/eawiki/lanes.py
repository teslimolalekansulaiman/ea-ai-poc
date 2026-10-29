"""The kinds of evidence the retrieval merge keeps apart (docs/RETRIEVAL_MERGE_SPEC.md, section 2), and the block types each is made of.

A block of the index has a `btype`. A lane is a set of block types searched on its own, with its own number of results, so that a short
label cannot push a diagram's description out of a search, nor a figure a table. The wiki and the graph are lanes too, but they are not
searched in the vector index and have no block types here.
"""

from __future__ import annotations

LANE_TYPES = {
    "tables": ("table",),
    "figures": ("figure",),
    "text": ("paragraph", "list_item", "caption", "other"),       # headings are not embedded
}
TYPE_FETCH_FACTOR = 30      # a search of one lane fetches this many times what it keeps: the index cannot filter inside the search


def types_of(lane: str) -> tuple[str, ...]:
    """The block types of a vector lane; an unknown lane is an error, never an empty search."""
    try:
        return LANE_TYPES[lane]
    except KeyError:
        raise ValueError(f"unknown lane '{lane}' (expected one of: {', '.join(LANE_TYPES)})") from None


def lane_of(btype: str) -> str:
    """The lane a block type belongs to ('text' for a type that is none of the others)."""
    for lane, types in LANE_TYPES.items():
        if btype in types:
            return lane
    return "text"
