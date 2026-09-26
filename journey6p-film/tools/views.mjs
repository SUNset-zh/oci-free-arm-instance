// Render arbitrary debug views: node tools/views.mjs name "world|frame:px,py,pz:lx,ly,lz:fov|t" ...
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const W = Number(process.env.W || 800), H = Number(process.env.H || 450);
const out = path.join(root, 'shots');
fs.mkdirSync(out, { recursive: true });
const port = 5700 + Math.floor(Math.random() * 500);
const server = spawn(process.execPath, [path.join(root, 'tools/serve.mjs')], { env: { ...process.env, PORT: String(port) }, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 400));
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: W, height: H } });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.log('[page]', m.text().slice(0, 300)); });
const specs = process.argv.slice(2);
await page.goto(`http://localhost:${port}/?render&nowarm&w=${W}&h=${H}`);
await page.waitForFunction(() => window.__film && window.__film.ready, null, { timeout: 600000 });
for (let i = 0; i < specs.length; i += 2) {
  const name = specs[i];
  const [world, pose, t] = specs[i + 1].split('|');
  await page.evaluate(([w, p, tt]) => { window.__film.debug(w, p); window.__film.renderAt(tt); }, [world, pose, Number(t || 0)]);
  await page.locator('#stage').screenshot({ path: path.join(out, `v_${name}.png`) });
  console.log('ok', name);
}
await browser.close();
server.kill();
