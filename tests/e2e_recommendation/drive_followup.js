// The draft is the message only, and a follow-up question on the case is asked inside the whole case, in a real browser: see README.md.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const ROOT = path.resolve(__dirname, '../..');
const OUT = process.env.OUT || require('os').tmpdir();
const ORIGIN = `http://127.0.0.1:${process.env.PORT || 8766}`;
let failed = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 1000 } })).newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  const csv = fs.readFileSync(path.join(ROOT, 'use_cases/samples/demand-management-inputs.csv'));
  const parsed = await (await page.request.post(`${ORIGIN}/api/cases/parse-file?use_case_id=demand-management`,
    { multipart: { file: { name: 'd.csv', mimeType: 'text/csv', buffer: csv } } })).json();
  const made = await (await page.request.post(`${ORIGIN}/api/cases`, { data: { use_case_id: 'demand-management', items: parsed.items, name: 'Follow-up check' } })).json();
  await page.goto(`${ORIGIN}/#/cases/${made.id}`);
  const approve1 = page.locator('button:has-text("Approve and continue to")');
  await approve1.waitFor({ timeout: 30000 });
  await approve1.click();
  await page.waitForSelector('.rd', { timeout: 30000 });

  // the draft is the message and nothing else
  check((await page.$$('.rd-arch')).length === 0 && !/For the architect, not sent/i.test(await page.innerText('.rd')), 'no part for the architect after the message');
  check(!/Message to the requester/i.test(await page.innerText('.rd-rec')) && /continue under D-2026-001/.test(await page.innerText('.rd-rec .rd-text')), 'the draft opens with the overview of the request');
  check((await page.$$('.rd-sheet > .rd-sec')).length === 3, 'a section for each demand, and nothing after them');
  check(/^Download$/.test((await page.locator('.rd-dl').innerText()).trim()), 'the download is just "Download": there is only the message');
  await page.screenshot({ path: path.join(OUT, 'followup-1-message-only.png') });

  // the follow-up box: each question is asked inside the whole case, with the last five exchanges
  const box = page.locator('textarea, input[type=text]').last();
  const answers = [];
  for (let i = 1; i <= 7; i++) {
    await box.fill(`Follow-up ${i}: who owns it?`);
    await box.press('Enter');
    await page.waitForFunction(n => document.body.innerText.split('STAND-IN ANSWER').length - 1 >= n, i, { timeout: 15000 });
    answers.push((await page.innerText('body')).split('STAND-IN ANSWER').slice(-1)[0].split('\n')[0]);
  }
  check(/request=yes stages=2 drafts=yes/.test(answers[0]), 'the first question has the request, both stages and the drafts: ' + answers[0].trim());
  check(/history=0\b/.test(answers[0]) && /history=2\b/.test(answers[1]), 'it starts with no history and then carries the exchange before it');
  check(/history=10\b/.test(answers[6]) && /history=10\b/.test(answers[5]), 'after that it carries the last five exchanges and no more (' + answers[6].trim() + ')');
  check(/focus=no/.test(answers[0]), 'with no demand open, no demand is named');
  await page.screenshot({ path: path.join(OUT, 'followup-2-thread.png') });
  check(errors.length === 0, 'no script errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? `${failed} FAILED` : 'all passed');
  process.exit(failed ? 1 : 0);
})();
