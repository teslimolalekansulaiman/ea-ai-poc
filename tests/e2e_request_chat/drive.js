// Drives the request screen in a real browser against serve.py: see README.md.
const { chromium } = require('playwright');
const path = require('path');
const D = __dirname, OUT = process.env.OUT || require('os').tmpdir(), BASE = `http://127.0.0.1:${process.env.PORT || 8765}/#/cases`;
const shot = (page, n) => page.screenshot({ path: path.join(OUT, 'request-chat-' + n + '.png'), fullPage: false });
let failed = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) failed++; };
const idle = (page) => page.waitForFunction(() => !document.querySelector('.rc-working') && ![...document.querySelectorAll('button')].some(b => b.textContent === 'Reading…'), null, { timeout: 15000 });
const msgs = (page) => page.$$eval('.rc-msgs .cs-msg', els => els.map(e => e.innerText));

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 860 } })).newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  // 1. the start screen
  await page.goto(BASE); await page.waitForSelector('textarea[aria-label="Message"]');
  await shot(page, '1-start');

  // 2. a typed message starts a request and the conversation
  await page.fill('textarea[aria-label="Message"]', 'We need a complaint tracking system to log, assign and follow up complaints. Our sponsor is the Chief Customer Officer.');
  await page.click('button:has-text("Send")'); await page.waitForSelector('.rc'); await idle(page);
  let m = await msgs(page);
  check(m.length >= 2 && /I found 1 demand/.test(m.join('\n')), 'a typed message starts a request: ' + (m[1] || '').slice(0, 70).replace(/\n/g, ' '));
  check(page.url().includes('request='), 'the address names the request');
  await shot(page, '2-chat');

  // 3. where a value came from, and the exact words
  await page.waitForSelector('.rq-item');
  const tag = await page.$('.rq-tag'); check(!!tag, 'a value shows where it came from');
  if (tag) { await tag.click(); check(!!(await page.$('.rq-quote')), 'the exact words show on click'); }
  await shot(page, '3-provenance');

  // 4. answer the open questions: buttons where there are options, typing where there are none
  for (let i = 0; i < 16 && await page.$('.rc-q'); i++) {
    const opt = await page.$('.rc-opts button:not(:has-text("Ask the requester"))');
    if (opt) { await opt.click(); }
    else { await page.fill('textarea[aria-label="Message"]', 'Answer ' + i); await page.press('textarea[aria-label="Message"]', 'Enter'); }
    await idle(page); await page.waitForTimeout(150);
  }
  check(!(await page.$('.rc-q')), 'every question was answered');
  m = await msgs(page); check(/Everything required is filled in/.test(m[m.length - 1] || ''), 'the agent says it can start: ' + (m[m.length - 1] || '').slice(0, 60));
  await shot(page, '4-ready');

  // 5. reload: the conversation continues from the address
  const before = (await msgs(page)).length;
  await page.reload(); await page.waitForSelector('.rc'); await idle(page);
  check((await msgs(page)).length === before, 'a reload continues the same conversation (' + before + ' messages)');

  // 6. start the case: the case screen takes over
  await page.click('button:has-text("Start the case")'); await page.waitForURL(/#\/cases\/[a-f0-9]{12}$/, { timeout: 15000 });
  await page.waitForSelector('.cs-bar', { timeout: 15000 });
  check(true, 'starting the case opens the case screen: ' + page.url().split('#')[1]);
  await shot(page, '5-case');

  // 7. a sheet with gaps: the conversation asks, grouped across demands
  await page.goto(BASE); await page.waitForSelector('textarea[aria-label="Message"]');
  await page.setInputFiles('input[type=file]', path.join(D, 'gaps.csv'));
  await page.click('button:has-text("Send")'); await page.waitForSelector('.rc'); await idle(page);
  m = await msgs(page); check(/Business sponsor is missing for|What is the business sponsor for/.test(m.join('\n')), 'a sheet with gaps gets a grouped question: ' + (m[0] || '').slice(0, 80).replace(/\n/g, ' '));
  check(!!(await page.$('.rc-scope')), 'the demands the answer is for can be chosen');
  await shot(page, '6-sheet');

  // 8. attach a file mid-chat: it is read for the gaps and named
  await page.setInputFiles('.rc input[type=file]', path.join(D, 'notes.txt'));
  await page.click('.rc-comp button:has-text("Send")'); await idle(page);
  m = await msgs(page); check(/from notes\.txt/.test(m.join('\n')), 'a file added mid-chat fills gaps and names itself');
  await shot(page, '7-attached');

  // 9. the agent could not read the text: the old way is still there
  await page.goto(BASE); await page.waitForSelector('textarea[aria-label="Message"]');
  await page.fill('textarea[aria-label="Message"]', 'hello there how are you');
  await page.click('button:has-text("Send")'); await page.waitForSelector('.rc-note');
  check(/could not find any demands/.test(await page.innerText('.rc-note')), 'when nothing is found, it says so');
  await shot(page, '8-fallback');
  await page.click('button:has-text("Start the case with my text as it is")'); await page.waitForURL(/#\/cases\/[a-f0-9]{12}$/, { timeout: 15000 });
  check(true, 'and the text can still start a case as it is');

  check(errors.length === 0, 'no errors in the browser console' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('DRIVER ERROR', e); process.exit(2); });
