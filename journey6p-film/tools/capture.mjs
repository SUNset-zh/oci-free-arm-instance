// Frame-accurate video export: renders every frame deterministically, then
// muxes the offline-rendered score. Needs a full ffmpeg (libx264) on PATH or
// in $FFMPEG. Headless Chromium uses software GL, so this is slow but exact;
// pass --gpu to try hardware GL.
//
//   node tools/capture.mjs --fps 30 --w 1920 --h 1080 --out out/journey6p.mp4
//   node tools/capture.mjs --from 50 --to 60 --fps 24 --w 960 --h 540   (a slice)
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const opt = (k, d) => { const i = argv.indexOf(`--${k}`); return i >= 0 ? argv[i + 1] : d; };
const flag = (k) => argv.includes(`--${k}`);
const fps = Number(opt('fps', 30));
const W = Number(opt('w', 1920)), H = Number(opt('h', 1080));
const outFile = path.resolve(opt('out', path.join(root, 'out', 'journey6p.mp4')));
const ffmpeg = opt('ffmpeg', process.env.FFMPEG || 'ffmpeg');
const lang = opt('lang', 'both');
const quality = opt('q', 'high');
fs.mkdirSync(path.dirname(outFile), { recursive: true });

if (spawnSync(ffmpeg, ['-version']).status !== 0) {
  console.error(`ffmpeg not found (${ffmpeg}). Install it or pass --ffmpeg /path/to/ffmpeg.`);
  process.exit(1);
}
const port = 5600 + Math.floor(Math.random() * 300);
const server = spawn(process.execPath, [path.join(root, 'tools/serve.mjs')], { env: { ...process.env, PORT: String(port) }, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 400));
const gl = flag('gpu') ? ['--use-angle=gl', '--enable-gpu', '--ignore-gpu-blocklist'] : ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
const browser = await chromium.launch({ args: gl });
const page = await browser.newPage({ viewport: { width: W, height: H } });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto(`http://localhost:${port}/?render&w=${W}&h=${H}&q=${quality}&lang=${lang}`);
await page.waitForFunction(() => window.__film && window.__film.ready, null, { timeout: 0 });
const duration = await page.evaluate(() => window.__film.duration);
const from = Number(opt('from', 0)), to = Math.min(duration, Number(opt('to', duration)));

// Audio first (fast).
const wav = path.join(path.dirname(outFile), 'score.wav');
const b64 = await page.evaluate(() => window.__film.renderAudio(48000));
fs.writeFileSync(wav, Buffer.from(b64, 'base64'));
console.log('score →', wav);

const enc = spawn(ffmpeg, [
  '-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', '-',
  '-ss', String(from), '-i', wav, '-t', String(to - from),
  '-c:v', 'libx264', '-preset', 'slow', '-crf', '15', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
  '-c:a', 'aac', '-b:a', '256k', '-shortest', outFile,
], { stdio: ['pipe', 'inherit', 'inherit'] });
const frames = Math.round((to - from) * fps);
const t0 = Date.now();
for (let i = 0; i < frames; i++) {
  const t = from + i / fps;
  await page.evaluate((tt) => window.__film.renderAt(tt), t);
  const buf = await page.locator('#stage').screenshot({ type: 'jpeg', quality: 96 });
  if (!enc.stdin.write(buf)) await new Promise((r) => enc.stdin.once('drain', r));
  if (i % fps === 0) {
    const el = (Date.now() - t0) / 1000;
    console.log(`frame ${i}/${frames}  t=${t.toFixed(2)}  ${(el / (i + 1)).toFixed(2)} s/frame  eta ${((frames - i) * el / (i + 1) / 60).toFixed(1)} min`);
  }
}
enc.stdin.end();
await new Promise((r) => enc.on('close', r));
await browser.close();
server.kill();
console.log('done →', outFile);
