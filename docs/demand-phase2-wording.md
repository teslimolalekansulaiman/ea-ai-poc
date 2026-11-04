# Demand use case, Phase 2 (Recommendation): proposed wording

For review. Nothing here is applied yet. It follows the design agreed in the conversation:

- The draft is the **last** property of Phase 2 (the stage's summary property, like "Screening observation" in Phase 1). It starts only when every other Phase 2 property has finished, and it reads all of Phase 1 and Phase 2.
- The audience is the **requester**. The length is **one page** (about 300 words). The EA reads, edits and approves it.
- The draft has two parts: the **message to the requester**, and **for the architect, not sent** (the findings, what is still to confirm, the evidence).

## What changes in the property list

| Today | Proposed |
|---|---|
| Recommendation (five-word label) | renamed **Recommendation type** (still the stage's tag, and what Confidence is graded from) |
| Recommended action | removed (becomes the message) |
| Justification | removed (becomes the "Why" paragraph of the message) |
| (none) | **Risks and conditions** (list) |
| (none) | **Next steps** (list) |
| (none) | **Recommendation** (text, the stage's summary property: the message to the requester) |
| Overlaps with, Contract / licence match, Security fit, Recommended owner | unchanged (wording already in the repo) |
| Consolidate with demand(s) | wording changes: it now also reads the other demands' screening answers |
| Confidence (graded in code), Evidence | unchanged |

Run order: Overlaps with, Consolidate with demand(s), Contract / licence match, Security fit; then Recommendation type, Recommended owner, Risks and conditions, Next steps; last, Recommendation.

## Stage instructions (Recommendation)

> Check overlap with existing solutions (components, platforms, applications, APIs, prior or running initiatives) and with other demands (consolidate). Check the contract register for licences and renewals that could cover it. Confirm the security fit before recommending reuse. Decide the way forward and the owner, and name the risks and the next steps. The last property, Recommendation, is the message to the requester: it is written only after all the others are done, from them and from the screening. Do NOT recommend new business capabilities. Answer only what the knowledge base supports; for anything it does not, say what is needed.

## Consolidate with demand(s) (changed)

Description:
> Other demands in this request that should be handled together with this one because they ask for the same need, for the same users, on the same systems. Their demand IDs, or None.

How to resolve:
> Compare this demand with the screening answers of the other demands in this request (the duplicate answers, the impacted applications and the impacted capabilities), which are listed for you. Write only demand IDs that appear in this request, never one invented or taken from outside it. A match needs the same need and the same systems, not the same words. None when no other demand matches. If the screening left the duplicate question open, say that instead of writing None.

## Recommendation type (renamed from "Recommendation"; wording unchanged)

Values: Reuse, Enhancement, Merge/CR, Link new artefacts, Onboard new requirement. Builds on: Overlaps with, Consolidate with demand(s), Contract / licence match, Security fit. The description and how-to-resolve already in the repo stay as they are.

## Risks and conditions (new, list)

Description:
> What could stop or change this recommendation, one item per line: what is not yet confirmed, what must be true before it goes ahead, and what it depends on. Each item says who has to confirm it, as a role.

How to resolve:
> Take them from what is open in this assessment: a security fit that is not confirmed, a contract or licence that was not checked, an overlapping solution whose status is unclear (for example one listed as not in use), a dependency on something that is only proposed or has no initiative ID, and anything the screening left open. One short line each, with the ID of the solution or contract it concerns. Do not add a risk that none of the answers or sources supports. None when nothing is open.

Builds on: Overlaps with, Consolidate with demand(s), Contract / licence match, Security fit, Recommendation type.

## Next steps (new, list)

Description:
> What happens next, in order, one item per line, each with the role that does it. Where the requester has something to do, that step says so.

How to resolve:
> Write the steps that follow from the recommendation type and from the risks above: confirming a status with an owner, a review by the security team, a contract check, combining with another demand, raising a change request. Each names a role taken from the Owners answer or from the Recommended owner, never a person's name. Order them so the first one unblocks the rest. Do not invent a process, a date or a team; if no owner is recorded, say whose confirmation is needed. For a demand that should be combined with another, the first step is to continue under that demand.

Builds on: Recommendation type, Recommended owner, Risks and conditions.

## Recommendation (new, text, the stage's summary property)

Description:
> The recommendation to the requester, as the architecture team would write it: one page, in plain language, written to the requester as "you". It is a draft for the architect to read, edit and approve.

How to resolve:
> Write one message of about 300 words at most, to the requester, from the architecture team. Use only what this assessment found: the request's own fields, the screening answers, and the answers of this phase. Write these parts, as short paragraphs under their own headings:
>
> 1. **Recommendation**: the recommendation type in a sentence or two, and what to do. If another demand covers the same need, say not to raise a new one and name it. If an existing solution covers it, name it and say what to extend.
> 2. **What you asked for**: one sentence, from the request's need and expected outcome, in your own words and not copied.
> 3. **Why**: what it overlaps with, the contract and licence match, any demand to combine it with, and the security fit, with the IDs exactly as the answers give them.
> 4. **Risks and conditions**: from the property of that name, kept short.
> 5. **Next steps**: from the property of that name, as a numbered list.
>
> Say plainly what is not yet confirmed. Do not add a fact, an ID, a date, a name, a cost or a regulation that is not in the answers or the sources. Do not recommend new business capabilities. Write roles, never personal names. Do not state a grade or a confidence level. If the recommendation type is not decided, say what is needed instead of writing a message.

Builds on: every other Phase 2 property (Overlaps with, Consolidate with demand(s), Contract / licence match, Security fit, Recommendation type, Recommended owner, Risks and conditions, Next steps).

## Stage settings

- Summary property: **Recommendation** (today: Justification).
- Tag (row tag): **Recommendation type** (today: Recommendation).
- Draft document: headline text = **Recommendation**; key line = **Recommended owner**.
- Draft parts (needs a small new setting): the first part, **Message to the requester**, is the headline text. The second part, **For the architect: not sent**, holds the findings (Overlaps with, Consolidate with demand(s), Contract / licence match, Security fit), what is still to confirm, and the evidence.

## Needs a code change (not wording)

1. A document setting that chooses which properties appear as sections, and the two parts.
2. The other demands' screening answers made visible to "Consolidate with demand(s)".
3. When an answer changes after the draft was written, rewrite the draft, unless the architect has already edited it, and say so on screen.
