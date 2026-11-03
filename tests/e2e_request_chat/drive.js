// Drives the request chat in a real browser against serve.py: see README.md.
const { chromium } = require('playwright');
const path = require('path');
const D = __dirname, OUT = process.env.OUT || require('os').tmpdir(), BASE = `http://127.0.0.1:${process.env.PORT || 8765}/#/cases`;
const shot = (page, n) => page.screenshot({ path: path.join(OUT, 'request-chat-' + n + '.png'), fullPage: false });
let failed = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) failed++; };
const idle = (page) => page.waitForFunction(() => !document.querySelector('.rc-working') && ![...document.querySelectorAll('button')].some(b => b.textContent === 'Reading…'), null, { timeout: 15000 });
const msgs = (page) => page.$$eval('.rc-msgs .cs-msg', els => els.map(e => e.innerText));
const MSG = 'textarea[aria-label="Message"]';
const SPARSE = 'We need a complaint tracking system to log, assign and follow up complaints.';

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 860 } })).newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  const start = async (text) => { await page.goto(BASE); await page.waitForSelector(MSG); await page.fill(MSG, text); await page.click('button:has-text("Send")'); await page.waitForSelector('.rc'); await idle(page); };

  // 1. the start screen
  await page.goto(BASE); await page.waitForSelector(MSG);
  await shot(page, '1-start');

  // 2. a sparse message: everything happens in the chat, and too many open questions are listed, not stepped through
  await start(SPARSE);
  let m = await msgs(page);
  check(/I found 1 demand/.test(m.join('\n')) && /required details are still missing/.test(m.join('\n')), 'the agent says what it found and what is missing, in the chat: ' + (m[1] || m[0] || '').slice(0, 90).replace(/\n/g, ' '));
  check(page.url().includes('request='), 'the address names the request');
  check(!(await page.$('.rc-side')) && !(await page.$('.rq-in[aria-label]')) , 'there is no second screen or form beside the chat');
  check(!!(await page.$('.rc-gaplist')) && await page.locator('.rc-gaplist li').count() > 5, 'many open questions are listed, with the other ways to go on');
  const routes = await Promise.all(['Go through them one by one', 'Attach a file', 'Ask the requesters for all of these'].map(t => page.locator(`.rc-q button:has-text("${t}")`).count()));
  check(routes.every(n => n === 1), 'the three routes are offered');
  await shot(page, '2-list');

  // 3. what I have so far: where a value came from, and the exact words; a value can be corrected by clicking it
  await page.click('.rc-sum > summary');
  const tag = await page.$('.rq-tag'); check(!!tag, 'a value shows where it came from');
  if (tag) { await tag.click(); check(!!(await page.$('.rq-quote')), 'the exact words show on click'); }
  await page.click('.rc-val >> nth=0');
  const field = page.locator('.rc-edit input, .rc-edit textarea, .rc-edit select').first();
  await field.fill('Complaint handling tool'); await page.click('.rc-edit button:has-text("Save")');
  await page.waitForSelector('.rc-val:has-text("Complaint handling tool")');
  check(await page.locator('.rc-dem .cs-pill.user:has-text("You entered")').count() > 0, 'a corrected value is marked as entered by the person');
  await shot(page, '3-summary');
  await page.click('.rc-sum > summary');

  // 4. writing everything in one message fills what it states (read against all that is missing)
  const before = await page.locator('.rc-gaplist li').count();
  await page.fill(MSG, 'Our sponsor is the Chief Financial Officer.'); await page.press(MSG, 'Enter'); await idle(page);
  check(await page.locator('.rc-gaplist li').count() === before - 1 || await page.locator('.rc-q[aria-label="Open question"]').count() === 1, 'one message fills what it states, and the list shrinks');
  m = await msgs(page); check(/Business sponsor: the Chief Financial Officer/.test(m.join('\n')) , 'and the agent says what it added');

  // 5. the answer sheet: swipe through the questions, answer in each page, and send everything once
  await page.click('.rc-q button:has-text("Go through them one by one")'); await page.waitForSelector('.rc-slide');
  const nav = await page.innerText('.rc-qnav');
  const N = await page.locator('.rc-dot').count();
  check(/Question 1 of \d+/.test(nav) && N > 5, 'the questions are pages of one sheet: ' + nav.replace(/\s+/g, ' ').slice(0, 40) + ' (' + N + ' dots)');
  await page.click('button[aria-label="Next question"]');
  check(/Question 2 of/.test(await page.innerText('.rc-qnav')), 'Next moves to the next question');
  await page.click('.rc-dot >> nth=0');
  check(/Question 1 of/.test(await page.innerText('.rc-qnav')), 'a dot jumps to any question');
  await shot(page, '4-sheet');
  await page.setViewportSize({ width: 400, height: 800 }); await shot(page, '4b-sheet-phone'); await page.setViewportSize({ width: 1360, height: 860 });
  const sent0 = (await msgs(page)).length;
  for (let n = 0; n < N; n++) {
    const chip = await page.$('.rc-slide .rc-opts button:not(:has-text("Ask the requester"))');
    if (n === 1) await page.click('.rc-slide button:has-text("Ask the requester")');                          // asks the requester, and moves on
    else if (chip) await chip.click();                                                                         // a pick list answers by a button, and moves on
    else if (n === N - 1) await page.fill('.rc-ans', 'Answer ' + n);                                           // Enter on the last page would send
    else { await page.fill('.rc-ans', 'Answer ' + n); await page.press('.rc-ans', 'Enter'); }
  }
  check(/\d+ ready/.test(await page.innerText('.rc-qnav')) && await page.locator(`button:has-text("Send ${N} answers")`).count() === 1, 'every page answered, and one button to send them all: Send ' + N + ' answers');
  check((await msgs(page)).length === sent0, 'nothing is sent until that button is pressed');
  await page.click('.rc-dot >> nth=0');
  check((await page.inputValue('.rc-ans').catch(() => '')) !== '' || await page.locator('.rc-slide .rc-opts button[aria-pressed="true"]').count() > 0, 'swiping back keeps what was typed on the first page');
  await shot(page, '4c-sheet-filled');
  await page.click(`button:has-text("Send ${N} answers")`); await page.waitForSelector('.rc-ready'); await idle(page);
  m = await msgs(page);
  check(m.length === sent0 + 2 && /Ask the requester/.test(m[m.length - 2]) && /Answer 0/.test(m[m.length - 2]), 'one message in the thread carries every answer, and the agent replies once');
  check(!(await page.$('.rc-slide')), 'every question was answered or asked of the requester');

  // 6. nothing left to ask: the start button is in the chat (a demand asked of the requester is held)
  await page.waitForSelector('.rc-ready');
  const ready = await page.innerText('.rc-ready');
  check(/held for information/.test(ready) && /Start anyway, holding 1 demand/.test(ready) && /Download the gaps sheet/.test(ready), 'the chat offers to start with the incomplete demand held: ' + ready.replace(/\s+/g, ' ').slice(0, 80));
  await shot(page, '5-ready');
  const before2 = (await msgs(page)).length;
  await page.reload(); await page.waitForSelector('.rc'); await idle(page);
  check((await msgs(page)).length === before2, 'a reload continues the same conversation (' + before2 + ' messages)');
  await page.click('button:has-text("Start anyway")'); await page.waitForURL(/#\/cases\/[a-f0-9]{12}$/, { timeout: 15000 });
  await page.waitForSelector('.cs-bar', { timeout: 15000 });
  check(true, 'starting opens the case screen: ' + page.url().split('#')[1]);
  await shot(page, '6-case');

  // 7. ask the requesters for all of these: one button, and nothing is left to ask
  await start(SPARSE);
  await page.click('.rc-q button:has-text("Ask the requesters for all of these")'); await page.waitForSelector('.rc-ready'); await idle(page);
  m = await msgs(page);
  check(/Ask the requesters for all of these/.test(m.join('\n')) && /only the requester can give/.test(m.join('\n')), 'one button asks the requester for everything and the agent says so');
  check(/Start anyway, holding 1 demand/.test(await page.innerText('.rc-ready')), 'and the demand is held, not lost');
  await shot(page, '7-asked-all');

  // 8. a sheet with gaps: few questions, so they are pages straight away; the demands an answer is for can be chosen
  await page.goto(BASE); await page.waitForSelector(MSG);
  await page.setInputFiles('input[type=file]', path.join(D, 'gaps.csv'));
  await page.click('button:has-text("Send")'); await page.waitForSelector('.rc'); await idle(page);
  m = await msgs(page); check(/required details are still missing|missing for|business sponsor/i.test(m.join('\n')), 'a sheet with gaps gets its questions in the chat: ' + (m[0] || '').slice(0, 80).replace(/\n/g, ' '));
  check(await page.locator('.rc-slide').count() === 1 && await page.locator('.rc-dot').count() === 2 && !!(await page.$('.rc-scope')), 'two pages, with the demands each answer is for');
  await shot(page, '8-sheet');

  // 9. attach a file mid-chat: it is read for the gaps and named; then answer what is left, from the sheet
  await page.setInputFiles('.rc input[type=file]', path.join(D, 'notes.txt'));
  await page.click('.rc-comp button:has-text("Send")'); await idle(page);
  m = await msgs(page); check(/from notes\.txt/.test(m.join('\n')), 'a file added mid-chat fills gaps and names itself');
  await page.waitForSelector('.rc-ans'); await page.fill('.rc-ans', '2027-06-30');
  await page.click('button:has-text("Send 1 answer")'); await page.waitForSelector('.rc-ready'); await idle(page);
  check(/Start the case/.test(await page.innerText('.rc-ready')), 'the last answer sent from the sheet leaves nothing to ask');
  await shot(page, '9-attached');

  // 10. text with no demand in it: the exchange stays in the chat, the next message adds to it, and the old way is still there
  await page.goto(BASE); await page.waitForSelector(MSG);
  await page.fill(MSG, 'demand use case'); await page.press(MSG, 'Enter'); await page.waitForSelector('.rc .rc-msgs'); await idle(page);
  m = await msgs(page);
  check(m.length === 2 && /demand use case/.test(m[0]) && /could not find any demands/.test(m[1]), 'text with no demand stays in the chat: your words, then the agent\'s answer');
  check((await page.inputValue(MSG)) === '', 'and the box is cleared, as in any chat');
  await shot(page, '10-nothing-found');
  await page.fill(MSG, 'We need a way to log complaints.'); await page.press(MSG, 'Enter'); await page.waitForSelector('.rc-sum'); await idle(page);
  m = await msgs(page); check(/I found 1 demand/.test(m.join('\n')), 'the next message adds to what was said, and a request starts: ' + (m[m.length - 1] || '').slice(0, 60).replace(/\n/g, ' '));
  await page.goto(BASE); await page.waitForSelector(MSG);
  await page.fill(MSG, 'hello there how are you'); await page.press(MSG, 'Enter'); await page.waitForSelector('.rc-msgs'); await idle(page);
  await page.click('button:has-text("Start the case with my text as it is")'); await page.waitForURL(/#\/cases\/[a-f0-9]{12}$/, { timeout: 15000 });
  check(true, 'and the text can still start a case as it is');

  check(errors.length === 0, 'no errors in the browser console' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('DRIVER ERROR', e); process.exit(2); });
