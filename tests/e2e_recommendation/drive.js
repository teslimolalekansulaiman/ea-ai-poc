// Drives the EA's review of the one recommendation for a whole request, in a real browser against serve.py: see README.md.
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

  // a case from the sample sheet (three demands), started the way the screen starts one
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
  check(true, 'the draft appears once the phase is done');
  check(/One draft for the whole request/.test(await page.innerText('.rd h3')), 'one draft for the request, not one per demand: ' + (await page.innerText('.rd h3')));
  check((await page.$$('.rd-item')).length === 0, 'so there are no tabs');
  check(/Message to the requester/i.test(await page.innerText('.rd-rec')) && /continue under D-2026-001/.test(await page.innerText('.rd-rec .rd-text')), 'it opens with the overview of the whole request');

  // a section for each demand; the ones that ask for the same thing sit together under one heading, the lead first
  const groups = await page.$$eval('.rd-group', e => e.map(x => x.textContent));
  check(groups.length === 1 && groups[0] === 'Combined: D-2026-001, D-2026-003', 'the demands handled together have one heading: ' + groups.join(' | '));
  const heads = await page.$$eval('.rd > div .rd-sheet > .rd-sec .rd-h, .rd-sheet > .rd-sec .rd-h', e => e.map(x => x.textContent));
  check(heads.length === 3 && /^D-2026-001 · /.test(heads[0]) && /^D-2026-003 · /.test(heads[1]) && /^D-2026-004 · /.test(heads[2]), 'a section for each demand, the combined ones first: ' + heads.map(h => h.slice(0, 12)).join(', '));
  const firstBody = await page.innerText('.rd-sheet > .rd-sec >> nth=0');
  check(/extend the existing platform to cover D-2026-001/.test(firstBody) && /Risks and conditions/.test(firstBody) && /Next steps/.test(firstBody), 'each section is that demand\'s own recommendation');

  // what is for the architect is apart, after, and says it is not sent
  check(/For the architect, not sent/i.test(await page.innerText('.rd-arch')), 'the architect\'s part is set apart after the sections');
  const apart = await page.$$eval('.rd-arch .rd-sec .rd-h', e => e.map(x => x.textContent));
  const apartDemands = await page.$$eval('.rd-arch .rd-demand', e => e.map(x => x.textContent));
  check(['Security fit', 'Handled with', 'Overlaps with', 'To confirm before approval'].every(h => apart.includes(h)) && ['D-2026-001', 'D-2026-003', 'D-2026-004'].every(d => apartDemands.includes(d)), 'it holds each demand\'s findings under the demand\'s own heading, and what is still to confirm: ' + apartDemands.join(', '));
  check(/D-2026-003 did not name D-2026-001/.test(await page.innerText('.rd-arch')), 'and says where the answers about who is combined disagree');
  check(!/Confidence/.test(await page.innerText('.rd-sheet')), 'no confidence is shown (it is graded in the table, not signed)');
  const box = await page.locator('.rd-rec').boundingBox();
  check(box && box.y >= 0 && box.y < 800, 'the draft is in view when it opens (top at ' + Math.round(box ? box.y : -1) + 'px)');
  await page.setViewportSize({ width: 1360, height: 3000 });
  await page.locator('.rd-sheet').screenshot({ path: path.join(OUT, 'recommendation-1-draft.png') });
  await page.setViewportSize({ width: 1360, height: 900 });

  // how it was decided: for a demand's section, and for the overview
  await page.locator('.rd-sheet > .rd-sec .rd-why').first().click();
  await page.waitForSelector('.rd-sheet > .rd-sec .rd-trail .rd-tr-row');
  const t1 = await page.innerText('.rd-sheet > .rd-sec .rd-trail');
  check(/What was done/.test(t1) && /The model's note/.test(t1) && /not checked by the engine/.test(t1), 'a demand\'s section opens its trail, the model\'s note marked as unchecked');
  await page.locator('.rd-sheet > .rd-sec .rd-why').first().click();
  await page.locator('.rd-rec .rd-why').click();
  await page.waitForSelector('.rd-rec .rd-trail .rd-tr-row');
  check(/What was done/.test(await page.innerText('.rd-rec .rd-trail')), 'the overview opens its own');
  await page.locator('.rd-rec .rd-why').click();

  // edit the overview; the original is kept, the groups and the architect's part stay
  await page.click('.rd-sheet button:has-text("Edit")');
  await page.fill('.rd-lead', 'Do not raise D-2026-003. Continue under D-2026-001.');
  await page.setViewportSize({ width: 1360, height: 3000 });
  await page.locator('.rd-sheet').screenshot({ path: path.join(OUT, 'recommendation-2a-editing.png') });
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.click('button:has-text("Save text")');
  await page.waitForSelector('.rd-note:has-text("Edited by the architect")');
  check(/Continue under D-2026-001/.test(await page.innerText('.rd-rec .rd-text')) && await page.locator('.rd-group').count() === 1 && await page.locator('.rd-arch').count() === 1, 'an edit is saved and marked, and the groups and the architect\'s part stay');

  // return with a note, reopen; then approve once: the whole request
  await page.click('.rd-actions button:has-text("Return with a note")');
  const send = page.locator('button:has-text("Return it")');
  check(await send.isDisabled(), 'a return needs a note (the button waits for one)');
  await page.fill('#rd-note', 'Name the licence owner first.');
  await send.click();
  await page.waitForSelector('.rd-banner.crit');
  check(/Name the licence owner first\./.test(await page.innerText('.rd-banner.crit')), 'a returned draft shows its note');
  await page.click('button:has-text("Reopen as a draft")');
  await page.waitForSelector('.rd-actions button:has-text("Approve")');
  await page.click('.rd-actions button:has-text("Approve")');
  await page.waitForSelector('.rd-banner.ok');
  check(/Approved/.test(await page.innerText('.rd-banner.ok')) && !(await page.$('.rd-sheet button:has-text("Edit")')), 'one approval locks the draft');
  check(/^Approved$/.test((await page.innerText('.rd h3')).trim()), 'and the card says approved: ' + (await page.innerText('.rd h3')));
  await shot(page, '3-approved');

  // the download is the message: the overview and the sections, with the group named, and not the architect's part
  const href = await page.getAttribute('.rd-dl', 'href');
  const dl = await page.request.get(ORIGIN + href);
  const text = await dl.text();
  check(dl.ok() && /attachment/.test(dl.headers()['content-disposition'] || '') && /<!doctype html>/i.test(text), 'the download is a page');
  check(/Continue under D-2026-001/.test(text) && /Combined: D-2026-001, D-2026-003/.test(text) && /D-2026-004/.test(text) && !/Overlaps with|Handled with|To confirm before approval|Evidence/.test(text), 'it holds the message only, with the group named');
  check(/Download the message/.test(await page.innerText('.rd-dl')), 'and the button says so');

  // a reload keeps what was decided
  await page.reload();
  await page.waitForSelector('.rd');
  check(/^Approved$/.test((await page.innerText('.rd h3')).trim()), 'a reload keeps the approval');

  check(errors.length === 0, 'no errors in the browser console' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('DRIVER ERROR', e); process.exit(2); });
