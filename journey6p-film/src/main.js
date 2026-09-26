import * as THREE from 'three';
import { Post } from './post.js';
import { Overlay } from './overlay.js';
import { makeEnvironments } from './lib/env.js';
import { Director, DURATION } from './director.js';
import { Score } from './audio.js';
import { clamp } from './lib/util.js';

const params = new URLSearchParams(location.search);
const P = {
  t: parseFloat(params.get('t') || '0'),
  freeze: params.has('freeze'),
  debug: params.has('debug'),
  lang: params.get('lang') || 'both',
  quality: params.get('q') || 'auto',
  render: params.has('render'),
  autoplay: params.has('autoplay'),
  w: parseInt(params.get('w') || '0', 10),
  h: parseInt(params.get('h') || '0', 10),
};

const stage = document.getElementById('stage');
const canvas = document.getElementById('c');
const startEl = document.getElementById('start');
const playBtn = document.getElementById('play');
const ui = document.getElementById('ui');
const dbg = document.getElementById('debug');
if (P.debug) dbg.style.display = 'block';

const renderer = new THREE.WebGLRenderer({
  canvas, antialias: false, alpha: false, stencil: false, depth: true,
  powerPreference: 'high-performance', preserveDrawingBuffer: P.render,
});
renderer.autoClear = true;
renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
renderer.toneMapping = THREE.NoToneMapping;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.setClearColor(0x000000, 1);

const post = new Post(renderer);
const overlay = new Overlay(stage, P.lang);

// ---------------------------------------------------------------- sizing
let resScale = P.quality === 'low' ? 0.6 : P.quality === 'med' ? 0.8 : 1;
const maxDpr = P.quality === 'high' ? 2 : 1.25;
function layout() {
  let W = window.innerWidth, H = window.innerHeight;
  if (P.w && P.h) { W = P.w; H = P.h; }
  const aspect = 16 / 9;
  let sw = W, sh = W / aspect;
  if (sh > H) { sh = H; sw = H * aspect; }
  sw = Math.floor(sw); sh = Math.floor(sh);
  stage.style.width = `${sw}px`;
  stage.style.height = `${sh}px`;
  document.documentElement.style.setProperty('--u', `${sw / 100}px`);
  const dpr = P.render ? 1 : Math.min(window.devicePixelRatio || 1, maxDpr);
  const pw = Math.max(2, Math.floor(sw * dpr * resScale));
  const ph = Math.max(2, Math.floor(sh * dpr * resScale));
  renderer.setPixelRatio(1);
  renderer.setSize(pw, ph, false);
  post.setSize(pw, ph, P.quality === 'low' ? 0 : 4);
  post.dofTaps = P.quality === 'low' ? 24 : 40;
  director?.resize(pw / ph);
}
window.addEventListener('resize', layout);

// ---------------------------------------------------------------- boot
let director = null;
let score = null;
const clock = { t: P.t, playing: false, last: 0, rate: 1 };

async function boot() {
  const envs = makeEnvironments(renderer);
  const setProgress = (f) => { document.getElementById('loadfill').style.width = `${Math.round(f * 100)}%`; };
  director = new Director({ renderer, post, overlay, envs, lang: P.lang });
  await director.init(setProgress);
  if (params.get('world') || params.get('pose')) director.setDebug(params.get('world'), params.get('pose'));
  layout();
  score = new Score(director.audioCues());
  // Warm up shaders by rendering a spread of times once.
  const warm = params.has('nowarm') ? [] : [0.5, 3, 7, 10.5, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 61, 65];
  for (const t of warm) director.render(t);
  renderer.compile?.(new THREE.Scene(), new THREE.PerspectiveCamera());
  director.render(P.t);
  setProgress(1);
  playBtn.classList.add('ready');
  document.getElementById('playlabel').textContent = 'PLAY';
  window.__director = director;
  window.__film = {
    ready: true,
    duration: DURATION,
    renderAt: (t) => { director.render(t); return true; },
    seek, play, pause,
    renderAudio: (sr) => score.renderOffline(sr),
    debug: (world, pose) => { director.debugPose = null; director.setDebug(world, pose); },
  };
  if (P.freeze || P.render) {
    startEl.classList.add('gone');
    director.render(P.t);
    return;
  }
  if (P.autoplay) begin();
}

function begin() {
  if (!director) return;
  startEl.classList.add('gone');
  score.start(clock.t);
  play();
}
playBtn.addEventListener('click', begin);

function play() {
  clock.playing = true;
  clock.last = performance.now();
  score?.seek(clock.t, true);
}
function pause() {
  clock.playing = false;
  score?.pause();
}
function seek(t) {
  clock.t = clamp(t, 0, DURATION);
  score?.seek(clock.t, clock.playing);
  if (!clock.playing) director.render(clock.t);
}

// ---------------------------------------------------------------- loop
const frameTimes = [];
let lastAdapt = 0;
function tick(now) {
  requestAnimationFrame(tick);
  if (!director || P.freeze || P.render) return;
  if (clock.playing) {
    const dt = Math.min(0.1, (now - clock.last) / 1000);
    clock.last = now;
    // The score is the master clock when audio is running.
    const at = score?.time();
    clock.t = at != null ? at : clock.t + dt * clock.rate;
    if (clock.t >= DURATION) { clock.t = DURATION; pause(); }
    frameTimes.push(dt);
    if (frameTimes.length > 90) frameTimes.shift();
    if (P.quality === 'auto' && now - lastAdapt > 2500 && frameTimes.length >= 60) {
      const avg = frameTimes.reduce((a, b) => a + b, 0) / frameTimes.length;
      if (avg > 1 / 45 && resScale > 0.55) { resScale = Math.max(0.55, resScale * 0.85); layout(); lastAdapt = now; frameTimes.length = 0; }
      else if (avg < 1 / 58 && resScale < 1) { resScale = Math.min(1, resScale / 0.9); layout(); lastAdapt = now; frameTimes.length = 0; }
    }
    director.render(clock.t);
  }
  updateUI();
}
requestAnimationFrame(tick);

function updateUI() {
  const f = clock.t / DURATION;
  document.getElementById('trackfill').style.width = `${(f * 100).toFixed(2)}%`;
  const s = Math.floor(clock.t);
  document.getElementById('time').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  if (P.debug && director) {
    const avg = frameTimes.length ? frameTimes.reduce((a, b) => a + b, 0) / frameTimes.length : 0;
    dbg.textContent = `t ${clock.t.toFixed(2)}  fps ${(avg ? 1 / avg : 0).toFixed(0)}  res ${resScale.toFixed(2)}\n${director.debugText()}`;
  }
}

// ---------------------------------------------------------------- controls
let uiTimer = 0;
function pokeUI() {
  ui.classList.add('show');
  document.body.classList.remove('hidecursor');
  clearTimeout(uiTimer);
  uiTimer = setTimeout(() => { ui.classList.remove('show'); if (clock.playing) document.body.classList.add('hidecursor'); }, 1800);
}
window.addEventListener('mousemove', pokeUI);
document.getElementById('track').addEventListener('click', (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  seek(((e.clientX - r.left) / r.width) * DURATION);
});
window.addEventListener('keydown', (e) => {
  if (!director) return;
  if (e.code === 'Space') { e.preventDefault(); if (startEl.classList.contains('gone')) { clock.playing ? pause() : play(); } else begin(); }
  else if (e.code === 'ArrowRight') seek(clock.t + (e.shiftKey ? 0.5 : 3));
  else if (e.code === 'ArrowLeft') seek(clock.t - (e.shiftKey ? 0.5 : 3));
  else if (e.code === 'KeyF') { const p = document.fullscreenElement ? document.exitFullscreen?.() : document.documentElement.requestFullscreen?.(); p?.catch?.(() => {}); }
  else if (e.code === 'KeyM') score?.toggleMute();
  else if (e.code === 'KeyD') { P.debug = !P.debug; dbg.style.display = P.debug ? 'block' : 'none'; }
  else if (e.code === 'Home') seek(0);
  pokeUI();
});

layout();
boot().catch((err) => {
  console.error(err);
  document.getElementById('playlabel').textContent = 'WEBGL ERROR';
});
