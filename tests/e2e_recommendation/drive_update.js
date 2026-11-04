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
  check(/Phase 2 ends in a message to the requester/.test(panel) && /renamed 'Recommendation type'/.test(panel) && /'Risks and conditions' is added/.test(panel), 'the update is listed with what it would do');
  check(/Kept as you wrote it/.test(panel), 'and says which of the owner\'s wording it keeps');
  await page.screenshot({ path: path.join(OUT, 'update-1-preview.png') });

  await page.click('.uc-history button:has-text("Apply")');
  await page.waitForSelector('.uc-history .pill.ok:has-text("applied")');
  check(true, 'applying marks it applied');
  const after = await (await page.request.get(`${ORIGIN}/api/usecases/demand-management`)).json();
  const names = after.stages[1].output.columns.map(c => c.name);
  check(names.includes('Recommendation type') && names.includes('Risks and conditions') && names.includes('Next steps') && !names.includes('Recommended action') && !names.includes('Justification'), 'the stored use case has the new properties: ' + names.join(', '));
  check(after.stages[1].summary_columns[0] === 'Recommendation' && after.stages[1].output.mode === 'document', 'the message is the summary property and the stage shows documents');
  await page.screenshot({ path: path.join(OUT, 'update-2-applied.png') });

  // a new case now gets the documents
  const made = await (await page.request.post(`${ORIGIN}/api/cases`, { data: { use_case_id: 'demand-management', items: [{ demand_id: 'D-2026-901', title: 'Update check', business_need: 'x' }], name: 'update check' } })).json();
  const c = await (await page.request.get(`${ORIGIN}/api/cases/${made.id}`)).json();
  check(c.phases[1].mode === 'document', 'a case started after it shows Recommendation as documents');

  check(errors.length === 0, 'no errors in the browser console' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('DRIVER ERROR', e); process.exit(2); });
