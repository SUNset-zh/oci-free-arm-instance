// Render the score offline and print a loudness profile (RMS / peak per second).
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const port = 6100 + Math.floor(Math.random() * 400);
const server = spawn(process.execPath, [path.join(root, 'tools/serve.mjs')], { env: { ...process.env, PORT: String(port) }, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 400));
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 320, height: 180 } });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto(`http://localhost:${port}/?render&nowarm&w=320&h=180`);
await page.waitForFunction(() => window.__film && window.__film.ready, null, { timeout: 300000 });
const t0 = Date.now();
const b64 = await page.evaluate(() => window.__film.renderAudio(22050));
console.log(`offline render ${((Date.now() - t0) / 1000).toFixed(1)}s`);
const buf = Buffer.from(b64, 'base64');
fs.mkdirSync(path.join(root, 'out'), { recursive: true });
fs.writeFileSync(path.join(root, 'out', 'score_preview.wav'), buf);
const sr = buf.readUInt32LE(24);
const n = (buf.length - 44) / 4;
let line = '';
for (let s = 0; s < n / sr; s++) {
  let sum = 0, pk = 0;
  for (let i = s * sr; i < Math.min(n, (s + 1) * sr); i++) {
    const v = buf.readInt16LE(44 + i * 4) / 32768;
    sum += v * v; pk = Math.max(pk, Math.abs(v));
  }
  const rms = Math.sqrt(sum / sr);
  line += `${String(s).padStart(2)}s ${(20 * Math.log10(rms + 1e-9)).toFixed(0).padStart(4)}dB pk${pk.toFixed(2)}${s % 4 === 3 ? '\n' : ' | '}`;
}
console.log(line);
await browser.close(); server.kill();
