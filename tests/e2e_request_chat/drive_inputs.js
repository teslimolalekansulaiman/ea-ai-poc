// Starts a use case five ways, in a real browser against serve.py (see README.md): by chatting, from a PDF of one demand, a PDF of two,
// a sheet of one, a sheet of two. Each ends with the case started and its first phase run.
const { chromium } = require('playwright');
const path = require('path');
const D = __dirname, IN = path.join(D, 'inputs'), OUT = process.env.OUT || require('os').tmpdir();
const ORIGIN = `http://127.0.0.1:${process.env.PORT || 8765}`, BASE = `${ORIGIN}/#/cases`;
const MSG = 'textarea[aria-label="Message"]';
let failed = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) failed++; };
const idle = (page) => page.waitForFunction(() => !document.querySelector('.rc-working') && ![...document.querySelectorAll('button')].some(b => b.textContent === 'Reading…'), null, { timeout: 30000 });
const msgs = (page) => page.$$eval('.rc-msgs .cs-msg', els => els.map(e => e.innerText));
const shot = (page, n) => page.screenshot({ path: path.join(OUT, 'inputs-' + n + '.png') });

const CHAT = [
  'I want to raise a demand.',
  'Demand ID: D-2026-310',
  'Demand title: Automated invoice approval',
  'Requesting department: Finance',
  'Business sponsor: Chief Financial Officer',
  'Business need: Invoices are approved by email and Finance re-keys each one into the ledger. This takes days and causes errors.',
].join('\n');

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  const fresh = async () => { await page.goto(BASE); await page.waitForSelector(MSG); };
  const caseId = () => (page.url().match(/#\/cases\/([a-f0-9]{12})/) || [])[1];
  // the case is started and its first phase has run, with this many demands
  const started = async (n, label) => {
    await page.waitForURL(/#\/cases\/[a-f0-9]{12}$/, { timeout: 20000 });
    await page.waitForSelector('.cs-bar', { timeout: 20000 });
    const id = caseId();
    let c;
    for (let i = 0; i < 80; i++) { c = await (await page.request.get(`${ORIGIN}/api/cases/${id}`)).json(); if (c.phases[0].state.status === 'review') break; await page.waitForTimeout(500); }
    check(c.items && c.items.length === n && c.phases[0].state.status === 'review', `${label}: the case started with ${n} demand${n > 1 ? 's' : ''} and its first phase ran (${c.items ? c.items.map(i => i._id).join(', ') : '?'})`);
    return c;
  };
  // the case is taken on: the screening approved, the recommendation run, and the one draft for the request is there
  const toDraft = async (n, ids, label) => {
    await page.click('button:has-text("Approve and continue to")');
    await page.waitForSelector('.rd', { timeout: 40000 });
    check(/One draft for the whole request/.test(await page.innerText('.rd h3')), `${label}: the recommendation phase ends in one draft for the whole request`);
    check(new RegExp(`The request holds ${n} demand`).test(await page.innerText('.rd-rec .rd-text')), `${label}: it opens with the overview of the request: ` + (await page.innerText('.rd-rec .rd-text')).replace(/\s+/g, ' ').slice(0, 70));
    const heads = await page.$$eval('.rd-sheet > .rd-sec .rd-h', e => e.map(x => x.textContent));
    check(heads.length === n && ids.every((id, i) => heads[i].startsWith(id + ' · ')), `${label}: a section for each demand: ` + heads.join(' | '));
    const body = await page.innerText('.rd-sheet > .rd-sec >> nth=0');
    check(new RegExp(`extend the existing platform to cover ${ids[0]}`).test(body) && /Next steps/.test(body), `${label}: each section is that demand's own recommendation, with its next steps`);
    const apart = await page.$$eval('.rd-arch .rd-demand', e => e.map(x => x.textContent));
    check(ids.every(id => apart.includes(id)) && /For the architect, not sent/i.test(await page.innerText('.rd-arch')), `${label}: the architect's part has each demand's findings, apart and not sent`);
    const dl = await page.request.get(ORIGIN + await page.getAttribute('.rd-dl', 'href'));
    const text = await dl.text();
    check(dl.ok() && ids.every(id => text.includes(id)) && /The request holds/.test(text) && !/Overlaps with|To confirm before approval/.test(text), `${label}: the download holds the overview and every demand's section, not the architect's part`);
    await page.click('.rd-actions button:has-text("Approve")');
    await page.waitForSelector('.rd-banner.ok');
    check(/This is the recommendation for this request/.test(await page.innerText('.rd-banner.ok')) && !/_request/.test(await page.innerText('.rd')), `${label}: nothing internal shows in the text (no "_request")`);
    check(/^Approved$/.test((await page.innerText('.rd h3')).trim()), `${label}: one approval, and the case is finished`);
    await shot(page, label.split(' ')[0] + '-draft');
  };
  const ready = async () => { await page.waitForSelector('.rc-ready', { timeout: 20000 }); return page.innerText('.rc-ready'); };

  // 1. chatting: a typed message, what is missing is asked, the answers go in the sheet, then the case starts
  await fresh();
  await page.fill(MSG, CHAT); await page.press(MSG, 'Enter'); await page.waitForSelector('.rc'); await idle(page);
  let m = await msgs(page);
  check(/I found 1 demand: D-2026-310 \(Automated invoice approval\)/.test(m.join('\n')), '1 chat: the agent found the demand in the message: ' + (m[1] || '').slice(0, 80).replace(/\n/g, ' '));
  await page.click('.rc-sum > summary');
  const have = await page.innerText('.rc-sumbody');
  check(/Finance/.test(have) && /Chief Financial Officer/.test(have) && /From your message/.test(have), '1 chat: what it read is listed with where it came from');
  await page.click('.rc-sum > summary');
  const miss = await page.locator('.rc-gaplist li').allInnerTexts();
  check(miss.length >= 5 && miss.some(x => /Date submitted/.test(x)) && miss.some(x => /Request type/.test(x)), '1 chat: it asks for what the message did not say: ' + miss.map(x => x.split('\n')[0]).join(', '));
  await shot(page, '1-chat-asks');
  await page.click('.rc-q button:has-text("Go through them one by one")'); await page.waitForSelector('.rc-slide');
  const N = await page.locator('.rc-dot').count();
  for (let n = 0; n < N; n++) {
    const chip = await page.$('.rc-slide .rc-opts button:not(:has-text("Ask the requester"))');
    if (chip) await chip.click();                                                              // a pick list answers by a button
    else if (n === N - 1) await page.fill('.rc-ans', 'Answer ' + n);                            // Enter on the last page would send
    else { await page.fill('.rc-ans', 'Answer ' + n); await page.press('.rc-ans', 'Enter'); }
  }
  await page.click(`button:has-text("Send ${N} answers")`);
  check(/The demand is complete/.test(await ready()), '1 chat: after the answers, nothing is left to ask and the chat offers to start');
  await shot(page, '1-chat-ready');
  await page.click('.rc-ready button:has-text("Start the case")');
  await started(1, '1 chat');
  await shot(page, '1-chat-case');
  await toDraft(1, ['D-2026-310'], '1 chat');

  // 2 and 3. a PDF of one demand, a PDF of two: read, every required field found, nothing to ask, the case starts
  for (const [n, file, label] of [[1, 'one_demand.pdf', '2 PDF, one demand'], [2, 'two_demands.pdf', '3 PDF, two demands']]) {
    await fresh();
    await page.setInputFiles('input[type=file]', path.join(IN, file));
    await page.click('button:has-text("Send")'); await page.waitForSelector('.rc'); await idle(page);
    m = await msgs(page); const first = m.join('\n');
    check(new RegExp(`I found ${n} demand`).test(first) && /D-2026-301 \(Self-service payslip portal\)/.test(first) && (n === 1 || /D-2026-302 \(Contract renewal alerts\)/.test(first)),
      `${label}: found ${n} demand${n > 1 ? 's' : ''} in the PDF: ` + (m[1] || '').slice(0, 110).replace(/\n/g, ' '));
    const r = await ready();
    check(/complete/.test(r) && !(await page.$('.rc-gaplist')) && !(await page.$('.rc-slide')), `${label}: every required field was read, so nothing is asked: ` + r.replace(/\s+/g, ' ').slice(0, 60));
    await page.click('.rc-sum > summary');
    const sum = await page.innerText('.rc-sumbody');
    check(/From /.test(sum) && new RegExp(file.replace('.', '\\.')).test(await page.innerText('.rc-sumbody').catch(() => '') + (await page.$$eval('.rq-tag', e => e.map(x => x.textContent).join(' ')))), `${label}: each value says it came from ${file}`);
    await shot(page, n === 1 ? '2-pdf-one' : '3-pdf-two');
    await page.click('.rc-sum > summary');
    await page.click('.rc-ready button:has-text("Start the case")');
    await started(n, label);
    await toDraft(n, n === 1 ? ['D-2026-301'] : ['D-2026-301', 'D-2026-302'], label);
  }

  // 4. a sheet of one demand: complete, so the case starts without a conversation
  await fresh();
  await page.setInputFiles('input[type=file]', path.join(IN, 'one_demand.xlsx'));
  await page.click('button:has-text("Send")');
  await started(1, '4 Excel, one demand');
  check(!(await page.$('.rc-chat')), '4 Excel, one demand: a complete sheet needs no conversation');
  await toDraft(1, ['D-2026-301'], '4 Excel, one demand');
  await shot(page, '4-excel-one');

  // 5. a sheet of two demands, the second missing its sponsor and its go-live date: asked, answered together, then the case starts
  await fresh();
  await page.setInputFiles('input[type=file]', path.join(IN, 'two_demands.xlsx'));
  await page.click('button:has-text("Send")'); await page.waitForSelector('.rc'); await idle(page);
  m = await msgs(page);
  check(/2 required details are still missing: Business sponsor \(for D-2026-302\); Target go-live \(for D-2026-302\)/.test(m.join('\n')), '5 Excel, two demands: it asks only for what is missing, and for which demand: ' + (m[0] || '').slice(0, 120).replace(/\n/g, ' '));
  await page.waitForSelector('.rc-slide');
  check(await page.locator('.rc-dot').count() === 2, '5 Excel, two demands: two pages in the answer sheet');
  await shot(page, '5-excel-two-asks');
  await page.fill('.rc-ans', 'Chief Procurement Officer'); await page.press('.rc-ans', 'Enter');
  await page.fill('.rc-ans', '2026-12-15'); await page.press('.rc-ans', 'Enter');             // Enter on the last page sends both
  check(/All 2 demands are complete/.test(await ready()), '5 Excel, two demands: after both answers, both demands are complete');
  m = await msgs(page);
  check(/Business sponsor: Chief Procurement Officer/.test(m.join('\n')) && /Target go-live: 2026-12-15/.test(m.join('\n')), '5 Excel, two demands: one message in the thread carries both answers');
  await page.click('.rc-ready button:has-text("Start the case")');
  await started(2, '5 Excel, two demands');
  await shot(page, '5-excel-two-case');
  await toDraft(2, ['D-2026-301', 'D-2026-302'], '5 Excel, two demands');

  check(errors.length === 0, 'no errors in the browser console' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('DRIVER ERROR', e); process.exit(2); });
