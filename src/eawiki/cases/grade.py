"""A grade for a recommendation, worked out in code from what the case holds.

A model asked "how confident are you?" returns a word with nothing behind it, and an architect cannot argue with
it. This reads the cells instead: is the headline answer decided, does it stand on a cited source from the knowledge
base, and is anything it rests on (this stage and the stages before it) still open. The reasons are returned with
the grade, so the screen can say "Medium, because two things are not confirmed" and name them.

    Low     the headline answer is not decided; or something it rests on is open and it cites no source of its own
    Medium  something it rests on is open; or nothing in the whole assessment cites a source from the knowledge base
    High    the headline answer is decided, nothing it rests on is open, and the assessment cites a source

A column is graded in code when the use case sets `graded` on it; its pick list must hold High, Medium and Low.
"""

from __future__ import annotations

from typing import Optional

OPEN = ("needs_input", "needs_source")
LEVELS = ("High", "Medium", "Low")
OWN = ("demand:", "decided:")          # a citation of the demand's own words, or of an earlier answer: not a source


def scale(col: dict) -> Optional[dict]:
    """The pick-list word for each level, or None when the list lacks one."""
    words = {v.casefold(): v for v in col.get("values") or [] if isinstance(v, str)}
    return {lv: words[lv.casefold()] for lv in LEVELS} if all(lv.casefold() in words for lv in LEVELS) else None


def _sources(cell: Optional[dict]) -> list:
    return [e for e in (cell or {}).get("evidence") or [] if not str(e).startswith(OWN)]


def grade(headline: Optional[dict], cells: list[tuple[str, dict]]) -> dict:
    """{"level": High|Medium|Low, "why": [sentences]}.
    `headline` is the cell the stage is about (its row tag); `cells` is (label, cell) for everything it rests on."""
    open_ = [label for label, c in cells if c.get("status") in OPEN]
    n_sourced = sum(1 for _l, c in cells if _sources(c))
    if headline is None or headline.get("status") != "answered":
        return {"level": "Low", "why": ["The recommendation itself is not decided."]}
    own = _sources(headline)
    why = [f"The recommendation cites {len(own)} source{'s' if len(own) != 1 else ''} from the knowledge base." if own
           else "The recommendation cites no source from the knowledge base; it rests on the demand's words and earlier answers."]
    if open_:
        why.append(f"{len(open_)} thing{'s' if len(open_) != 1 else ''} it rests on {'are' if len(open_) != 1 else 'is'} not confirmed: "
                   + ", ".join(open_[:6]) + (f" and {len(open_) - 6} more" if len(open_) > 6 else "") + ".")
        return {"level": "Medium" if own else "Low", "why": why}
    if n_sourced == 0:
        why.append("No answer in this assessment cites a source from the knowledge base.")
        return {"level": "Medium", "why": why}
    why.append("Nothing it rests on is open.")
    return {"level": "High", "why": why}
