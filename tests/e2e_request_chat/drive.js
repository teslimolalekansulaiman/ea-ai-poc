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

  // 5. go through them one by one: a card per question, stepping, a pick list by buttons, typing for the rest, ask the requester on any
  await page.click('.rc-q button:has-text("Go through them one by one")'); await page.waitForSelector('.rc-q[aria-label="Open question"]');
  const nav = await page.innerText('.rc-qnav');
  check(/Question 1 of \d+/.test(nav), 'the questions are stepped through: ' + nav.replace(/\s+/g, ' ').slice(0, 60));
  await page.click('button[aria-label="Next question"]');
  check(/Question 2 of/.test(await page.innerText('.rc-qnav')), 'Next moves to the next question');
  await page.click('button[aria-label="Previous question"]');
  await shot(page, '4-step');
  await page.setViewportSize({ width: 400, height: 800 }); await shot(page, '4b-step-phone'); await page.setViewportSize({ width: 1360, height: 860 });
  let asked = false;
  for (let i = 0; i < 20 && await page.$('.rc-q[aria-label="Open question"]'); i++) {
    const opt = await page.$('.rc-q[aria-label="Open question"] .rc-opts button:not(:has-text("Ask the requester"))');
    if (opt) await opt.click();
    else if (!asked && i === 1) { await page.click('.rc-q button:has-text("Ask the requester")'); asked = true; }
    else { await page.fill(MSG, 'Answer ' + i); await page.press(MSG, 'Enter'); }
    await idle(page); await page.waitForTimeout(150);
  }
  check(!(await page.$('.rc-q[aria-label="Open question"]')), 'every question was answered or asked of the requester');

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

  // 8. a sheet with gaps: few questions, so they are stepped through; the demands an answer is for can be chosen
  await page.goto(BASE); await page.waitForSelector(MSG);
  await page.setInputFiles('input[type=file]', path.join(D, 'gaps.csv'));
  await page.click('button:has-text("Send")'); await page.waitForSelector('.rc'); await idle(page);
  m = await msgs(page); check(/required details are still missing|missing for|business sponsor/i.test(m.join('\n')), 'a sheet with gaps gets its questions in the chat: ' + (m[0] || '').slice(0, 80).replace(/\n/g, ' '));
  check(!!(await page.$('.rc-q[aria-label="Open question"]')) && !!(await page.$('.rc-scope')), 'a card per question, with the demands it is for');
  await shot(page, '8-sheet');
  await page.click('button:has-text("Answer in one message instead")');
  check(!(await page.$('.rc-q[aria-label="Open question"]')) && /Write everything you know below/.test(await page.innerText('.rc-q')), 'the person can switch to one message about everything');
  await page.click('button:has-text("Answer one at a time")'); await page.waitForSelector('.rc-q[aria-label="Open question"]');
  check(true, 'and back to question by question');

  // 9. attach a file mid-chat: it is read for the gaps and named
  await page.setInputFiles('.rc input[type=file]', path.join(D, 'notes.txt'));
  await page.click('.rc-comp button:has-text("Send")'); await idle(page);
  m = await msgs(page); check(/from notes\.txt/.test(m.join('\n')), 'a file added mid-chat fills gaps and names itself');
  await shot(page, '9-attached');

  // 10. the agent could not read the text: the old way is still there
  await page.goto(BASE); await page.waitForSelector(MSG);
  await page.fill(MSG, 'hello there how are you');
  await page.click('button:has-text("Send")'); await page.waitForSelector('.rc-note');
  check(/could not find any demands/.test(await page.innerText('.rc-note')), 'when nothing is found, it says so');
  await page.click('button:has-text("Start the case with my text as it is")'); await page.waitForURL(/#\/cases\/[a-f0-9]{12}$/, { timeout: 15000 });
  check(true, 'and the text can still start a case as it is');

  check(errors.length === 0, 'no errors in the browser console' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('DRIVER ERROR', e); process.exit(2); });
