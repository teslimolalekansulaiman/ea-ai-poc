# The EA's draft recommendation, in a real browser

Opt-in, like the other `e2e_*` scripts: it needs Playwright (Node) and a built UI, and is not part of the pytest suite.

```
cd ui && npm run build && cd ..
python tests/e2e_recommendation/serve.py &       # the real backend, with stand-in model answers for the Recommendation phase
node tests/e2e_recommendation/drive.js           # OUT=<folder> keeps the screenshots (default: the system temp folder)
```

It starts a case from the sample sheet (three demands, two of which ask for the same thing), approves the screening, and then checks, in
Chromium: one draft for the whole request, not one per demand (no tabs); it opens with the overview; the demands handled together sit under
one "Combined" heading, the lead first, and each demand has its own section; what is for the architect is set apart after them, grouped under
each demand, with what is still to confirm and where the answers about who is combined disagree; no confidence is shown; "How was this
decided?" works for a demand's section and for the overview; an edit is saved and marked and keeps the groups and the architect's part; a
return needs a note and can be reopened; one approval locks the draft; the download is a page that holds the message only, with the group
named; and a reload keeps the approval.

The model answers are a stand-in: this checks the screen and the plumbing, not the quality of a real model's recommendation.

## The update on the Config screen

```
PORT=8767 EA_E2E_OLD_SECOND_STAGE=1 python tests/e2e_recommendation/serve.py &     # the use case as a database copy from before the update holds it
PORT=8767 node tests/e2e_recommendation/drive_update.js
```

It opens Config, Edit, History, and checks that the shipped update is listed with what it would do and which of the owner's wording it keeps;
applies it; checks the stored use case (new properties, each demand's section as the summary property, one draft for the whole request); then runs a
case on it through both phases and checks that it ends in one draft with the overview and a section for each demand. Both servers work on a temporary copy of `use_cases/`, so nothing is written into the repo.

## "Draft the questions" on the Config screen

```
PORT=8768 python tests/e2e_recommendation/serve.py &       # a fresh server: the check saves a lookup into its temporary copy of the use case
PORT=8768 node tests/e2e_recommendation/drive_draft.js
```

Opens Demand Management → Security fit, presses **Draft the questions**, and checks that the stand-in model's proposals are shown with where they
start and why, that one starting from a property that does not exist was left out and said, that nothing is added until **Add this question**,
that adding one that starts from a property of the same stage also makes the property build on it, and that Save keeps the lookup without the
draft's notes. Run it against a fresh server: a second run finds the lookup already there.

## "Draft the questions for every property" of a stage

```
PORT=8769 python tests/e2e_recommendation/serve.py &       # a fresh server again: the check saves into its temporary copy
PORT=8769 node tests/e2e_recommendation/drive_stage_draft.js
```

Opens Demand Management → Stage 1 and drafts the questions of the whole stage: only the properties that had none are drafted, the others are
named and left alone, nothing is stored by drafting, a question can be unticked, and Save keeps the picked ones without the draft's notes.

## The draft is the message only, and a follow-up question on a case

```
PORT=8774 python tests/e2e_recommendation/serve.py &
PORT=8774 node tests/e2e_recommendation/drive_followup.js
```

Starts a case, approves the screening and checks that the draft is the overview and a section for each demand, with nothing kept for the
architect after them. Then it asks seven follow-up questions in the box on the case page. The answer is a stand-in that says what it was
given: the request, both stages and the drafts, and the last five exchanges of the conversation and no more.

`drive.js` checks the architect's part, which the shipped use case no longer has: start `serve.py` with `EA_E2E_ARCHITECT_PART=1` for it.
