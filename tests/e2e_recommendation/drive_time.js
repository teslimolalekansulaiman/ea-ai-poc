// Where the time of a phase went, on the case's Activity tab, in a real browser: see README.md.
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
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 1100 } })).newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  const csv = fs.readFileSync(path.join(ROOT, 'use_cases/samples/demand-management-inputs.csv'));
  const parsed = await (await page.request.post(`${ORIGIN}/api/cases/parse-file?use_case_id=demand-management`,
    { multipart: { file: { name: 'd.csv', mimeType: 'text/csv', buffer: csv } } })).json();
  const made = await (await page.request.post(`${ORIGIN}/api/cases`, { data: { use_case_id: 'demand-management', items: parsed.items, name: 'Time check' } })).json();
  await page.goto(`${ORIGIN}/#/cases/${made.id}`);
  const approve1 = page.locator('button:has-text("Approve and continue to")');
  await approve1.waitFor({ timeout: 30000 });
  await page.locator('button:has-text("View activity")').first().click();
  await page.waitForSelector('.cs-time', { timeout: 15000 });
  const text = await page.innerText('.cs-time');
  check(/On the clock:/.test(text) && /Work done, added up:/.test(text), 'it says the time on the clock and the work added up');
  check(/Steps, by the time they took/i.test(text) && /gather the evidence|write the answer/.test(text), 'the steps are listed by the time they took');
  check(/model call: write the answer/.test(text) && /calls?, /.test(text), 'a step says how many calls it was and how long each took');
  check(/Properties, by the time they took/i.test(text) && /Domain|Owners|Urgency/.test(text), 'the properties are listed with the time each took for each demand');
  check((await page.$$('.cs-time-step')).length >= 3, 'with a bar for each step');
  await page.screenshot({ path: path.join(OUT, 'time-1-activity.png') });
  const api = await (await page.request.get(`${ORIGIN}/api/cases/${made.id}/timings`)).json();
  check(api.phases.length === 2 && api.phases[0].steps.length > 0, 'the same, from the route, for both phases');
  check(errors.length === 0, 'no script errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? `${failed} FAILED` : 'all passed');
  process.exit(failed ? 1 : 0);
})();
