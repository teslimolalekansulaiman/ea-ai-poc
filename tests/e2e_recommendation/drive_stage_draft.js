// "Draft the questions for every property" of a whole stage on the Config screen, in a real browser: see README.md. Needs a fresh serve.py.
const { chromium } = require('playwright');
const path = require('path');
const OUT = process.env.OUT || require('os').tmpdir();
const ORIGIN = `http://127.0.0.1:${process.env.PORT || 8766}`;
let failed = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 1200 } })).newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('dialog', d => d.accept());

  const before = await (await page.request.get(`${ORIGIN}/api/usecases/demand-management`)).json();
  const had = Object.fromEntries(before.stages[0].output.columns.map(c => [c.name, (c.lookups || []).length]));

  await page.goto(`${ORIGIN}/#/usecases`);
  await page.waitForSelector('text=Demand Management');
  await page.locator('.kb-doc', { hasText: 'Demand Management' }).locator('a:has-text("Edit")').click();
  await page.locator('.uc-nav', { hasText: 'Stage 1' }).first().click();
  await page.waitForSelector('.stage-draft');
  await page.click('.draft-stage');
  await page.waitForSelector('.stage-draft-prop');
  const props = await page.locator('.stage-draft-prop').allInnerTexts();
  const names = await page.locator('.stage-draft-prop > div:first-child').allInnerTexts();
  check(props.length > 0 && names.every(n => had[n] === 0), 'it drafts only properties that had no questions: ' + names.join(', '));
  check(!names.includes('Domain') && /Left as they are:.*Domain \(it already has questions/.test(await page.innerText('.stage-draft')), 'the ones that already have questions are named and left alone');
  check((await page.locator('.stage-draft input[type=checkbox]:checked').count()) > 0, 'the questions are picked by default');
  await page.screenshot({ path: path.join(OUT, 'stage-1-proposed.png') });

  const unchanged = await (await page.request.get(`${ORIGIN}/api/usecases/demand-management`)).json();
  check(JSON.stringify(unchanged) === JSON.stringify(before), 'nothing is stored by drafting');

  // drop one question, then add the rest
  const first = page.locator('.stage-draft-prop input[type=checkbox]').first();
  const droppedFor = (await page.locator('.stage-draft-prop > div:first-child').first().innerText());
  await first.uncheck();
  await page.click('.add-picked');
  await page.waitForSelector('.stage-draft-prop', { state: 'detached' });
  check(true, 'adding closes the review');
  await page.click('button:has-text("Save")');
  await page.waitForTimeout(900);
  const after = await (await page.request.get(`${ORIGIN}/api/usecases/demand-management`)).json();
  const cols = after.stages[0].output.columns;
  const added = cols.filter(c => (c.lookups || []).length > (had[c.name] || 0));
  check(added.length > 0 && added.every(c => had[c.name] === 0 && c.lookups.every(l => !('why' in l) && !('needs_uses' in l))), 'saved: questions in the properties that had none, without the draft\'s notes (' + added.map(c => c.name).join(', ') + ')');
  check(!(cols.find(c => c.name === droppedFor).lookups || []).length, 'the question that was unticked was not added to ' + droppedFor);
  check(cols.filter(c => had[c.name] > 0).every(c => c.lookups.length === had[c.name]), 'the questions that were there are as they were');
  check(errors.length === 0, 'no script errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? `${failed} FAILED` : 'all passed');
  process.exit(failed ? 1 : 0);
})();
