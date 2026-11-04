// "Draft the questions" on the Config screen, in a real browser: see README.md. Needs serve.py (any mode).
const { chromium } = require('playwright');
const path = require('path');
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
  page.on('dialog', d => d.accept());

  await page.goto(`${ORIGIN}/#/usecases`);
  await page.waitForSelector('text=Demand Management');
  await page.locator('.kb-doc', { hasText: 'Demand Management' }).locator('a:has-text("Edit")').click();
  await page.locator('.uc-nav', { hasText: 'Security fit' }).first().click();
  await page.waitForSelector('.lookup-draft');
  check((await page.locator('.add-lookup').count()) === 1 && /No lookups yet/.test(await page.innerText('.uc-property')), 'the property starts with no lookups');

  await page.click('.draft-lookups');
  await page.waitForSelector('.draft-item');
  const items = await page.locator('.draft-item').allInnerTexts();
  check(items.length === 2, 'two questions are proposed; the one that starts from a property that does not exist was left out (' + items.length + ')');
  check(/the answer of “Overlaps with”/.test(items[0]) && /Why: the owner of what already exists/.test(items[0]), 'a proposal says where it starts from and why');
  check(/also makes the property build on “Overlaps with”/.test(items[0]), 'and that adding it makes the property build on that answer');
  check(/starts from the answer of “Nothing at all”|not decided before/.test(await page.innerText('.lookup-draft')), 'what was left out is said');
  check((await page.locator('.add-lookup').count()) === 1, 'nothing has been added to the property yet');
  await page.screenshot({ path: path.join(OUT, 'draft-1-proposed.png') });

  await page.locator('.add-draft').first().click();
  await page.waitForSelector('.lookup-relations');
  check((await page.locator('.draft-item').count()) === 1, 'an added proposal leaves the list; the other stays');
  const lookupText = await page.innerText('.lookup-relations');
  check(/Lookup 1|who owns each system/.test(await page.locator('.lookup-relations').innerHTML()) || /result:Overlaps with/.test(await page.locator('.lookup-relations').innerHTML()), 'the lookup is in the property');
  await page.screenshot({ path: path.join(OUT, 'draft-2-added.png') });
  void lookupText;

  // saved, it is the use case's
  await page.click('button:has-text("Save")');
  await page.waitForTimeout(800);
  const got = await (await page.request.get(`${ORIGIN}/api/usecases/demand-management`)).json();
  const col = got.stages[1].output.columns.find(c => c.name === 'Security fit');
  check(col.lookups?.length === 1 && col.lookups[0].from === 'result:Overlaps with' && col.lookups[0].match === 'name' && !('why' in col.lookups[0]) && !('needs_uses' in col.lookups[0]), 'saved: the lookup, without the draft\'s notes');
  check((col.uses || []).includes('Overlaps with'), 'saved: the property builds on the answer it starts from');
  check(errors.length === 0, 'no script errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? `${failed} FAILED` : 'all passed');
  process.exit(failed ? 1 : 0);
})();
