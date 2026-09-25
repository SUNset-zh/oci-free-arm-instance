// Screenshot the keynote page at given times.
// usage: node tools/shot.cjs <outdir> <t1,t2,...> [scale=0.5] [page=web/index.html]
const path = require('path');
const fs = require('fs');
const { chromium } = (() => {
  for (const m of [process.env.PLAYWRIGHT_MODULE, 'playwright', '/opt/node22/lib/node_modules/playwright']) {
    if (!m) continue;
    try { return require(m); } catch (e) { /* try the next location */ }
  }
  throw new Error('playwright not found: npm install, or set PLAYWRIGHT_MODULE');
})();

if (require.main === module) (async () => {
  const outdir = process.argv[2] || 'shots';
  const times = (process.argv[3] || '0').split(',').map(Number);
  const scale = Number(process.argv[4] || 0.5);
  const page_ = path.resolve(process.argv[5] || path.join(__dirname, '..', 'web', 'index.html'));
  fs.mkdirSync(outdir, { recursive: true });
  const browser = await chromium.launch({ args: ['--allow-file-access-from-files', '--force-color-profile=srgb'] });
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: scale });
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') console.log('[page]', m.text()); });
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  await page.goto('file://' + page_);
  await page.evaluate(() => window.__ready);
  for (const t of times) {
    await page.evaluate(t => window.seek(t), t);
    const f = path.join(outdir, `t${t.toFixed(2).padStart(6, '0')}.jpg`);
    await page.screenshot({ path: f, type: 'jpeg', quality: 85 });
  }
  await browser.close();
  console.log('ok', times.length, 'shots ->', outdir);
})();
