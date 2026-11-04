# The request screen, in a real browser

Opt-in, like the other `e2e_*` scripts: it needs Playwright (Node) and a built UI, and is not part of the pytest suite.

```
cd ui && npm run build && cd ..
python tests/e2e_request_chat/serve.py &        # the real backend, with a rule-based stand-in for the model
node tests/e2e_request_chat/drive.js            # OUT=<folder> keeps the screenshots (default: the system temp folder)
```

It checks, in Chromium: a typed message starts a request and the conversation, all inside one chat column (no second screen or form);
the page address names the request and a reload continues it; with too many open questions the chat lists them and offers three
routes (one by one, attach a file, ask the requesters for all of these); "What I have so far" shows where each value came from, the
exact words behind it, and lets a value be corrected by clicking it; one message about everything fills what it states; the open
questions are an answer sheet: pages with a dot for each, an answer box (or buttons for a pick list) on every page, Back, Next and a dot to
reach any of them, drafts kept while swiping, nothing sent until the one button ("Send N answers") is pressed, and a single message in the
thread carrying every answer; typing in the message box answers the question on the page showing; the same at phone width; after answers are sent the agent says what it added and how many are left; when nothing is left the chat offers
to start the case (or to start with the incomplete demands held, and to download the gaps sheet); a sheet with gaps gets a card per
question with the demands it is for, and a file attached mid-conversation fills gaps and names itself; and when nothing is found
the text can still start a case as it is.

The stand-in model is rule-based: it checks the screen and the plumbing, not how well a real model reads. `gaps.csv` is a sheet of
four demands with sponsors and a date missing; `notes.txt` names a sponsor.

## Starting a case five ways

```
python tests/e2e_request_chat/serve.py &
node tests/e2e_request_chat/drive_inputs.js      # OUT=<folder> keeps the screenshots
```

Checks, in Chromium, that a case can be started by **chatting** (a typed message with labelled statements: the demand is found, what it
did not say is asked, the answers go in the sheet, then the case starts), from a **PDF of one demand**, a **PDF of two**, a **sheet of one**
(complete, so no conversation) and a **sheet of two** (the second misses its sponsor and go-live date, so two questions are asked). Each
ends with the case started and its first phase run, with the right number of demands, and then taken on: the screening approved, the recommendation run, and the one draft for the request checked (the overview, a section for each demand, the architect's part apart, the download, one approval). The files are in `inputs/` (rewrite them with
`make_inputs.py`, which needs reportlab and openpyxl).

The stand-in reads labelled statements by rule: it checks reading each kind of file, splitting demands, the questions and the start, not how
well a real model reads a free-form demand.
