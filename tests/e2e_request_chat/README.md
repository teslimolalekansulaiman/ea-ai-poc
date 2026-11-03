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
questions are stepped through a card at a time (Back and Next, a pick list by buttons, typing for the rest, "Ask the requester" on
any) and at phone width; after an answer the agent says what it added and how many are left; when nothing is left the chat offers
to start the case (or to start with the incomplete demands held, and to download the gaps sheet); a sheet with gaps gets a card per
question with the demands it is for, and a file attached mid-conversation fills gaps and names itself; and when nothing is found
the text can still start a case as it is.

The stand-in model is rule-based: it checks the screen and the plumbing, not how well a real model reads. `gaps.csv` is a sheet of
four demands with sponsors and a date missing; `notes.txt` names a sponsor.
