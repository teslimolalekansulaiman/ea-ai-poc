# Demand use case, Phase 2 (Recommendation): proposed wording, version 2

For review. Nothing here is applied yet. This **replaces** the earlier design of one message per demand.

## The design

- A request with more than one demand is a group. It gets **one recommendation, in one draft**, approved once. Each demand is still addressed separately inside it.
- The audience is the **requester** who sent the request. Each demand's section is **100 to 150 words**; the overview is 60 to 120. There is no cap on the number of demands.
- Demands that ask for the same thing are **placed together** in the draft under a "Combined" heading, the lead first. The others follow in the order they came in the sheet.
- Findings stay **per demand**, because they differ: Overlaps with, Consolidate with demand(s), Contract / licence match, Security fit, Recommendation type, Recommended owner, Risks and conditions, Next steps.
- Two properties write the draft, in this order, after all the findings:
  1. **Recommendation**, per demand: that demand's section.
  2. **Request overview**, once per request: the opening. It sees every demand's findings and sections.
- **Handled with** is worked out in code, not by the model: the consolidation answers must agree both ways (if A names B, B names A, or the architect is asked), and the earliest submitted demand leads. Both the sections and the overview read it, so they agree.

## How the draft is put together (by code)

1. Request overview.
2. For each group of combined demands: a "Combined: ..." heading, then the lead's section, then the others'.
3. Each other demand, in sheet order: its section.
4. For the architect, not sent: each demand's findings, what is still to confirm, and the evidence.

The download holds parts 1 to 3 only.

## Handled with (new, per demand, worked out in code)

Description:
> Whether this demand is handled together with others in the request, and which of them leads. Worked out in code, not by the model: from the consolidation answers, which must agree both ways, with the earliest submitted demand leading by default. It reads "Alone", or "Combined with D-2026-003; lead: D-2026-001".

## Recommendation (per demand: that demand's section)

Description:
> This demand's section of the recommendation to the requester: 100 to 150 words, in plain language, written to the requester as "you". It is a draft for the architect to read, edit and approve as part of the request's one recommendation.

How to resolve:
> You are a senior enterprise architect writing the architecture team's recommendation to the requester. Lead with the decision. Weigh what is gained and what is risked, say what you would not do and why, and be direct about what is not settled. Use judgement where it follows from the answers; do not state a fact that is not in them. Write in plain language that someone who is not an architect can follow: no jargon, and no catalogue codes except the IDs the answers give.
>
> Write this demand's section only, 100 to 150 words, to the requester, from the architecture team. Use only what this assessment found for this demand and, where "Handled with" says it is combined, for the demands it is combined with. Plain text only, with no symbols or markdown. Write these parts as short paragraphs. The first has no heading; each of the others has a short heading on a line of its own:
> 1. The recommendation (no heading): this demand's recommendation type and what to do, in one or two sentences. If the demand is handled with others, say so first. For the lead: which demands are combined into it and what that changes. For any other: that it should not be raised on its own, and that the work continues under the lead, named.
> 2. Why: two or three sentences: what it overlaps with, the contract and licence match, and the security fit, with the IDs exactly as the answers give them. Add, from the screening, whatever bears on the way forward: the deadline and urgency, the data classification, and any conflict with the architecture principles and standards.
> 3. Risks and conditions: from the property of that name, at most two lines.
> 4. Next steps: from the property of that name, a numbered list of at most three.
>
> Say plainly what is not yet confirmed. Do not add a fact, an ID, a date, a name, a cost or a regulation that is not in the answers or the sources. Do not recommend new business capabilities. Write roles, never personal names. Do not state a grade or a confidence level. If the recommendation type is not decided, say what is needed instead of writing the section.

Builds on: every finding of this demand, and Handled with. Sees, for the other demands: Recommendation type, Recommended owner and Handled with.

## Request overview (new, once per request, written last)

Description:
> The opening of the request's recommendation: how the request as a whole should be handled, in plain language, written to the requester. The demands' own sections follow it.

How to resolve:
> You are a senior enterprise architect writing the architecture team's recommendation to the requester. Lead with the decision. Weigh what is gained and what is risked, say what you would not do and why, and be direct about what is not settled. Use judgement where it follows from the answers; do not state a fact that is not in them. Write in plain language that someone who is not an architect can follow: no jargon, and no catalogue codes except the IDs the answers give.
>
> Write 60 to 120 words of plain text, with no symbols or markdown, to the requester, from the architecture team. Say how many demands the request holds and the overall recommendation, in a sentence or two. Name which demands are handled together and which one leads each group. If the demands should be done in an order, or share a risk or a step, say which and why. Use only the answers shown for the demands of this request. Do not repeat the demands' sections; they follow. Say plainly what is not yet confirmed. Do not add a fact, an ID, a date, a name, a cost or a regulation that is not in the answers or the sources. Do not recommend new business capabilities. Write roles, never personal names. Do not state a grade or a confidence level. If the recommendation type is not decided, say what is needed instead of writing the section.

Builds on: every demand's findings and Handled with.

## Unchanged

Overlaps with, Contract / licence match, Security fit, Recommended owner, Recommendation type (renamed from "Recommendation"), Risks and conditions, Next steps, Consolidate with demand(s): wording as in the earlier version and in the repo. Consolidate with demand(s) now only proposes the merge; the agreement check and the lead are in code.

## Sample of one demand's section (illustrative)

> D-2026-201 · Send evaluation results to payroll
>
> We recommend enhancing the existing link between the HR & Payroll Portal, which hosts Evaluate, and the Payroll System, rather than raising a new demand.
>
> Why
> Both systems already exist (As-Is catalogue 4.19 and 4.29), and Evaluate is built in-house with no third-party licence. The data is classified Internal, and your target date of 31 March 2027 is realistic for an enhancement.
>
> Risks and conditions
> The cyber team has not confirmed access control for the interface. Evaluate is listed as "Not in use", so its status needs confirming.
>
> Next steps
> 1. The portal owner confirms Evaluate's status.
> 2. The cyber team reviews access control for the interface.
> 3. Architecture confirms once the security fit is settled.

## What the code must support (to build)

1. A request scope for a property (written once, not per demand), and the request's own cells.
2. A property worked out in code ("Handled with"): agreement of the consolidation answers, and the lead.
3. One draft per request: assembly in the order above, one approval, one download.
