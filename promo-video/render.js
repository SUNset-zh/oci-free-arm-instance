#!/usr/bin/env node
// 逐帧渲染 film.html 并编码为 MP4。
//
//   node render.js                      # 渲染完整视频（默认 3840x2160 / 30fps）
//   node render.js --stills 1,5,10      # 只导出指定秒数的静帧，用于检查画面
//   node render.js --scale 1            # 1920x1080
//
// 依赖：playwright（Chromium）、ffmpeg（环境变量 FFMPEG 可指定路径）。
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

let playwright;
try { playwright = require('playwright'); }
catch { playwright = require(path.join(process.execPath, '../../lib/node_modules/playwright')); }

const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf(`--${name}`); return i >= 0 ? args[i + 1] : def; };
const FPS = Number(opt('fps', 30));
const SCALE = Number(opt('scale', 2));
const OUT = opt('out', path.join(__dirname, 'out'));
const STILLS = opt('stills', null);
const FFMPEG = process.env.FFMPEG || 'ffmpeg';

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await playwright.chromium.launch({ args: ['--force-color-profile=srgb', '--font-render-hinting=none'] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: SCALE });
  await page.goto('file://' + path.join(__dirname, 'film.html'));
  await page.evaluate(() => document.fonts.ready);
  const duration = await page.evaluate(() => window.DURATION);
  fs.writeFileSync(path.join(OUT, 'events.json'), JSON.stringify(await page.evaluate(() => window.EVENTS), null, 1));
  const stage = await page.$('#stage');

  if (STILLS) {
    for (const s of STILLS.split(',').map(Number)) {
      await page.evaluate(t => window.render(t), s);
      await stage.screenshot({ path: path.join(OUT, `still_${String(Math.round(s * 1000)).padStart(5, "0")}.jpg`), type: 'jpeg', quality: 88 });
    }
    await browser.close();
    return;
  }

  const total = Math.round(duration * FPS);
  const video = path.join(OUT, 'video_only.mp4');
  const ff = spawn(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p',
    '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
    '-movflags', '+faststart', video], { stdio: ['pipe', 'inherit', 'inherit'] });
  const started = Date.now();
  for (let f = 0; f < total; f++) {
    await page.evaluate(t => window.render(t), f / FPS);
    const buf = await stage.screenshot({ type: 'jpeg', quality: 95 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (f % 60 === 0) process.stdout.write(`frame ${f}/${total}  ${((Date.now() - started) / 1000).toFixed(0)}s\n`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await browser.close();
  console.log('video ->', video);
})();
