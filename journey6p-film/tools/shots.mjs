// Render stills at given film times (headless Chromium) for review.
// usage: node tools/shots.mjs 0.5 3 7 ...   [--w 960 --h 540 --out shots --q high]
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(`--${k}`); if (i >= 0) { const v = args[i + 1]; args.splice(i, 2); return v; } return d; };
const W = Number(opt('w', 960)), H = Number(opt('h', 540));
const out = path.resolve(opt('out', path.join(root, 'shots')));
const q = opt('q', 'high');
const url = opt('url', '');
const times = args.map(Number).filter((x) => !Number.isNaN(x));
fs.mkdirSync(out, { recursive: true });

const port = 5190 + Math.floor(Math.random() * 500);
const server = spawn(process.execPath, [path.join(root, 'tools/serve.mjs')], { env: { ...process.env, PORT: String(port) }, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 400));
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: W, height: H } });
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log('[page]', m.type(), m.text().slice(0, 400)); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
const t0 = Date.now();
await page.goto(url || `http://localhost:${port}/?render&w=${W}&h=${H}&q=${q}&t=${times[0] || 0}`);
await page.waitForFunction(() => window.__film && window.__film.ready, null, { timeout: 600000 });
console.log(`ready in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
for (const t of times) {
  const s = Date.now();
  await page.evaluate((tt) => window.__film.renderAt(tt), t);
  const file = path.join(out, `t${t.toFixed(2).padStart(6, '0')}.png`);
  await page.locator('#stage').screenshot({ path: file });
  console.log(`${file}  (${((Date.now() - s) / 1000).toFixed(1)}s)`);
}
await browser.close();
server.kill();
