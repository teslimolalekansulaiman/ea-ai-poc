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
