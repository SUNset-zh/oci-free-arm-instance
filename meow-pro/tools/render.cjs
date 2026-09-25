// Render web/index.html frame by frame to JPEGs using parallel headless Chromium workers.
//
// usage: node tools/render.cjs <outdir> [fps=60] [workers=4] [start=0] [end=50] [quality=95] [sub=1] [shutter=0.5]
//
// sub > 1 renders `sub` samples per output frame spread over `shutter` of the frame
// interval (0.5 = 180° shutter). Files are numbered sequentially (frame*sub + j);
// encode.sh averages each group with ffmpeg's tmix for real motion blur.
const path = require('path');
const fs = require('fs');
const { chromium } = (() => {
  for (const m of [process.env.PLAYWRIGHT_MODULE, 'playwright', '/opt/node22/lib/node_modules/playwright']) {
    if (!m) continue;
    try { return require(m); } catch (e) { /* try the next location */ }
  }
  throw new Error('playwright not found: npm install, or set PLAYWRIGHT_MODULE');
})();

const [outdir = 'frames', fpsA = '60', workersA = '4', startA = '0', endA = '50', qA = '95', subA = '1', shA = '0.5'] = process.argv.slice(2);
const fps = Number(fpsA), workers = Number(workersA), start = Number(startA), end = Number(endA);
const quality = Number(qA), sub = Number(subA), shutter = Number(shA);
const pagePath = path.resolve(__dirname, '..', 'web', 'index.html');

function sampleTime(n) {
  const k = Math.floor(n / sub), j = n % sub;
  const off = sub > 1 ? (j / (sub - 1) - 0.5) * shutter / fps : 0;
  return k / fps + off;
}

async function worker(id, samples) {
  const browser = await chromium.launch({ args: ['--allow-file-access-from-files', '--force-color-profile=srgb', '--disable-lcd-text'] });
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => console.log(`[w${id}] pageerror`, e.message));
  await page.goto('file://' + pagePath);
  await page.evaluate(() => window.__ready);
  let done = 0;
  const t0 = Date.now();
  for (const n of samples) {
    await page.evaluate(t => window.seek(t), sampleTime(n));
    const buf = await page.screenshot({ type: 'jpeg', quality });
    fs.writeFileSync(path.join(outdir, `f${String(n).padStart(6, '0')}.jpg`), buf);
    if (++done % 300 === 0) console.log(`[w${id}] ${done}/${samples.length} (${((Date.now() - t0) / done).toFixed(0)} ms/sample)`);
  }
  await browser.close();
}

if (require.main === module) (async () => {
  fs.mkdirSync(outdir, { recursive: true });
  const all = [];
  for (let n = Math.round(start * fps) * sub; n < Math.round(end * fps) * sub; n++) all.push(n);
  const chunks = Array.from({ length: workers }, () => []);
  all.forEach((n, i) => chunks[Math.floor(i / 60) % workers].push(n));
  const t0 = Date.now();
  await Promise.all(chunks.map((c, i) => worker(i, c)));
  console.log(`rendered ${all.length} samples (${all.length / sub} frames) in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
})();
