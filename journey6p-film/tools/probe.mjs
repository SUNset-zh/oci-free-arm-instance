// Debug probe: node tools/probe.mjs "name|world|pose|t|js" ...   (js runs with `d` = director)
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const W = Number(process.env.W || 640), H = Number(process.env.H || 360);
fs.mkdirSync(path.join(root, 'shots'), { recursive: true });
const port = 6000 + Math.floor(Math.random() * 900);
const server = spawn(process.execPath, [path.join(root, 'tools/serve.mjs')], { env: { ...process.env, PORT: String(port) }, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 400));
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: W, height: H } });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
page.on('console', (m) => { if (m.type() === 'log' || m.type() === 'error') console.log('[page]', m.text().slice(0, 2000)); });
await page.goto(`http://localhost:${port}/?render&nowarm&w=${W}&h=${H}`);
await page.waitForFunction(() => (window.__film && window.__film.ready) || document.getElementById('playlabel').textContent.includes('ERROR'), null, { timeout: 300000 });
for (const spec of process.argv.slice(2)) {
  const [name, world, pose, t, js] = spec.split('|');
  const res = await page.evaluate(([w, p, tt, code]) => {
    const d = window.__director; d.debugPose = null; d.debugWorld = null;
    if (w || p) d.setDebug(w, p);
    let r = null;
    if (code) r = eval(code);
    window.__film.renderAt(Number(tt || 0));
    return r == null ? null : JSON.stringify(r);
  }, [world, pose, t, js]);
  if (res) console.log(name, res);
  if (name && !name.startsWith('_')) await page.locator('#stage').screenshot({ path: path.join(root, 'shots', `p_${name}.png`) });
}
await browser.close();
server.kill();
