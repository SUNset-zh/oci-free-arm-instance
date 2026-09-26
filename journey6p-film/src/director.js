import * as THREE from 'three';
import { keys, clamp, smooth, smoother, hermite, win, lerp } from './lib/util.js';
import { Pose, setAnchor, convertPoint, UNIT } from './frames.js';
import { KeyCam, FnCam, CameraRig } from './camera.js';
import { RoadWorld, BOARD_ANCHOR, LANE_CHANGE } from './worlds/road.js';
import { BoardWorld, DIE_ANCHOR, T as BT, coverLift, pkgState, DIE_FLIP_Y, PKG } from './worlds/board.js';
import { DieWorld, NANO_ANCHOR, TILE_TOP, targetPE } from './worlds/die.js';
import { NanoWorld, LAT_ANCHOR, FIN, TGATE_X, GATE } from './worlds/nano.js';
import { LatticeWorld } from './worlds/lattice.js';

export const DURATION = 68.5;

// ------------------------------------------------------------------ zoom-out
// Hyper zoom-out: camera distance (log10 metres) as a C1 spline over time.
const ZO = { t0: 51.8 };
const ZO_KEYS = [
  [51.8, Math.log10(3.3e-10)],
  [53.0, -8.95],
  [53.7, -8.05],
  [54.5, -6.3],
  [55.1, -4.5],
  [55.8, -2.35],
  [56.5, -1.1],
  [57.1, -0.3],
  [57.8, 0.7],
  [58.8, Math.log10(26)],
];
const ZT = ZO_KEYS.map((k) => k[0]);
const ZV = ZO_KEYS.map((k) => [k[1]]);
const _z = [0];
export function zoomLog(t) { return hermite(ZT, ZV, t, 1, _z, true)[0]; }
function timeAtLog(L) {
  let lo = ZO.t0, hi = 58.8;
  for (let i = 0; i < 50; i++) { const m = (lo + hi) / 2; if (zoomLog(m) < L) lo = m; else hi = m; }
  return (lo + hi) / 2;
}
// Bands (log10 m) in which each world is shown during the zoom-out.
const BANDS = [
  ['lat', 'nano', -8.35, -7.95],
  ['nano', 'die', -4.62, -4.3],
  ['die', 'board', -1.93, -1.72],
  ['board', 'road', -0.55, -0.32],
];

export class Director {
  constructor({ renderer, post, overlay, envs, lang }) {
    this.renderer = renderer; this.post = post; this.overlay = overlay; this.envs = envs; this.lang = lang;
    this.pose = new Pose();
    this.poseA = new Pose();
    this.poseB = new Pose();
    this.aspect = 16 / 9;
    this.size = new THREE.Vector2(1920, 1080);
  }

  async init(progress) {
    const E = this.envs;
    const tick = () => new Promise((r) => setTimeout(r, 0));
    this.worlds = {};
    const order = [['road', RoadWorld], ['board', BoardWorld], ['die', DieWorld], ['nano', NanoWorld], ['lat', LatticeWorld]];
    let i = 0;
    for (const [k, C] of order) {
      this.worlds[k] = new C(E);
      this.worlds[k].init();
      progress?.(0.1 + 0.6 * (++i / order.length));
      await tick();
    }
    setAnchor('board', BOARD_ANCHOR);
    setAnchor('die', DIE_ANCHOR);
    setAnchor('nano', NANO_ANCHOR);
    setAnchor('lat', LAT_ANCHOR);
    // Zoom-out choreography: close things up just as the camera passes their scale.
    BT.reassemble = timeAtLog(Math.log10(0.024));
    BT.coverDown = timeAtLog(Math.log10(0.22));
    this.worlds.road.reassembleAt = timeAtLog(Math.log10(2.2));
    this.zoBand = BANDS.map(([a, b, l0, l1]) => ({ a, b, t0: timeAtLog(l0), t1: timeAtLog(l1) }));
    // Bakes: die face -> board, board -> PCB inside the car.
    const dieTex = this.worlds.die.bake(this.renderer);
    this.worlds.board.setDieTexture(dieTex);
    progress?.(0.8);
    await tick();
    const pcbTex = this.worlds.board.bake(this.renderer);
    this.worlds.road.setPCBTexture(pcbTex);
    this.renderer.setRenderTarget(null);
    progress?.(0.9);
    this.buildTimeline();
    this.buildOverlay();
  }

  resize(aspect) {
    this.aspect = aspect;
    for (const w of Object.values(this.worlds || {})) { w.camera.aspect = aspect; w.camera.updateProjectionMatrix(); }
    this.renderer.getDrawingBufferSize(this.size);
  }

  // ---------------------------------------------------------------- timeline
  buildTimeline() {
    const lat = this.worlds.lat;
    const ch = lat.channel; // open [110] channel (Å)
    const [pex, pez] = targetPE();
    const tracks = [];

    // A+B. Hook -> into the car (car frame, metres).
    const carCam = new KeyCam('car', [
      { t: 0.0, p: [0.0, 2.35, -7.2], l: [0, 1.0, 12], fov: 36, ap: 0.006 },
      { t: 1.9, p: [0.3, 2.05, -5.9], l: [0, 0.9, 14] },
      { t: 3.1, p: [5.3, 1.65, -4.4], l: [0, 0.8, 0.6], fov: 34 },
      { t: 4.3, p: [5.1, 1.05, 4.5], l: [0, 0.75, 0.4], ap: 0.01 },
      { t: 5.0, p: [3.3, 1.4, 5.0], l: [0, 1.0, 0.6] },
      { t: 5.8, p: [0.95, 2.15, 2.35], l: [0, 1.15, 0.35], fov: 38 },
      { t: 6.7, p: [0.34, 2.05, 1.25], l: [0, 0.62, 0.12], ap: 0.014 },
      { t: 7.5, p: [0.17, 1.35, 0.74], l: [0, 0.48, 0.2] },
      { t: 8.0, p: [0.09, 0.97, 0.52], l: [0, 0.47, 0.18] },
    ], { endZero: false });
    tracks.push(carCam);

    // C. Driving computer approach + fin fly-through (board frame, mm).
    const k0 = carCam.keyAt(8.0, 'board');
    const finCam = new KeyCam('board', [
      { ...carCam.keyAt(7.5, 'board'), t: 7.5 },
      k0,
      { t: 8.6, p: [215, 185, -12], l: [40, 40, 2.5], up: [0, 1, 0], fov: 40, ap: 0.02 },
      { t: 9.2, p: [160, 86, 1.5], l: [60, 36, 2.5] },
      { t: 9.62, p: [127, 42, 2.5], l: [40, 33.5, 2.5], fov: 44 },
      { t: 10.0, p: [72, 34, 2.5], l: [-40, 31.5, 2.5], ap: 0.03 },
      { t: 10.38, p: [36, 33, 2.4], l: [29, 32, 5.9] },
    ], { endZero: false });
    finCam.t0 = 8.0;
    tracks.push(finCam);

    // D+E+F. Highway -> hero reveal -> exploded view -> dive to die (board frame).
    const boardCam = new KeyCam('board', [
      { t: 10.38, p: [143, 0.6, -1.2], l: [100, 0.6, -3.5], fov: 44, ap: 0.02 },
      { t: 10.62, p: [133, 2.6, -8.25], l: [80, 1.6, -6.5] },
      { t: 11.15, p: [108, 2.3, -8.25], l: [60, 1.0, -4] },
      { t: 12.25, p: [86, 1.55, -3.0], l: [40, 0.7, 0], ap: 0.035 },
      { t: 13.25, p: [58, 1.25, 0.2], l: [15, 1.8, 0], fov: 42 },
      { t: 14.05, p: [37, 3.3, 0], l: [0, 3.2, 0] },
      { t: 14.95, p: [34, 9.5, 6], l: [0, 3.4, 1.5], fov: 38, ap: 0.03 },
      { t: 16.2, p: [50, 21, 56], l: [-14, 2.2, 13], fov: 34 },
      { t: 17.6, p: [32, 28, 66], l: [-17, 2, 8.4], fov: 33 },
      { t: 18.6, p: [8, 58, 88], l: [0, 6, 0], ap: 0.018 },
      { t: 20.0, p: [-34, 44, 78], l: [0, 8.5, 0] },
      { t: 21.2, p: [-40, 46, 60], l: [0, 11, 0] },
      { t: 22.4, p: [-21, 50, 33], l: [0, 16.5, 0], up: [0, 1, 0] },
      { t: 23.3, p: [-3.5, 41, 7], l: [0, 18.4, 0.3], up: [0, 0, -1], fov: 40, ap: 0.012 },
      { t: 24.1, p: [0, 29.6, 0.2], l: [0, 18.39, 0], up: [0, 0, -1] },
    ], { endZero: false });
    tracks.push(boardCam);

    // G. Die fly-over (die frame, µm).
    const tg = [pex, TILE_TOP, pez];
    const dieCam = new KeyCam('die', [
      boardCam.keyAt(23.3, 'die'),
      boardCam.keyAt(24.1, 'die'),
      { t: 25.0, p: [-300, 5200, 2700], l: [300, 0, -700], up: [0, 0.6, -0.8], fov: 42, ap: 0.012 },
      { t: 26.0, p: [700, 1500, 3500], l: [1900, 0, -2200], up: [0, 1, 0], ap: 0.02 },
      { t: 27.2, p: [1800, 480, 700], l: [2750, 0, -3400] },
      { t: 28.3, p: [2480, 230, -560], l: [pex, 0, pez - 250], ap: 0.03 },
      { t: 28.95, p: [pex - 12, 150, pez + 70], l: [pex, TILE_TOP, pez], up: [0, 0.3, -1] },
      { t: 29.5, p: [pex, TILE_TOP + 62, pez + 2], l: tg, up: [0, 0, -1], ap: 0.01 },
      { t: 29.9, p: [pex, TILE_TOP + 36, pez + 1], l: tg, up: [0, 0, -1] },
    ], { endZero: false });
    dieCam.t0 = 24.1;
    tracks.push(dieCam);

    // H. Descent through the copper stack (nano frame, nm) — log-spaced keys.
    const nk = [dieCam.keyAt(29.5, 'nano'), dieCam.keyAt(29.9, 'nano')];
    // Descent: the camera sinks down the open shaft while pitching from straight
    // down to a raking 55° and circling, so the copper layers read as stacked
    // "overpasses". Keys are log-spaced in height.
    const N = 11;
    for (let i = 1; i <= N; i++) {
      const u = i / N;
      const t = lerp(29.9, 34.25, u);
      const y = 42800 * Math.pow(300 / 42800, Math.pow(u, 0.85));
      const pitch = THREE.MathUtils.degToRad(lerp(88, 56, smooth(u * 1.4)));
      const yaw = -1.2 + 1.5 * u;
      const f = (y - FIN.top) / Math.sin(pitch);
      const dir = [Math.cos(yaw) * Math.cos(pitch), -Math.sin(pitch), Math.sin(yaw) * Math.cos(pitch)];
      const off = (1 - smooth(u * 3)) * 900;
      const p = [0, y, off];
      const l = [p[0] + dir[0] * f, p[1] + dir[1] * f, p[2] + dir[2] * f];
      const up = u < 0.25 ? [Math.cos(yaw) * 0.7, 0.7, Math.sin(yaw) * 0.7] : [0, 1, 0];
      nk.push({ t, p, l, up, fov: 46, ap: i < 3 ? 0.012 : 0.022, f });
    }
    nk.push(
      // I. Cutaway: the metal dissolves, we rise over the field of FinFETs.
      { t: 34.95, p: [70, 330, 250], l: [-20, 60, 0], up: [0, 1, 0], fov: 44, ap: 0.02 },
      { t: 35.9, p: [150, 270, 310], l: [-30, 55, 0], ap: 0.025 },
      // J. The transistor.
      { t: 36.9, p: [30, 165, 200], l: [-27, 55, 0], fov: 40 },
      { t: 38.1, p: [-14, 122, 128], l: [-27, 56, 0], ap: 0.035 },
      { t: 39.3, p: [-9, 104, 72], l: [-34, 58, 0], fov: 44 },
      { t: 39.85, p: [-46, 100, 44], l: [-30, 58, 0], fov: 48 },
      { t: 40.3, p: [-55, 74, 20], l: [-20, 58, 0], fov: 50 },
      // K. Electron POV through the channel.
      { t: 41.0, p: [-57, ch.y / 10 + FIN.top, ch.z / 10 + 1.2], l: [-5, ch.y / 10 + FIN.top, ch.z / 10], fov: 58, ap: 0.03 },
      { t: 42.2, p: [-31, ch.y / 10 + FIN.top, ch.z / 10 + 0.3], l: [20, ch.y / 10 + FIN.top, ch.z / 10] },
      { t: 43.2, p: [-12, ch.y / 10 + FIN.top, ch.z / 10], l: [30, ch.y / 10 + FIN.top, ch.z / 10] },
      { t: 43.9, p: [-7.4, ch.y / 10 + FIN.top, ch.z / 10], l: [30, ch.y / 10 + FIN.top, ch.z / 10] },
    );
    const nanoCam = new KeyCam('nano', nk, { endZero: false });
    nanoCam.t0 = 29.9;
    tracks.push(nanoCam);

    // L. Lattice glide -> single atom (lat frame, Å).
    const lk = [nanoCam.keyAt(43.2, 'lat'), nanoCam.keyAt(43.9, 'lat')];
    lk.push(
      { t: 45.2, p: [-52, ch.y, ch.z], l: [60, ch.y, ch.z], fov: 58, ap: 0.035, near: 0.08 },
      { t: 46.5, p: [-30, ch.y, ch.z + 0.3], l: [60, ch.y + 2, ch.z] },
      { t: 47.35, p: [-15.6, ch.y + 0.4, ch.z + 0.9], l: [0, ch.y + 6, 1], fov: 56 },
      // up an open [001] shaft like an elevator, out through the surface
      { t: 47.85, p: [-14.4, -8.6, 1.0], l: [0, -3, 1] },
      { t: 48.3, p: [-14.4, -4.4, 1.0], l: [0, 0, 1] },
      { t: 48.75, p: [-14.4, -0.3, 1.0], l: [0, 1, 0.8], fov: 50 },
      { t: 49.2, p: [-12.6, 3.3, 1.3], l: [0, 0, 0], fov: 48, ap: 0.05 },
      { t: 50.0, p: [-5.6, 3.6, 2.5], l: [0, 0, 0], fov: 44 },
      { t: 51.8, p: [-3.6, 2.35, 1.6], l: [0, 0, 0], fov: 42, ap: 0.06, near: 0.05 },
    );
    const latCam = new KeyCam('lat', lk, { endZero: false });
    latCam.t0 = 43.9;
    tracks.push(latCam);

    // M. Hyper zoom-out (procedural, lat frame).
    const qp = latCam.sample(51.8);
    const startDir = qp.p.clone().normalize();
    const d0 = qp.p.length();
    const upStart = new THREE.Vector3(1, 0, 0);
    this.zoomCam = new FnCam('lat', ZO.t0, 58.8, (t, pose) => {
      const L = zoomLog(t);
      const d = Math.pow(10, L) / UNIT.lat;
      const k = smoother((t - ZO.t0) / 1.6);
      const dir = startDir.clone().lerp(new THREE.Vector3(0, 1, 0), k).normalize();
      pose.p.copy(dir).multiplyScalar(Math.max(d, d0));
      pose.l.set(0, 0, 0);
      const roll = smoother((t - ZO.t0 - 0.5) / 6.5) * Math.PI * 0.5;
      const up = new THREE.Vector3(Math.cos(roll), 0, Math.sin(roll));
      pose.up.copy(new THREE.Vector3(0, 1, 0).lerp(up, k)).normalize();
      pose.fov = lerp(42, 50, smooth((t - ZO.t0) / 2.5)) - 6 * smooth((t - 57.6) / 1.2);
      pose.focus = Math.max(d, d0);
      pose.ap = lerp(0.06, 0.008, smooth((t - ZO.t0) / 1.2));
    });
    tracks.push(this.zoomCam);

    // N. Ending on the road (road frame).
    this.worlds.road.updateCarMatrix(58.8);
    setAnchor('car', this.worlds.road.carMatrix);
    const endStart = this.zoomCam.sample(58.8).to('road');
    const endCam = new KeyCam('road', [
      { t: 58.8, p: endStart.p.toArray(), l: endStart.l.toArray(), up: endStart.up.toArray(), fov: endStart.fov, ap: 0.004, f: endStart.focus },
      { t: 60.2, p: [-5.2, 8.0, -10.5], l: [1.2, 0.6, 9], up: [0, 1, 0], fov: 38, ap: 0.006 },
      { t: 61.4, p: [-3.0, 2.5, -9.4], l: [2.4, 0.95, 9] },
      { t: 62.8, p: [1.6, 1.65, -7.8], l: [3.6, 0.95, 6], fov: 36 },
      { t: 64.8, p: [2.7, 4.2, -15], l: [3.6, 1.0, 6] },
      { t: 67.2, p: [3.1, 10.5, -34], l: [3.6, 0.8, 22], fov: 34 },
      { t: 68.5, p: [3.2, 12.5, -40], l: [3.6, 0.8, 24] },
    ]);
    tracks.push(endCam);

    this.rig = new CameraRig(tracks);

    // World schedule for the zoom-in: [world, t0, t1] + crossfades [a, b, t0, t1].
    this.schedule = [
      { a: 'road', t0: -1, t1: 8.95 },
      { a: 'road', b: 'board', t0: 8.95, t1: 9.45 },
      { a: 'board', t0: 9.45, t1: 23.65 },
      { a: 'board', b: 'die', t0: 23.65, t1: 24.1 },
      { a: 'die', t0: 24.1, t1: 29.45 },
      { a: 'die', b: 'nano', t0: 29.45, t1: 29.9 },
      { a: 'nano', t0: 29.9, t1: 43.45 },
      { a: 'nano', b: 'lat', t0: 43.45, t1: 44.05 },
      { a: 'lat', t0: 44.05, t1: this.zoBand[0].t0 },
    ];
    for (let i = 0; i < this.zoBand.length; i++) {
      const b = this.zoBand[i];
      this.schedule.push({ a: b.a, b: b.b, t0: b.t0, t1: b.t1 });
      const next = this.zoBand[i + 1];
      this.schedule.push({ a: b.b, t0: b.t1, t1: next ? next.t0 : DURATION + 1 });
    }
  }

  fx(t) {
    const zo = clamp((t - 52.4) / 5.8);
    const fx = {
      exposure: 1.0,
      fade: keys(t, [[0, 0], [0.25, 1, 'out2'], [67.4, 1], [68.5, 0, 'in2']]),
      worldLight: keys(t, [[0, 0], [1.9, 0], [3.1, 1, 'inOut2']]),
      lidar: keys(t, [[0, 1], [2.5, 1], [3.9, 0, 'inOut2']]),
      boxes: keys(t, [[0, 0], [1.05, 0], [1.3, 1], [3.0, 1], [3.7, 0]]),
      streams: keys(t, [[0, 0], [4.9, 0], [6.4, 1, 'inOut2'], [56.6, 1]]),
      streamAlpha: keys(t, [[0, 1], [9.2, 1], [9.6, 0], [56.6, 0], [57.2, 0.9], [59.0, 0.9], [60.2, 0]]),
      ribbon: keys(t, [[0, 0], [59.0, 0], [59.5, 1], [61.9, 1], [62.8, 0]]),
      bloom: 0.9,
      bloomThreshold: keys(t, [[0, 1.0], [9.4, 1.0], [9.6, 1.4], [23.8, 1.4], [24.2, 1.0]]),
      bloomKnee: 0.6,
      zoomBlur: Math.max(
        keys(t, [[0, 0], [10.2, 0], [10.36, 0.28, 'in2'], [10.7, 0, 'out2']]),
        keys(t, [[0, 0], [9.5, 0], [9.8, 0.06], [10.2, 0]]),
        keys(t, [[0, 0], [23.4, 0], [23.9, 0.1], [24.4, 0]]),
        keys(t, [[0, 0], [29.3, 0], [29.8, 0.08], [30.6, 0.05], [33.6, 0.05], [34.3, 0]]),
        keys(t, [[0, 0], [52.3, 0], [53.4, 0.12, 'in2'], [55.3, 0.32], [57.4, 0.18], [58.6, 0, 'out2']]),
      ),
      vignette: 0.42,
      grain: 0.03,
      ca: 0.001 + 0.004 * Math.sin(Math.PI * zo),
      sat: keys(t, [[0, 1], [49, 1], [49.8, 0.75], [51.8, 0.75], [52.6, 1]]),
      dofMax: 0.03,
      traceFlow: 1,
      dieGlow: 1,
      wave: 1,
      wireFlow: 1,
      sea: keys(t, [[0, 0], [34.2, 0], [35.0, 1], [58, 1]]),
      iso: keys(t, [[0, 0], [36.6, 0], [37.3, 1], [44.2, 1], [44.8, 0]]),
      electrons: keys(t, [[0, 0], [37.1, 0], [37.8, 1], [44.4, 1], [44.9, 0], [53.4, 0]]),
      channel: 1,
      latElectrons: keys(t, [[0, 0], [43.4, 0], [43.9, 1], [47.4, 1], [48.3, 0]]),
      atomCloud: keys(t, [[0, 0], [48.9, 0], [50.0, 1, 'inOut2'], [52.3, 1], [53.1, 0]]),
      latAlpha: keys(t, [[0, 1], [43.4, 0.3], [45.6, 1, 'inOut2']]),
      metal: keys(t, [[0, 1], [34.0, 1], [34.9, 0, 'inOut2'], [53.3, 0], [53.9, 1]]),
      consoleLight: keys(t, [[0, 0], [6.4, 0], [7.8, 1], [9.6, 1], [9.8, 0], [56.5, 0], [57.0, 0.7], [58.6, 0]]),
      scaleAlpha: keys(t, [[0, 0], [4.7, 0], [5.6, 1], [62.2, 1], [63.2, 0]]),
    };
    return fx;
  }

  // Which world(s) to render at time t.
  layersAt(t) {
    for (const s of this.schedule) {
      if (t >= s.t0 && t < s.t1) {
        if (!s.b) return { a: s.a, b: null, blend: 0 };
        return { a: s.a, b: s.b, blend: smooth((t - s.t0) / (s.t1 - s.t0)) };
      }
    }
    return { a: 'road', b: null, blend: 0 };
  }

  // ---------------------------------------------------------------- overlay
  buildOverlay() {
    const O = this.overlay;
    const cues = [
      { t0: 2.1, t1: 4.45, en: 'How small is a car’s intelligence?', zh: '一辆车的智能，究竟藏在多小的地方？' },
      { t0: 4.75, t1: 6.3, en: 'Let’s go smaller.', zh: '往里走。', style: 'big' },
      { t0: 15.25, t1: 18.35, en: 'JOURNEY 6P', zh: '征程 6P', style: 'hero', pos: 'left', fi: 0.9, fo: 0.6,
        extra: [{ cls: 'rule', text: '' }, { cls: 'meta', text: 'HORIZON ROBOTICS · 地平线 · INTELLIGENT DRIVING SoC' }] },
      { t0: 18.75, t1: 20.1, en: 'Smaller.', zh: '更小。', style: 'big', pos: 'upper' },
      { t0: 24.45, t1: 26.0, en: 'Much smaller.', zh: '小得多。', style: 'big' },
      { t0: 34.35, t1: 36.45, en: 'Billions of switches.', zh: '数十亿个开关。' },
      { t0: 40.55, t1: 42.6, en: 'Now, you are an electron.', zh: '现在，你是一个电子。' },
      { t0: 44.6, t1: 47.1, en: 'From meters to nanometers.', zh: '从米，到纳米。' },
      { t0: 49.9, t1: 51.7, en: 'One silicon atom.', zh: '一个硅原子。', style: 'small', fi: 0.8,
        extra: [{ cls: 'meta', text: '' }] },
      { t0: 62.5, t1: 65.3, en: 'From silicon to intelligence.', zh: '从硅，到智能。', style: 'end', pos: 'mid', fi: 0.8, fo: 0.7 },
      { t0: 65.5, t1: 68.3, en: 'JOURNEY 6P', zh: '征程 6P', style: 'brand', pos: 'mid', fi: 0.9, fo: 0.8,
        extra: [{ cls: 'meta', text: 'HORIZON ROBOTICS · 地平线' }] },
      { t0: 65.9, t1: 68.3, en: 'Chip internals are illustrative visualizations, not the actual Journey 6P layout.',
        zh: '芯片内部结构为示意性可视化，并非 Journey 6P 实际版图。', style: 'fine', pos: 'low', fi: 0.8, fo: 0.8 },
    ];
    cues.forEach((c) => O.addCue(c));
    const labels = [
      { world: 'road', frame: 'board', at: [60, 46, -60], t0: 7.25, t1: 8.95, text: 'Driving computer', zh: '智能驾驶计算平台', dx: 140, dy: -90 },
      { world: 'board', frame: 'board', at: (t) => [14, 3.9 + 26 * pkgState(t).lidUp + 2 * pkgState(t).lidOut, -95 * pkgState(t).lidOut - 14], t0: 19.55, t1: 21.4, text: 'Lid', zh: '金属顶盖', dx: -120, dy: -50 },
      { world: 'board', frame: 'board', at: (t) => { const s = pkgState(t); const y = lerp(PKG.sub1 + 0.47 + 10 * s.layers, DIE_FLIP_Y, s.flip); return [9, y, 7]; }, t0: 19.85, t1: 22.9, text: 'Silicon die', zh: '硅晶粒', dx: 160, dy: -60 },
      { world: 'board', frame: 'board', at: (t) => [-8.5, PKG.sub1 + 0.06 + 4.5 * pkgState(t).layers, 7.5], t0: 20.15, t1: 22.7, text: 'Bumps', zh: '微凸点', dx: -170, dy: 30 },
      { world: 'board', frame: 'board', at: [-20, 1.2, 20], t0: 20.45, t1: 22.7, text: 'Substrate', zh: '封装基板', dx: -150, dy: 70 },
      { world: 'die', frame: 'die', at: [5200, TILE_TOP, -3000], t0: 26.3, t1: 28.1, text: 'Parallel compute array', zh: '并行计算阵列', dx: 150, dy: -110 },
      { world: 'nano', frame: 'nano', at: [6000, 6800, 1200], t0: 30.7, t1: 32.4, text: 'Copper interconnect', zh: '铜互连', dx: 150, dy: -80 },
      { world: 'nano', frame: 'nano', at: [TGATE_X, GATE.top, -40], t0: 37.3, t1: 40.0, text: 'Transistor', zh: '晶体管', dx: -170, dy: -90 },
      { world: 'nano', frame: 'nano', at: [TGATE_X, GATE.top, 20], t0: 37.7, t1: 38.9, text: 'OFF · 0', dx: 120, dy: -40 },
      { world: 'nano', frame: 'nano', at: [TGATE_X, GATE.top, 20], t0: 39.0, t1: 40.2, text: 'ON · 1', dx: 120, dy: -40 },
      { world: 'lat', frame: 'lat', at: [8, 0, -10], t0: 45.0, t1: 46.9, text: 'Silicon crystal', zh: '硅晶格', dx: 130, dy: -70 },
      { world: 'lat', frame: 'lat', at: [0, 0, 0], t0: 49.8, t1: 51.5, text: 'Si · 14 e⁻', dx: 150, dy: 80 },
    ];
    labels.forEach((l) => O.addLabel(l));
  }

  // Sound design hooks (times of events).
  audioCues() {
    return {
      duration: DURATION,
      zoomOut: [ZO.t0, 58.8],
      hits: [2.0, 9.45, 10.38, 14.95, 23.9, 29.7, 43.8, 58.8],
      whoosh: [[4.8, 6.4], [9.3, 10.4], [10.38, 11.2], [23.2, 24.3], [29.2, 30.4], [40.3, 41.4]],
      tick: [0.4, 1.0, 1.6],
      quiet: [48.9, 51.8],
      switchOn: 38.9,
      laneChange: LANE_CHANGE,
      bands: this.zoBand.map((b) => b.t1),
    };
  }

  // ---------------------------------------------------------------- render
  // Debug: ?world=board&pose=board:px,py,pz:lx,ly,lz:fov[:ap]
  setDebug(world, poseStr) {
    this.debugWorld = world || null;
    if (poseStr) {
      const [frame, p, l, fov, ap] = poseStr.split(':');
      const P = new Pose();
      P.frame = frame; P.p.set(...p.split(',').map(Number)); P.l.set(...l.split(',').map(Number));
      P.fov = Number(fov || 40); P.ap = Number(ap || 0); P.focus = P.p.distanceTo(P.l);
      this.debugPose = P;
    }
  }

  render(t) {
    const W = this.worlds;
    const road = W.road;
    road.updateCarMatrix(t);
    setAnchor('car', road.carMatrix);
    const pose = this.debugPose ? this.pose.copy(this.debugPose) : this.rig.sample(t, this.pose);
    const fx = this.fx(t);
    const L = this.debugWorld ? { a: this.debugWorld, b: null, blend: 0 } : this.layersAt(t);
    this.renderer.getDrawingBufferSize(this.size);
    const ctx = { fx, pixelHeight: this.size.y, coverLift, t };
    const layers = [];
    const views = {};
    for (const [name, poseOut] of [[L.a, this.poseA], [L.b, this.poseB]]) {
      if (!name) continue;
      const w = W[name];
      pose.to(w.frame, poseOut);
      w.update(t, poseOut, ctx);
      poseOut.apply(w.camera, w.nearMul, w.farMul, w.farMax, w.nearMin);
      if (w.preRender) w.preRender(this.renderer, w.camera, this.size);
      layers.push({ scene: w.scene, camera: w.camera, focus: poseOut.focus, ap: poseOut.ap });
      views[name] = { camera: w.camera, frame: w.frame, toWorld: (v, frame) => convertPoint(v, frame, w.frame) };
    }
    this.post.render(layers, L.b ? L.blend : 0, fx, t);
    this.overlay.update(t, { views, scaleMetres: pose.widthMetres(this.aspect), scaleAlpha: fx.scaleAlpha });
    this.last = { t, L, pose };
  }

  debugText() {
    const l = this.last;
    if (!l) return '';
    return `${l.L.a}${l.L.b ? ` → ${l.L.b} ${(l.L.blend * 100).toFixed(0)}%` : ''}  frame ${l.pose.frame}  f ${l.pose.focus.toFixed(3)}`;
  }
}
