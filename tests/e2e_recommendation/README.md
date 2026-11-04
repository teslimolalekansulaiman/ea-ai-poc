# The EA's draft recommendation, in a real browser

Opt-in, like the other `e2e_*` scripts: it needs Playwright (Node) and a built UI, and is not part of the pytest suite.

```
cd ui && npm run build && cd ..
python tests/e2e_recommendation/serve.py &       # the real backend, with stand-in model answers for the Recommendation phase
node tests/e2e_recommendation/drive.js           # OUT=<folder> keeps the screenshots (default: the system temp folder)
```

It starts a case from the sample sheet, approves the screening, and then checks, in Chromium: the drafts appear when the phase is done
and are in view without scrolling; one tab per demand and "N of M approved"; the headline is the message to the requester, and the findings, risks and next steps are in a
separate part, "For the architect, not sent"; "How was this decided?" opens a read-only trail (what was done, the sources it cites, the model's note marked as unchecked) and closes again; no confidence is shown; an edit is saved and marked as edited; approving locks the draft and moves the count;
a return needs a note and shows it; a returned draft can be reopened; the download is a page that holds the message only; and a reload keeps what was decided.

The model answers are a stand-in: this checks the screen and the plumbing, not the quality of a real model's recommendation.

## The update on the Config screen

```
PORT=8767 EA_E2E_OLD_SECOND_STAGE=1 python tests/e2e_recommendation/serve.py &     # the use case as a database copy from before the update holds it
PORT=8767 node tests/e2e_recommendation/drive_update.js
```

It opens Config, Edit, History, and checks that the shipped update is listed with what it would do and which of the owner's wording it keeps;
applies it; checks the stored use case (new properties, the message as the summary property, documents mode); and that a case started
afterwards shows Recommendation as documents. Both servers work on a temporary copy of `use_cases/`, so nothing is written into the repo.
