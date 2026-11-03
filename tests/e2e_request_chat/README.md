# The request screen, in a real browser

Opt-in, like the other `e2e_*` scripts: it needs Playwright (Node) and a built UI, and is not part of the pytest suite.

```
cd ui && npm run build && cd ..
python tests/e2e_request_chat/serve.py &        # the real backend, with a rule-based stand-in for the model
node tests/e2e_request_chat/drive.js            # OUT=<folder> keeps the screenshots (default: the system temp folder)
```

It checks, in Chromium: a typed message starts a request and the conversation; the page address names the request and a
reload continues it; where each value came from and the exact words behind it; every question answered by buttons or by typing;
starting the case opens the case screen; a sheet with gaps gets a grouped question with the demands it is for; a file attached
mid-conversation fills gaps and names itself; and when nothing is found the text can still start a case as it is.

The stand-in model is rule-based: it checks the screen and the plumbing, not how well a real model reads. `gaps.csv` is a sheet of
four demands with sponsors and a date missing; `notes.txt` names a sponsor.
