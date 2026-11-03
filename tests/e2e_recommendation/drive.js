// Drives the EA's draft recommendation review in a real browser against serve.py: see README.md.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const ROOT = path.resolve(__dirname, '../..');
const OUT = process.env.OUT || require('os').tmpdir();
const ORIGIN = `http://127.0.0.1:${process.env.PORT || 8766}`;
const shot = (page, n) => page.screenshot({ path: path.join(OUT, 'recommendation-' + n + '.png') });
let failed = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  // a case from the sample sheet, started the way the screen starts one
  const csv = fs.readFileSync(path.join(ROOT, 'use_cases/samples/demand-management-inputs.csv'));
  const parsed = await (await page.request.post(`${ORIGIN}/api/cases/parse-file?use_case_id=demand-management`,
    { multipart: { file: { name: 'd.csv', mimeType: 'text/csv', buffer: csv } } })).json();
  const made = await (await page.request.post(`${ORIGIN}/api/cases`,
    { data: { use_case_id: 'demand-management', items: parsed.items, name: 'EA review check' } })).json();
  await page.goto(`${ORIGIN}/#/cases/${made.id}`);

  // phase 1 finishes and waits for review; approving it starts the recommendation
  const approve1 = page.locator('button:has-text("Approve and continue to")');
  await approve1.waitFor({ timeout: 30000 });
  await approve1.click();
  await page.waitForSelector('.rd', { timeout: 30000 });
  check(true, 'the draft recommendations appear once the phase is done');
  check(/0 of 3 approved/.test(await page.innerText('.rd h3')), 'the card says how many are approved: ' + (await page.innerText('.rd h3')));
  check((await page.$$('.rd-item')).length === 3, 'one tab per demand');
  check((await page.$$('.rd-item .cs-pill')).length === 0 && /Draft for review/.test(await page.innerText('.rd-sheet')), 'drafts are not labelled on every tab; the open sheet says it once');
  check(/Extend the existing platform/.test(await page.innerText('.rd-rec .rd-text')), 'the headline statement is the recommended action');
  const heads = await page.$$eval('.rd-sec .rd-h', e => e.map(x => x.textContent));
  check(['Overlaps with', 'Contract / licence match', 'Security fit', 'Justification'].every(h => heads.includes(h)), 'the other properties are sections: ' + heads.join(', '));
  const box = await page.locator('.rd-rec').boundingBox();
  check(box && box.y >= 0 && box.y < 800, 'the draft is in view when it opens, without scrolling (top at ' + Math.round(box ? box.y : -1) + 'px)');
  check(!/Confidence/.test(await page.innerText('.rd-sheet')), 'no confidence is shown (it is graded in the table, not signed)');
  await shot(page, '1-draft');

  // how the answer was decided: opened on demand, read-only, with the model's note marked as unchecked
  const why = page.locator('.rd-rec .rd-why');
  check(await why.count() === 1, 'the headline offers "How was this decided?"');
  await why.click();
  await page.waitForSelector('.rd-rec .rd-trail .rd-tr-row');
  const trailText = await page.innerText('.rd-rec .rd-trail');
  check(/What was done/.test(trailText) && /Looked at:/.test(trailText), 'the trail says what was done: ' + trailText.replace(/\s+/g, ' ').slice(0, 90));
  check(/The model's note/.test(trailText) && /not checked by the engine/.test(trailText), "the model's note is labelled as unchecked");
  check(await page.locator('.rd-rec .rd-trail .cs-cite').count() > 0, 'the sources it cites are listed as buttons');
  await shot(page, '1b-how-decided');
  await why.click();
  check(await page.locator('.rd-rec .rd-trail').count() === 0, 'it closes again');

  // edit any text; the original is kept
  await page.click('.rd-sheet button:has-text("Edit")');
  await page.fill('.rd-lead', 'Do not raise a new demand. Merge it into the HR platform.');
  await page.setViewportSize({ width: 1360, height: 2200 });                                                      // a tall window, so the whole sheet shows
  await page.locator('.rd-sheet').screenshot({ path: path.join(OUT, 'recommendation-2a-editing.png') });         // the whole sheet, in edit mode
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.click('button:has-text("Save text")');
  await page.waitForSelector('.rd-note:has-text("Edited by the architect")');
  check(/Merge it into the HR platform/.test(await page.innerText('.rd-rec .rd-text')), 'an edit is saved and shown, and marked as edited');
  await shot(page, '2-edited');
  await page.setViewportSize({ width: 1360, height: 2200 });
  await page.locator('.rd-sheet').screenshot({ path: path.join(OUT, 'recommendation-2b-saved.png') });
  await page.setViewportSize({ width: 1360, height: 900 });

  // approve: locked
  await page.click('.rd-actions button:has-text("Approve")');
  await page.waitForSelector('.rd-banner.ok');
  check(/Approved/.test(await page.innerText('.rd-banner.ok')) && !(await page.$('.rd-sheet button:has-text("Edit")')), 'approving locks the draft (no Edit button)');
  check(/1 of 3 approved/.test(await page.innerText('.rd h3')), 'the count moves: ' + (await page.innerText('.rd h3')));
  await shot(page, '3-approved');

  // return another with a note, then reopen it
  await (await page.$$('.rd-item'))[1].click();
  await page.click('.rd-actions button:has-text("Return with a note")');
  const send = page.locator('button:has-text("Return it")');
  check(await send.isDisabled(), 'a return needs a note (the button waits for one)');
  await page.fill('#rd-note', 'Name the licence owner first.');
  await send.click();
  await page.waitForSelector('.rd-banner.crit');
  check(/Name the licence owner first\./.test(await page.innerText('.rd-banner.crit')), 'a returned draft shows its note');
  await shot(page, '4-returned');
  await page.click('button:has-text("Reopen as a draft")');
  await page.waitForSelector('.rd-actions button:has-text("Approve")');
  check(true, 'a returned draft can be reopened');

  // the download is a page
  const href = await page.getAttribute('.rd-dl', 'href');
  const dl = await page.request.get(ORIGIN + href);
  check(dl.ok() && /attachment/.test(dl.headers()['content-disposition'] || '') && /<!doctype html>/i.test(await dl.text()), 'the download is a page');

  // a reload keeps what was decided
  await page.reload();
  await page.waitForSelector('.rd');
  check(/1 of 3 approved/.test(await page.innerText('.rd h3')), 'a reload keeps the approval');

  check(errors.length === 0, 'no errors in the browser console' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('DRIVER ERROR', e); process.exit(2); });
