// The shipped update on the Config screen, in a real browser: see README.md. Needs serve.py started with EA_E2E_OLD_SECOND_STAGE=1.
const { chromium } = require('playwright');
const path = require('path');
const OUT = process.env.OUT || require('os').tmpdir();
const ORIGIN = `http://127.0.0.1:${process.env.PORT || 8767}`;
let failed = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 1000 } })).newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('dialog', d => d.accept());                                   // the screen asks before it applies

  const before = await (await page.request.get(`${ORIGIN}/api/usecases/demand-management`)).json();
  check(before.stages[1].output.columns.some(c => c.name === 'Recommended action') && !before.stages[1].output.columns.some(c => c.name === 'Risks and conditions'), 'the copy starts as the older second stage');

  await page.goto(`${ORIGIN}/#/usecases`);
  await page.waitForSelector('text=Demand Management');
  await page.locator('.kb-doc', { hasText: 'Demand Management' }).locator('a:has-text("Edit")').click();
  await page.click('button:has-text("History")');
  await page.waitForSelector('text=Updates that came with the code');
  const panel = await page.innerText('.uc-history');
  check(/Phase 2 ends in one recommendation for the whole request/.test(panel) && /renamed 'Recommendation type'/.test(panel) && /'Request overview' is added/.test(panel) && /'Handled with' is added/.test(panel), 'the update is listed with what it would do');
  check(/Kept as you wrote it/.test(panel), 'and says which of the owner\'s wording it keeps');
  await page.screenshot({ path: path.join(OUT, 'update-1-preview.png') });

  await page.click('.uc-history button:has-text("Apply")');
  await page.waitForSelector('.uc-history .pill.ok:has-text("applied")');
  check(true, 'applying marks it applied');
  const after = await (await page.request.get(`${ORIGIN}/api/usecases/demand-management`)).json();
  const names = after.stages[1].output.columns.map(c => c.name);
  check(['Recommendation type', 'Risks and conditions', 'Handled with', 'Recommendation', 'Request overview'].every(n => names.includes(n)) && !['Recommended action', 'Justification', 'Next steps', 'Confidence'].some(n => names.includes(n)), 'the stored use case has the new properties: ' + names.join(', '));
  check(after.stages[1].summary_columns[0] === 'Recommendation' && after.stages[1].output.mode === 'document' && after.stages[1].output.document.scope === 'request', 'each demand\'s section is the summary property, and the stage is one draft for the whole request');
  await page.screenshot({ path: path.join(OUT, 'update-2-applied.png') });

  // a case started now runs both phases on the updated use case and ends in one draft for the request
  const fs = require('fs');
  const csv = fs.readFileSync(path.join(__dirname, '../../use_cases/samples/demand-management-inputs.csv'));
  const parsed = await (await page.request.post(`${ORIGIN}/api/cases/parse-file?use_case_id=demand-management`, { multipart: { file: { name: 'd.csv', mimeType: 'text/csv', buffer: csv } } })).json();
  const made = await (await page.request.post(`${ORIGIN}/api/cases`, { data: { use_case_id: 'demand-management', items: parsed.items, name: 'update check' } })).json();
  const until = async (i, status) => { for (let n = 0; n < 80; n++) { const c = await (await page.request.get(`${ORIGIN}/api/cases/${made.id}`)).json(); if (c.phases[i].state.status === status) return c; await page.waitForTimeout(500); } throw new Error('phase ' + i + ' never reached ' + status); };
  const c0 = await until(0, 'review');
  check(c0.phases[1].mode === 'document', 'a case started after it shows Recommendation as documents');
  await page.request.post(`${ORIGIN}/api/cases/${made.id}/phases/screening/approve`, { data: {} });
  const c1 = await until(1, 'review');
  check(!c1.phases[1].columns.some(c => c.name === 'Request overview') && c1.phases[1].columns.some(c => c.name === 'Handled with'), 'the request overview is not a column of the demands; the groups are');
  const docs = (await (await page.request.get(`${ORIGIN}/api/cases/${made.id}/phases/recommendation/documents`)).json()).documents;
  check(docs.length === 1 && docs[0].item_id === '_request' && /continue under D-2026-001/.test(docs[0].doc.rec.body), 'the phase ends in one draft for the whole request, with the overview');
  check(docs[0].doc.sections.filter(x => !x.internal).length === 3 && docs[0].doc.sections.some(x => x.group === 'Combined: D-2026-001, D-2026-003'), 'with a section for each demand, the combined ones together');
  await page.goto(`${ORIGIN}/#/cases/${made.id}`);
  await page.waitForSelector('.rd');
  await page.screenshot({ path: path.join(OUT, 'update-3-draft.png') });

  check(errors.length === 0, 'no errors in the browser console' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('DRIVER ERROR', e); process.exit(2); });
