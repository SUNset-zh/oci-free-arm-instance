#!/usr/bin/env node
// 起一个本地静态服务器（ES module 不能走 file://），逐帧渲染 world.html 并编码为 MP4。
//
//   node render.js                    # 完整视频（1080x1920 / 30fps）
//   node render.js --stills 5,12.5    # 只导出静帧
//   node render.js --from 20 --to 30  # 只渲染一段（调试用）
const path = require('path');
const fs = require('fs');
const http = require('http');
const { spawn } = require('child_process');
let playwright;
try { playwright = require('playwright'); }
catch { playwright = require(path.join(process.execPath, '../../lib/node_modules/playwright')); }

const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(`--${n}`); return i >= 0 ? args[i + 1] : d; };
const FPS = Number(opt('fps', 30));
const OUT = opt('out', path.join(__dirname, 'out'));
const STILLS = opt('stills', null);
const FFMPEG = process.env.FFMPEG || 'ffmpeg';
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json' };

const server = http.createServer((req, res) => {
  const f = path.join(__dirname, decodeURIComponent(req.url.split('?')[0]));
  if (!f.startsWith(__dirname) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'application/octet-stream' });
  fs.createReadStream(f).pipe(res);
});

server.listen(0, async () => {
  const port = server.address().port;
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await playwright.chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => { console.error('page error:', e.message); process.exit(1); });
  page.on('console', m => { if (m.type() === 'error') console.error('console:', m.text()); });
  await page.goto(`http://127.0.0.1:${port}/world.html?render=1`);
  await page.waitForFunction(() => window.READY === true, null, { timeout: 300000 });
  const duration = await page.evaluate(() => window.DURATION);
  const stage = await page.$('#stage');

  if (STILLS) {
    for (const s of STILLS.split(',').map(Number)) {
      await page.evaluate(t => window.render(t), s);
      await stage.screenshot({ path: path.join(OUT, `still_${String(Math.round(s * 1000)).padStart(5, '0')}.jpg`), type: 'jpeg', quality: 88 });
    }
    await browser.close(); server.close(); return;
  }

  const from = Number(opt('from', 0)), to = Number(opt('to', duration));
  const video = path.join(OUT, opt('name', 'video_only.mp4'));
  const ff = spawn(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', video], { stdio: ['pipe', 'inherit', 'inherit'] });
  const t0 = Date.now(), f0 = Math.round(from * FPS), f1 = Math.round(to * FPS);
  for (let f = f0; f < f1; f++) {
    await page.evaluate(t => window.render(t), f / FPS);
    const buf = await stage.screenshot({ type: 'jpeg', quality: 94 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (f % 30 === 0) console.log(`frame ${f}/${f1}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await browser.close(); server.close();
  console.log('video ->', video);
});
