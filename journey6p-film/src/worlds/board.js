import * as THREE from 'three';
import { clamp, smooth, smoother, rng, lerp } from '../lib/util.js';
import { RoundedBoxGeometry } from '../lib/rounded.js';
import { canvasTexture } from '../lib/env.js';
import { buildHousing, housingMaterials, HOUSING, fins } from './housing.js';
import { anchorFrom } from '../frames.js';

// BOARD WORLD — the driving computer, in millimetres.
// PCB top at y = 0, SoC (Journey 6P package) centred at the origin.

export const PKG = { size: 45, sub0: 0.45, sub1: 1.65, die: [18, 0.78, 16], lid: 40, lidTop: 3.9 };
export const DIE_FLIP_Y = 18; // die centre height once flipped face-up (exploded)
export const DIE_ANCHOR = anchorFrom({ position: [0, DIE_FLIP_Y + PKG.die[1] / 2, 0], scale: 0.001 });

// Exploded-view choreography (all pure functions of time).
export const T = {
  coverUp: 10.3, // housing cover lifts off after the fin fly-through
  lidUp: 18.7, lidOut: 19.5, layers: 19.0, dieFlip: 21.0,
  reassemble: 56.5, // package closes again during the zoom-out
  coverDown: 57.0,
};

export function coverLift(t) {
  const up = smoother((t - T.coverUp) / 1.6);
  const down = smoother((t - T.coverDown) / 0.8);
  const k = up * (1 - down);
  return { x: -30 * k, y: 140 * k, z: -260 * smoother((t - T.coverUp - 0.4) / 1.6) * (1 - down), rz: 0.12 * k };
}

export function pkgState(t) {
  const close = smoother((t - T.reassemble) / 0.7);
  const lidUp = smoother((t - T.lidUp) / 1.0) * (1 - close);
  const lidOut = smoother((t - T.lidOut) / 1.3) * (1 - smoother((t - T.reassemble + 0.2) / 0.6));
  const layers = smoother((t - T.layers) / 1.4) * (1 - close);
  const flip = smoother((t - T.dieFlip) / 1.5) * (1 - smoother((t - T.reassemble) / 0.55));
  return { lidUp, lidOut, layers, flip, close };
}

const TRACE_VERT = /* glsl */`
attribute float aS; attribute float aSeed; attribute float aDir;
varying float vS; varying float vSeed; varying vec3 vW; varying vec3 vN;
void main() {
  vS = aS; vSeed = aSeed;
  vec4 w = modelMatrix * vec4(position, 1.0);
  vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal);
  gl_Position = projectionMatrix * viewMatrix * w;
}`;
const TRACE_FRAG = /* glsl */`
precision highp float;
uniform float uTime; uniform float uFlow; uniform vec3 uCamPos; uniform vec3 uKey;
varying float vS; varying float vSeed; varying vec3 vW; varying vec3 vN;
float h11(float p) { return fract(sin(p * 78.233) * 43758.5453); }
void main() {
  vec3 V = normalize(uCamPos - vW);
  vec3 N = normalize(vN);
  // copper under glossy solder mask
  vec3 base = vec3(0.028, 0.05, 0.036);
  float diff = max(dot(N, normalize(uKey)), 0.0);
  vec3 H = normalize(normalize(uKey) + V);
  float spec = pow(max(dot(N, H), 0.0), 90.0) * 1.2;
  float fres = pow(1.0 - max(dot(N, V), 0.0), 4.0);
  vec3 col = base * (0.25 + diff * 1.4) + vec3(0.7, 0.85, 0.8) * spec * 0.25 + vec3(0.06, 0.1, 0.09) * fres;
  // data packets
  float x = vS * 0.9 - uTime * 42.0 * 0.9 + vSeed * 17.0;
  float id = floor(x);
  float f = fract(x);
  float on = step(0.35, h11(id * 1.7 + vSeed * 3.1));
  float len = 0.18 + 0.25 * h11(id + 9.1);
  float pk = on * smoothstep(0.0, 0.03, f) * (1.0 - smoothstep(len * 0.4, len, f));
  col += vec3(0.45, 0.85, 1.0) * pk * 6.0 * uFlow;
  col += vec3(0.25, 0.55, 0.8) * 0.04 * uFlow;
  gl_FragColor = vec4(col, 1.0);
}`;

export class BoardWorld {
  constructor(envs) {
    this.name = 'board';
    this.frame = 'board';
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x000000);
    this.camera = new THREE.PerspectiveCamera(40, 16 / 9, 1, 5000);
    this.envs = envs;
    this.nearMul = 0.01; this.farMul = 60; this.farMax = 6000; this.nearMin = 0.02;
  }

  init() {
    const S = this.scene;
    const env = this.envs.studio;
    this.S = S;
    this.parts = [];
    const r = rng(1234);

    // ---------------------------------------------------------------- lights
    const key = new THREE.DirectionalLight(0xfff4e8, 2.4);
    key.position.set(-120, 260, 140);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    const sc = key.shadow.camera;
    sc.left = -150; sc.right = 150; sc.top = 150; sc.bottom = -150; sc.near = 50; sc.far = 700;
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.05;
    S.add(key, key.target);
    this.key = key;
    const rim1 = new THREE.DirectionalLight(0xcfe2ff, 1.3); rim1.position.set(220, 80, -200); S.add(rim1);
    const rim2 = new THREE.DirectionalLight(0xffe0c0, 0.6); rim2.position.set(-240, 60, -120); S.add(rim2);
    this.amb = new THREE.HemisphereLight(0x3a4250, 0x050505, 0.35); S.add(this.amb);
    // Sweep light for the hero reveal.
    this.sweep = new THREE.SpotLight(0xffffff, 0, 400, 0.22, 0.8, 1.2);
    this.sweep.position.set(0, 140, 0);
    S.add(this.sweep, this.sweep.target);

    // ---------------------------------------------------------------- housing
    this.hm = housingMaterials(env);
    this.housing = buildHousing(this.hm);
    this.housing.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    S.add(this.housing);

    // ---------------------------------------------------------------- PCB
    this.layout = this.planLayout(r);
    const { color, bump } = this.pcbTextures(this.layout);
    this.pcbMat = new THREE.MeshPhysicalMaterial({
      map: color, bumpMap: bump, bumpScale: 1.4, roughness: 0.42, metalness: 0.0,
      clearcoat: 0.7, clearcoatRoughness: 0.22, envMap: env, envMapIntensity: 0.9,
    });
    const edgeMat = new THREE.MeshStandardMaterial({ color: 0x1b2a1c, roughness: 0.8 });
    const pcb = new THREE.Mesh(new THREE.BoxGeometry(HOUSING.pcbX * 2, 1.6, HOUSING.pcbZ * 2), [edgeMat, edgeMat, this.pcbMat, edgeMat, edgeMat, edgeMat]);
    pcb.position.y = -0.8;
    pcb.receiveShadow = true;
    S.add(pcb);
    this.pcb = pcb;

    // ---------------------------------------------------------------- components
    this.buildComponents(r);
    this.buildPackage();
    this.buildTraces();

    this.envRot = new THREE.Euler();
  }

  // ------------------------------------------------------------------ layout
  planLayout(r) {
    const L = { ics: [], caps: [], res: [], inductors: [], ecaps: [], holes: [] };
    const push = (arr, o) => arr.push(o);
    // LPDDR x4 flanking the SoC.
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) push(L.ics, { x: sx * 11, z: sz * 42.5, w: 12.4, d: 14, h: 1.0, kind: 'dram', text: 'LPDDR5' });
    // Deserializers near the camera connectors.
    [-33, -11, 11, 33].forEach((z) => push(L.ics, { x: 82, z, w: 10, d: 10, h: 0.9, kind: 'qfn', text: 'DES' }));
    push(L.ics, { x: -60, z: 22, w: 8, d: 8, h: 0.9, kind: 'qfn', text: 'PMIC' });
    push(L.ics, { x: -60, z: -22, w: 8, d: 8, h: 0.9, kind: 'qfn', text: 'PMIC' });
    push(L.ics, { x: -46, z: -56, w: 14, d: 14, h: 1.4, kind: 'qfp', text: 'MCU' });
    push(L.ics, { x: 58, z: -60, w: 12, d: 12, h: 1.0, kind: 'qfn', text: 'ETH' });
    push(L.ics, { x: 50, z: 58, w: 6, d: 8, h: 0.8, kind: 'qfn', text: 'NOR' });
    push(L.ics, { x: 32, z: 60, w: 5, d: 5, h: 0.8, kind: 'qfn', text: 'PHY' });
    push(L.ics, { x: -30, z: 60, w: 7, d: 7, h: 0.9, kind: 'qfn', text: 'PMIC' });
    // Power inductors & bulk caps on the -x side.
    for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) push(L.inductors, { x: -84 + i * 13, z: (j ? 1 : -1) * (12 + 0), s: 10, h: 5 });
    for (const z of [-44, 44]) for (const x of [-100, -88]) push(L.ecaps, { x, z, rad: 4, h: 9 });
    // Mounting holes.
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) push(L.holes, { x: sx * 105, z: sz * 70 });
    // Decoupling caps ring around the SoC.
    const ring = (half, n, w, d) => {
      for (let i = 0; i < n; i++) {
        const u = (i + 0.5) / n;
        const s = -half + u * half * 2;
        push(L.caps, { x: s, z: -half - 2.2, w, d, rot: 0 });
        push(L.caps, { x: s, z: half + 2.2, w, d, rot: 0 });
        if (Math.abs(s) < half - 4) { push(L.caps, { x: -half - 2.2, z: s, w, d, rot: 1 }); }
      }
    };
    ring(PKG.size / 2, 22, 1.0, 0.5);
    ring(PKG.size / 2 + 1.4, 18, 1.6, 0.8);
    // Around DRAMs and deserializers.
    for (const ic of L.ics) {
      const n = ic.kind === 'dram' ? 10 : 6;
      for (let i = 0; i < n; i++) {
        const side = i % 4;
        const u = r.range(-0.4, 0.4);
        const off = 1.8 + r.range(0, 1.5);
        let x = ic.x, z = ic.z;
        if (side === 0) { x += u * ic.w; z += ic.d / 2 + off; }
        if (side === 1) { x += u * ic.w; z -= ic.d / 2 + off; }
        if (side === 2) { z += u * ic.d; x += ic.w / 2 + off; }
        if (side === 3) { z += u * ic.d; x -= ic.w / 2 + off; }
        if (ic.kind === 'qfn' && ic.x > 70 && (side === 3)) continue; // keep the highway clear
        push(L.caps, { x, z, w: 1.0, d: 0.5, rot: side >= 2 ? 1 : 0 });
      }
    }
    // Scatter small passives in free space (avoid the highway band and big parts).
    const blocked = (x, z) => {
      if (Math.abs(z) < 19 && x > 20 && x < 112) return true; // highway
      if (Math.abs(x) < 27 && Math.abs(z) < 27) return true;
      for (const ic of L.ics) if (Math.abs(x - ic.x) < ic.w / 2 + 2 && Math.abs(z - ic.z) < ic.d / 2 + 2) return true;
      for (const q of L.inductors) if (Math.abs(x - q.x) < 7 && Math.abs(z - q.z) < 7) return true;
      for (const q of L.ecaps) if (Math.hypot(x - q.x, z - q.z) < 6) return true;
      if (x > 100) return true;
      return false;
    };
    let tries = 0;
    while (L.res.length < 420 && tries < 20000) {
      tries++;
      const x = r.range(-108, 100), z = r.range(-74, 74);
      if (blocked(x, z)) continue;
      const big = r() < 0.2;
      push(L.res, { x, z, w: big ? 1.6 : 1.0, d: big ? 0.8 : 0.5, rot: r() < 0.5 ? 1 : 0, cap: r() < 0.6 });
    }
    return L;
  }

  pcbTextures(L) {
    const W = 4096, H = Math.round(4096 * (160 / 230));
    const sx = W / 230, sz = H / 160;
    const X = (x) => (x + 115) * sx;
    const Z = (z) => (z + 80) * sz; // v grows with +z (BoxGeometry top face: v runs along -z, handled via flipY)
    const r = rng(77);
    const drawBoth = (fn) => { fn(this._cg, 'color'); fn(this._bg, 'bump'); };
    const color = canvasTexture(W, H, (g) => {
      this._cg = g;
      g.fillStyle = '#06110c'; g.fillRect(0, 0, W, H);
      // Subtle mottling of the solder mask.
      for (let i = 0; i < 1400; i++) {
        g.fillStyle = `rgba(${r() < 0.5 ? '20,40,30' : '0,0,0'},${r.range(0.02, 0.06)})`;
        const s = r.range(20, 160);
        g.beginPath(); g.arc(r() * W, r() * H, s, 0, Math.PI * 2); g.fill();
      }
    }, { mipmaps: true });
    const bump = canvasTexture(W, H, (g) => { this._bg = g; g.fillStyle = '#000'; g.fillRect(0, 0, W, H); }, { srgb: false });
    const cg = this._cg, bg = this._bg;
    const line = (g, pts, w, style) => {
      g.strokeStyle = style; g.lineWidth = w; g.lineJoin = 'round'; g.lineCap = 'round';
      g.beginPath(); pts.forEach(([x, z], i) => (i ? g.lineTo(X(x), Z(z)) : g.moveTo(X(x), Z(z)))); g.stroke();
    };
    const trace = (pts, wmm = 0.12) => {
      line(cg, pts, wmm * sx, '#0f2419');
      line(bg, pts, wmm * sx, '#ffffff');
    };
    // Copper pours (power planes on top layer).
    const pour = (x0, z0, x1, z1) => {
      cg.fillStyle = '#0a1a12'; cg.fillRect(X(x0), Z(z0), (x1 - x0) * sx, (z1 - z0) * sz);
      bg.fillStyle = '#9a9a9a'; bg.fillRect(X(x0), Z(z0), (x1 - x0) * sx, (z1 - z0) * sz);
      // thermal-relief slots
      cg.fillStyle = '#06110c';
      for (let i = 0; i < 6; i++) cg.fillRect(X(lerp(x0, x1, r())), Z(lerp(z0, z1, r())), r.range(8, 30), r.range(3, 6));
    };
    pour(-112, -34, -50, 34);
    pour(-112, 38, -60, 76);
    pour(-40, 62, 20, 77);
    // DDR fan-out with length-matching serpentines.
    for (const ic of L.ics.filter((i) => i.kind === 'dram')) {
      const n = 26;
      for (let k = 0; k < n; k++) {
        const u = (k / (n - 1) - 0.5) * (ic.w - 1.2);
        const x0 = ic.x + u;
        const z0 = ic.z - Math.sign(ic.z) * (ic.d / 2);
        const z1 = Math.sign(ic.z) * (PKG.size / 2 + 0.5);
        const pts = [[x0, z0]];
        const zm = lerp(z0, z1, 0.45);
        // serpentine segment
        const amp = 0.5 + (k % 5) * 0.15;
        const segs = 3 + (k % 4);
        for (let s = 0; s <= segs * 2; s++) {
          const zz = lerp(z0, zm, s / (segs * 2));
          pts.push([x0 + (s % 2 ? amp : 0) * (k % 2 ? 1 : -1), zz]);
        }
        const xt = x0 * 0.85;
        pts.push([xt, lerp(zm, z1, 0.5)], [xt, z1]);
        trace(pts, 0.1);
      }
    }
    // Random routed nets between passives / ICs (45 degree style).
    for (let i = 0; i < 520; i++) {
      let x = r.range(-110, 108), z = r.range(-76, 76);
      if (Math.abs(z) < 19 && x > 22 && x < 112) continue;
      if (Math.abs(x) < 24 && Math.abs(z) < 24) continue;
      const pts = [[x, z]];
      const steps = r.int(2, 5);
      for (let s = 0; s < steps; s++) {
        const len = r.range(3, 22);
        const dir = r.int(0, 7) * (Math.PI / 4);
        x += Math.cos(dir) * len; z += Math.sin(dir) * len;
        x = clamp(x, -112, 112); z = clamp(z, -77, 77);
        if (Math.abs(z) < 19 && x > 22 && x < 112) break;
        pts.push([x, z]);
      }
      if (pts.length > 1) trace(pts, r() < 0.15 ? 0.35 : 0.12);
    }
    // Vias.
    for (let i = 0; i < 2600; i++) {
      const x = r.range(-112, 112), z = r.range(-77, 77);
      if (Math.abs(z) < 18 && x > 24 && x < 110) continue;
      cg.fillStyle = '#1a3024'; cg.beginPath(); cg.arc(X(x), Z(z), 0.22 * sx, 0, Math.PI * 2); cg.fill();
      cg.fillStyle = '#040806'; cg.beginPath(); cg.arc(X(x), Z(z), 0.1 * sx, 0, Math.PI * 2); cg.fill();
      bg.fillStyle = '#bbbbbb'; bg.beginPath(); bg.arc(X(x), Z(z), 0.22 * sx, 0, Math.PI * 2); bg.fill();
    }
    // Via fence along the highway (signal-integrity stitching).
    for (let x = 24; x < 76; x += 1.6) for (const z of [-17.5, 17.5]) {
      cg.fillStyle = '#1d3528'; cg.beginPath(); cg.arc(X(x), Z(z), 0.25 * sx, 0, Math.PI * 2); cg.fill();
    }
    // Pads & silkscreen.
    const gold = '#b8954e';
    const silk = 'rgba(214,220,210,0.85)';
    const pads = (x, z, w, d, rot) => {
      const pw = rot ? d : w, pd = rot ? w : d;
      cg.fillStyle = gold;
      if (rot) { cg.fillRect(X(x - pw / 2), Z(z - pd / 2 - 0.1), pw * sx, 0.35 * pd * sz); cg.fillRect(X(x - pw / 2), Z(z + pd / 2 - 0.35 * pd + 0.1), pw * sx, 0.35 * pd * sz); }
      else { cg.fillRect(X(x - pw / 2 - 0.1), Z(z - pd / 2), 0.35 * pw * sx, pd * sz); cg.fillRect(X(x + pw / 2 - 0.35 * pw + 0.1), Z(z - pd / 2), 0.35 * pw * sx, pd * sz); }
    };
    for (const c of [...L.caps, ...L.res]) pads(c.x, c.z, c.w * 1.25, c.d * 1.25, c.rot);
    cg.font = `${Math.round(1.1 * sx)}px Helvetica, Arial, sans-serif`;
    cg.textBaseline = 'middle';
    const box = (x, z, w, d, label) => {
      cg.strokeStyle = silk; cg.lineWidth = 0.15 * sx;
      cg.strokeRect(X(x - w / 2 - 1), Z(z - d / 2 - 1), (w + 2) * sx, (d + 2) * sz);
      cg.beginPath(); cg.arc(X(x - w / 2 - 1.8), Z(z - d / 2 - 1.8), 0.35 * sx, 0, Math.PI * 2); cg.fillStyle = silk; cg.fill();
      if (label) { cg.fillStyle = silk; cg.fillText(label, X(x - w / 2 - 1), Z(z + d / 2 + 2.4)); }
    };
    L.ics.forEach((ic, i) => box(ic.x, ic.z, ic.w, ic.d, `U${i + 2}`));
    box(0, 0, PKG.size, PKG.size, 'U1');
    L.inductors.forEach((q, i) => box(q.x, q.z, q.s, q.s, `L${i + 1}`));
    let ci = 100;
    for (const c of L.res) if (r() < 0.25) { cg.fillStyle = 'rgba(214,220,210,0.7)'; cg.font = `${Math.round(0.8 * sx)}px Helvetica`; cg.fillText(`${c.cap ? 'C' : 'R'}${ci++}`, X(c.x + 0.9), Z(c.z)); }
    // SoC BGA land pattern peeking around the package edge + mounting holes.
    for (const h of L.holes) {
      cg.fillStyle = gold; cg.beginPath(); cg.arc(X(h.x), Z(h.z), 3.2 * sx, 0, Math.PI * 2); cg.fill();
      cg.fillStyle = '#020302'; cg.beginPath(); cg.arc(X(h.x), Z(h.z), 1.7 * sx, 0, Math.PI * 2); cg.fill();
    }
    // Board marking.
    cg.fillStyle = 'rgba(214,220,210,0.8)';
    cg.font = `${Math.round(2.2 * sx)}px Helvetica, Arial, sans-serif`;
    cg.fillText('ADCU-A  REV B', X(-104), Z(-74));
    cg.font = `${Math.round(1.4 * sx)}px Helvetica, Arial, sans-serif`;
    cg.fillText('CAM 1-8', X(96), Z(-74));
    // Canvas row 0 is z = -80; BoxGeometry's +y face has v = 1 at z = -80 (default flipY).
    color.needsUpdate = true; bump.needsUpdate = true;
    return { color, bump };
  }

  // ------------------------------------------------------------------ parts
  buildComponents(r) {
    const S = this.S, L = this.layout, env = this.envs.studio;
    const blackIC = new THREE.MeshStandardMaterial({ color: 0x0d0d0f, roughness: 0.62, metalness: 0.05, envMap: env, envMapIntensity: 0.7 });
    const addShadow = (m) => { m.castShadow = true; m.receiveShadow = true; S.add(m); return m; };
    // ICs with laser-marked tops.
    for (const ic of L.ics) {
      const tex = canvasTexture(256, 256, (g, w, h) => {
        g.fillStyle = '#101012'; g.fillRect(0, 0, w, h);
        g.fillStyle = 'rgba(190,190,195,0.55)';
        g.font = '600 38px Helvetica, Arial, sans-serif'; g.textAlign = 'center';
        g.fillText(ic.text, w / 2, h * 0.45);
        g.font = '24px Helvetica, Arial, sans-serif';
        g.fillText(`${2400 + ((ic.x * 7 + ic.z * 3) & 255)}A`, w / 2, h * 0.68);
        g.beginPath(); g.arc(28, 28, 10, 0, Math.PI * 2); g.fillStyle = 'rgba(0,0,0,0.9)'; g.fill();
      });
      const top = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.6, metalness: 0.05, envMap: env, envMapIntensity: 0.7 });
      const m = new THREE.Mesh(new RoundedBoxGeometry(ic.w, ic.h, ic.d, 2, 0.12), blackIC);
      m.position.set(ic.x, ic.h / 2, ic.z);
      addShadow(m);
      const cap = new THREE.Mesh(new THREE.PlaneGeometry(ic.w * 0.94, ic.d * 0.94), top);
      cap.rotation.x = -Math.PI / 2;
      cap.position.set(ic.x, ic.h + 0.002, ic.z);
      S.add(cap);
      if (ic.kind === 'qfp') {
        // Gull-wing leads.
        const lead = new THREE.BoxGeometry(0.25, 0.15, 1.2);
        const leadM = new THREE.MeshStandardMaterial({ color: 0xc8c8c8, metalness: 1, roughness: 0.3, envMap: env });
        const n = 25;
        const im = new THREE.InstancedMesh(lead, leadM, n * 4);
        const mm = new THREE.Matrix4();
        let k = 0;
        for (let side = 0; side < 4; side++) for (let i = 0; i < n; i++) {
          const u = (i / (n - 1) - 0.5) * (ic.w - 2);
          const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), (side * Math.PI) / 2);
          const p = new THREE.Vector3(u, 0.2, ic.d / 2 + 0.5).applyQuaternion(q).add(new THREE.Vector3(ic.x, 0, ic.z));
          mm.compose(p, q, new THREE.Vector3(1, 1, 1));
          im.setMatrixAt(k++, mm);
        }
        addShadow(im);
      }
    }
    // Passives: instanced ceramic caps (tan body, silver terminals) and resistors (black).
    const capBody = new THREE.MeshStandardMaterial({ color: 0x8a7458, roughness: 0.55, envMap: env, envMapIntensity: 0.5 });
    const resBody = new THREE.MeshStandardMaterial({ color: 0x141414, roughness: 0.5, envMap: env, envMapIntensity: 0.5 });
    const term = new THREE.MeshStandardMaterial({ color: 0xd8d8d8, roughness: 0.3, metalness: 1, envMap: env });
    const all = [...L.caps.map((c) => ({ ...c, cap: true })), ...L.res];
    const caps = all.filter((c) => c.cap), res = all.filter((c) => !c.cap);
    const inst = (list, bodyMat) => {
      const body = new THREE.InstancedMesh(new RoundedBoxGeometry(1, 1, 1, 1, 0.08), bodyMat, list.length);
      const ends = new THREE.InstancedMesh(new RoundedBoxGeometry(1, 1, 1, 1, 0.08), term, list.length * 2);
      const m = new THREE.Matrix4();
      list.forEach((c, i) => {
        const h = c.d * 0.9;
        const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), c.rot ? Math.PI / 2 : 0);
        m.compose(new THREE.Vector3(c.x, h / 2, c.z), q, new THREE.Vector3(c.w * 0.62, h, c.d));
        body.setMatrixAt(i, m);
        for (const s of [-1, 1]) {
          const off = new THREE.Vector3(s * c.w * 0.39, 0, 0).applyQuaternion(q);
          m.compose(new THREE.Vector3(c.x + off.x, h / 2, c.z + off.z), q, new THREE.Vector3(c.w * 0.22, h * 1.02, c.d * 1.02));
          ends.setMatrixAt(i * 2 + (s > 0 ? 1 : 0), m);
        }
      });
      addShadow(body); addShadow(ends);
    };
    inst(caps, capBody);
    inst(res, resBody);
    // Power inductors.
    const ferrite = new THREE.MeshStandardMaterial({ color: 0x2c2d30, roughness: 0.75, metalness: 0.2, envMap: env, envMapIntensity: 0.6 });
    for (const q of L.inductors) {
      const m = new THREE.Mesh(new RoundedBoxGeometry(q.s, q.h, q.s, 3, 0.8), ferrite);
      m.position.set(q.x, q.h / 2, q.z); addShadow(m);
    }
    // Aluminium electrolytic caps (tall cylinders — great foreground occluders).
    const can = new THREE.MeshStandardMaterial({ color: 0xa9adb3, metalness: 0.9, roughness: 0.35, envMap: env });
    const sleeve = new THREE.MeshStandardMaterial({ color: 0x151a24, roughness: 0.45, envMap: env, envMapIntensity: 0.8 });
    for (const q of L.ecaps) {
      const body = new THREE.Mesh(new THREE.CylinderGeometry(q.rad, q.rad, q.h, 40), sleeve);
      body.position.set(q.x, q.h / 2, q.z); addShadow(body);
      const top = new THREE.Mesh(new THREE.CylinderGeometry(q.rad * 0.96, q.rad * 0.96, 0.3, 40), can);
      top.position.set(q.x, q.h + 0.1, q.z); addShadow(top);
    }
    // Board-side connector shells under the housing connectors.
    const shell = new THREE.MeshStandardMaterial({ color: 0x9da1a6, metalness: 1, roughness: 0.32, envMap: env });
    for (const z of this.housing.userData.connZ) {
      const m = new THREE.Mesh(new RoundedBoxGeometry(12, 7.5, 9, 2, 0.6), shell);
      m.position.set(111, 3.75, z); addShadow(m);
      const plug = new THREE.Mesh(new THREE.BoxGeometry(6, 5, 7), blackIC);
      plug.position.set(104, 2.5, z); addShadow(plug);
    }
  }

  buildPackage() {
    const S = this.S, env = this.envs.studio;
    const P = PKG;
    this.pkg = new THREE.Group();
    S.add(this.pkg);
    // Substrate: dark laminate with gold pads + die-side caps.
    const subTex = canvasTexture(1024, 1024, (g, w, h) => {
      g.fillStyle = '#1a2118'; g.fillRect(0, 0, w, h);
      const k = w / P.size;
      g.fillStyle = 'rgba(40,60,40,0.5)';
      for (let i = 0; i < 400; i++) g.fillRect(Math.random() * w, Math.random() * h, 30, 2);
      // Die shadow region pads (under-die bump field)
      g.fillStyle = '#6f5a2e';
      for (let x = -8.6; x <= 8.6; x += 0.35) for (let z = -7.6; z <= 7.6; z += 0.35) g.fillRect((x + P.size / 2) * k - 1.2, (z + P.size / 2) * k - 1.2, 2.4, 2.4);
      // Keep-out ring and caps.
      g.strokeStyle = 'rgba(200,170,90,0.6)'; g.lineWidth = 2;
      g.strokeRect((P.size / 2 - 20.5) * k, (P.size / 2 - 20.5) * k, 41 * k, 41 * k);
      g.fillStyle = '#c8a860';
      g.beginPath(); g.moveTo(10, 10); g.lineTo(40, 10); g.lineTo(10, 40); g.fill();
    });
    const subMat = new THREE.MeshStandardMaterial({ map: subTex, roughness: 0.55, metalness: 0.15, envMap: env, envMapIntensity: 0.7 });
    const sub = new THREE.Mesh(new RoundedBoxGeometry(P.size, P.sub1 - P.sub0, P.size, 2, 0.3), subMat);
    sub.position.y = (P.sub0 + P.sub1) / 2;
    sub.castShadow = sub.receiveShadow = true;
    const subTop = new THREE.Mesh(new THREE.PlaneGeometry(P.size * 0.985, P.size * 0.985), subMat);
    subTop.rotation.x = -Math.PI / 2; subTop.position.y = P.sub1 + 0.002; subTop.receiveShadow = true;
    this.pkg.add(sub, subTop);
    // Die-side capacitors on the substrate (visible when the lid is off).
    const capM = new THREE.MeshStandardMaterial({ color: 0x8a7458, roughness: 0.5, envMap: env });
    const capG = new THREE.BoxGeometry(1.0, 0.5, 0.5);
    const capIM = new THREE.InstancedMesh(capG, capM, 48);
    const mm = new THREE.Matrix4();
    let ci = 0;
    for (let i = 0; i < 12; i++) for (const [sx, sz, rot] of [[1, 0, 1], [-1, 0, 1], [0, 1, 0], [0, -1, 0]]) {
      const u = (i / 11 - 0.5) * 30;
      const x = sx ? sx * 13.5 : u, z = sz ? sz * 12.5 : u;
      const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), rot ? Math.PI / 2 : 0);
      mm.compose(new THREE.Vector3(x, P.sub1 + 0.25, z), q, new THREE.Vector3(1, 1, 1));
      capIM.setMatrixAt(ci++, mm);
    }
    capIM.castShadow = true;
    this.pkg.add(capIM);
    // BGA balls.
    const ballG = new THREE.SphereGeometry(0.3, 10, 8);
    const solder = new THREE.MeshStandardMaterial({ color: 0xbfc3c8, metalness: 1, roughness: 0.25, envMap: env });
    const nB = 42;
    const balls = new THREE.InstancedMesh(ballG, solder, nB * nB);
    let bi = 0;
    for (let i = 0; i < nB; i++) for (let j = 0; j < nB; j++) {
      mm.makeTranslation((i - (nB - 1) / 2) * 1.0, 0.25, (j - (nB - 1) / 2) * 1.0);
      balls.setMatrixAt(bi++, mm);
    }
    this.pkg.add(balls);

    // C4 bump layer (between die and substrate).
    const bumpG = new THREE.SphereGeometry(0.075, 8, 6);
    const nx = 80, nz = 70;
    this.bumps = new THREE.InstancedMesh(bumpG, solder, nx * nz);
    bi = 0;
    for (let i = 0; i < nx; i++) for (let j = 0; j < nz; j++) {
      mm.makeTranslation((i - (nx - 1) / 2) * 0.215, 0, (j - (nz - 1) / 2) * 0.215);
      this.bumps.setMatrixAt(bi++, mm);
    }
    this.bumps.position.y = P.sub1 + 0.06;
    this.pkg.add(this.bumps);

    // Silicon die. Active face (baked die-world texture) is the local -y face.
    this.dieGroup = new THREE.Group();
    const [dw, dh, dd] = P.die;
    const siliconSide = new THREE.MeshPhysicalMaterial({ color: 0x3a3c44, metalness: 0.6, roughness: 0.18, envMap: env, envMapIntensity: 1.2 });
    const back = new THREE.MeshPhysicalMaterial({ color: 0x55586a, metalness: 0.85, roughness: 0.08, envMap: env, envMapIntensity: 1.4, iridescence: 0.25, iridescenceIOR: 1.5, iridescenceThicknessRange: [300, 500] });
    const dieBody = new THREE.Mesh(new THREE.BoxGeometry(dw, dh, dd), [siliconSide, siliconSide, back, siliconSide, siliconSide, siliconSide]);
    dieBody.castShadow = true;
    this.dieGroup.add(dieBody);
    // Active face plane with UVs matching the baked die-world image after the flip.
    const fg = new THREE.PlaneGeometry(dw, dd);
    fg.rotateX(Math.PI / 2); // face -y
    const uv = fg.attributes.uv, pos = fg.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), z = pos.getZ(i);
      uv.setXY(i, x / dw + 0.5, z / dd + 0.5);
    }
    this.faceMat = new THREE.MeshPhysicalMaterial({
      color: 0x000000, emissive: 0xffffff, emissiveIntensity: 1, roughness: 0.25, metalness: 0.2,
      envMap: env, envMapIntensity: 0.35, iridescence: 0.6, iridescenceIOR: 1.9, iridescenceThicknessRange: [250, 650],
    });
    const face = new THREE.Mesh(fg, this.faceMat);
    face.position.y = -dh / 2 - 0.003;
    this.dieGroup.add(face);
    this.dieFace = face;
    this.pkg.add(this.dieGroup);

    // TIM layer.
    this.tim = new THREE.Mesh(new THREE.BoxGeometry(dw + 0.4, 0.1, dd + 0.4), new THREE.MeshStandardMaterial({ color: 0x8a8c90, roughness: 0.8, metalness: 0.3, envMap: env }));
    this.pkg.add(this.tim);

    // Lid (IHS): nickel-plated copper with laser marking.
    const lidTex = this.lidTextures();
    this.lidMat = new THREE.MeshPhysicalMaterial({
      color: 0xd9dbde, map: lidTex.color, roughnessMap: lidTex.rough, roughness: 1, metalness: 1,
      envMap: env, envMapIntensity: 1.25, anisotropy: 0.55, clearcoat: 0.0,
    });
    this.lidSideMat = new THREE.MeshPhysicalMaterial({ color: 0xc9cbce, metalness: 1, roughness: 0.3, envMap: env, envMapIntensity: 1.1 });
    this.lid = new THREE.Group();
    const lidTop = new THREE.Mesh(new RoundedBoxGeometry(P.lid, 0.9, P.lid, 3, 0.5), this.lidSideMat);
    lidTop.position.y = P.lidTop - 0.45;
    lidTop.castShadow = true; lidTop.receiveShadow = true;
    const lidFace = new THREE.Mesh(new THREE.PlaneGeometry(P.lid - 1.0, P.lid - 1.0), this.lidMat);
    // Marking reads upright when seen from +x (the direction the camera arrives from).
    lidFace.rotation.set(-Math.PI / 2, Math.PI / 2, 0, 'YXZ'); lidFace.position.y = P.lidTop + 0.002;
    lidFace.receiveShadow = true;
    // Lid skirt/foot ring.
    const foot = new THREE.Group();
    const fgx = new THREE.BoxGeometry(P.lid, P.lidTop - P.sub1 - 0.9, 2.2), fgz = new THREE.BoxGeometry(2.2, P.lidTop - P.sub1 - 0.9, P.lid);
    for (const s of [-1, 1]) {
      const a = new THREE.Mesh(fgx, this.lidSideMat); a.position.set(0, (P.sub1 + P.lidTop - 0.9) / 2, s * (P.lid / 2 - 1.1)); foot.add(a);
      const b = new THREE.Mesh(fgz, this.lidSideMat); b.position.set(s * (P.lid / 2 - 1.1), (P.sub1 + P.lidTop - 0.9) / 2, 0); foot.add(b);
    }
    foot.traverse((o) => { if (o.isMesh) o.castShadow = true; });
    this.lid.add(lidTop, lidFace, foot);
    this.pkg.add(this.lid);
  }

  lidTextures() {
    const N = 1024;
    const draw = (g, w, h, mode) => {
      const base = mode === 'color' ? '#ffffff' : '#474747';
      g.fillStyle = base; g.fillRect(0, 0, w, h);
      // fine brushed grain
      for (let i = 0; i < 2600; i++) {
        const y = Math.random() * h;
        g.fillStyle = mode === 'color' ? `rgba(0,0,0,${Math.random() * 0.03})` : `rgba(255,255,255,${Math.random() * 0.05})`;
        g.fillRect(0, y, w, Math.random() * 1.5 + 0.3);
      }
      const mark = mode === 'color' ? 'rgba(70,72,78,0.75)' : '#b0b0b0';
      g.fillStyle = mark; g.textAlign = 'center'; g.textBaseline = 'middle';
      g.font = '500 44px "Helvetica Neue", Helvetica, Arial, sans-serif';
      g.save(); g.translate(w / 2, h * 0.3);
      g.fillText('H O R I Z O N   R O B O T I C S', 0, 0);
      g.restore();
      g.font = '300 150px "Helvetica Neue", Helvetica, Arial, sans-serif';
      g.fillText('JOURNEY', w / 2, h * 0.48);
      g.font = '500 150px "Helvetica Neue", Helvetica, Arial, sans-serif';
      g.fillText('6P', w / 2, h * 0.64);
      g.font = '32px "SF Mono", Menlo, monospace';
      g.fillText('J6P · X1 2437-0042 · e4', w / 2, h * 0.8);
      g.beginPath(); g.arc(70, 70, 16, 0, Math.PI * 2); g.fill();
      g.strokeStyle = mark; g.lineWidth = 3; g.strokeRect(40, 40, w - 80, h - 80);
    };
    return {
      color: canvasTexture(N, N, (g, w, h) => draw(g, w, h, 'color')),
      rough: canvasTexture(N, N, (g, w, h) => draw(g, w, h, 'rough'), { srgb: false }),
    };
  }

  // 3D high-speed differential pairs: deserializers -> SoC ("the highway").
  buildTraces() {
    const lanes = [];
    const serdes = [-33, -11, 11, 33];
    serdes.forEach((zs, si) => {
      for (let p = 0; p < 4; p++) {
        const pairCenterTarget = -7.5 + (si * 4 + p) * 1.0;
        for (const s of [-0.16, 0.16]) {
          const zStart = zs - 2.2 + p * 1.4 + s;
          const zEnd = pairCenterTarget + s;
          const x0 = 76.5, x1 = 64 - Math.abs(zStart - zEnd) * 0.0, xDiagEnd = x1 - Math.abs(zStart - zEnd);
          lanes.push({ pts: [[x0, zStart], [x1, zStart], [xDiagEnd, zEnd], [22.8, zEnd]], seed: si * 4 + p + (s > 0 ? 0.5 : 0) });
        }
      }
    });
    // Coax inputs: connectors -> deserializers.
    const connZ = this.housing.userData.connZ;
    connZ.forEach((zc, i) => {
      const zs = serdes[Math.min(3, Math.floor(i / 2))] + (i % 2 ? 2.5 : -2.5);
      lanes.push({ pts: [[106, zc], [96, zc], [96 - Math.abs(zc - zs) * 0.5, zs], [87.2, zs]], seed: 40 + i, w: 0.3 });
    });
    const pos = [], nrm = [], aS = [], aSeed = [], idx = [];
    let base = 0;
    for (const lane of lanes) {
      const w = lane.w || 0.12, h = 0.035;
      // resample polyline
      const pts = [];
      for (let i = 0; i < lane.pts.length - 1; i++) {
        const [ax, az] = lane.pts[i], [bx, bz] = lane.pts[i + 1];
        const len = Math.hypot(bx - ax, bz - az);
        const n = Math.max(1, Math.ceil(len / 1.5));
        for (let k = 0; k < n; k++) pts.push([lerp(ax, bx, k / n), lerp(az, bz, k / n)]);
      }
      pts.push(lane.pts[lane.pts.length - 1]);
      let s = 0;
      for (let i = 0; i < pts.length; i++) {
        const [x, z] = pts[i];
        if (i > 0) s += Math.hypot(x - pts[i - 1][0], z - pts[i - 1][1]);
        const [nx0, nz0] = pts[Math.min(i + 1, pts.length - 1)];
        const [px0, pz0] = pts[Math.max(i - 1, 0)];
        let tx = nx0 - px0, tz = nz0 - pz0; const tl = Math.hypot(tx, tz) || 1; tx /= tl; tz /= tl;
        const ox = -tz * w / 2, oz = tx * w / 2;
        // 4 verts per station: left-bottom, left-top, right-top, right-bottom (flat-ish rounded)
        pos.push(x + ox, 0.0, z + oz, x + ox * 0.7, h, z + oz * 0.7, x - ox * 0.7, h, z - oz * 0.7, x - ox, 0.0, z - oz);
        const sx = -tz, sz = tx;
        nrm.push(sx * 0.8, 0.6, sz * 0.8, sx * 0.25, 0.97, sz * 0.25, -sx * 0.25, 0.97, -sz * 0.25, -sx * 0.8, 0.6, -sz * 0.8);
        for (let k = 0; k < 4; k++) { aS.push(s); aSeed.push(lane.seed); }
        if (i > 0) {
          const a = base + (i - 1) * 4, b = base + i * 4;
          for (let k = 0; k < 3; k++) idx.push(a + k, a + k + 1, b + k, a + k + 1, b + k + 1, b + k);
        }
      }
      base += pts.length * 4;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
    g.setAttribute('aS', new THREE.Float32BufferAttribute(aS, 1));
    g.setAttribute('aSeed', new THREE.Float32BufferAttribute(aSeed, 1));
    g.setIndex(idx);
    this.traceMat = new THREE.ShaderMaterial({
      vertexShader: TRACE_VERT, fragmentShader: TRACE_FRAG,
      uniforms: { uTime: { value: 0 }, uFlow: { value: 1 }, uCamPos: { value: new THREE.Vector3() }, uKey: { value: new THREE.Vector3(-120, 260, 140).normalize() } },
    });
    this.traces = new THREE.Mesh(g, this.traceMat);
    this.traces.position.y = 0.004;
    this.S.add(this.traces);
  }

  setDieTexture(tex) {
    this.faceMat.emissiveMap = tex;
    this.faceMat.needsUpdate = true;
  }

  // Top-down bake of the whole board (used on the PCB inside the car).
  bake(renderer) {
    const rt = new THREE.WebGLRenderTarget(2048, 1424, { type: THREE.HalfFloatType, generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter, samples: 4 });
    const cam = new THREE.OrthographicCamera(-115, 115, 80, -80, 1, 1000);
    cam.position.set(0, 400, 0);
    cam.up.set(0, 0, -1);
    cam.lookAt(0, 0, 0);
    this.update(0, null, { fx: { traceFlow: 0.3 } }, true);
    const vis = this.housing.visible;
    this.housing.visible = false;
    renderer.setRenderTarget(rt);
    renderer.clear();
    renderer.render(this.scene, cam);
    renderer.setRenderTarget(null);
    this.housing.visible = vis;
    return rt.texture;
  }

  update(t, pose, ctx, baking = false) {
    // Housing cover.
    const c = coverLift(t);
    const cover = this.housing.userData.cover;
    cover.position.set(c.x, c.y, c.z);
    cover.rotation.z = c.rz;
    cover.visible = c.y < 600;

    // Package explode choreography.
    const s = pkgState(t);
    const P = PKG;
    this.lid.position.set(0, 26 * s.lidUp + 2 * s.lidOut, -95 * s.lidOut);
    this.lid.rotation.x = -0.35 * s.lidOut;
    this.lid.visible = s.lidOut < 0.999;
    this.tim.position.set(0, P.sub1 + 0.08 + P.die[1] + 0.05 + 17 * s.layers, 0);
    this.tim.visible = s.flip < 0.2;
    (this.tim.material).opacity = 1;
    const dieY0 = P.sub1 + 0.08 + P.die[1] / 2;
    const dieY1 = dieY0 + 10 * s.layers;
    const dieY = lerp(dieY1, DIE_FLIP_Y, s.flip);
    this.dieGroup.position.set(0, dieY, 0);
    this.dieGroup.rotation.x = Math.PI * s.flip;
    this.bumps.position.y = P.sub1 + 0.06 + 4.5 * s.layers;
    this.bumps.visible = true;

    // Hero light sweep & environment rotation.
    const sweepK = clamp((t - 14.4) / 3.6);
    this.sweep.intensity = baking ? 0 : 2200 * Math.sin(Math.PI * clamp((t - 14.2) / 4.2)) ** 2;
    this.sweep.position.set(lerp(-90, 90, sweepK), 120, lerp(60, -40, sweepK));
    this.sweep.target.position.set(lerp(-10, 10, sweepK), 0, 0);
    const er = -0.6 + 1.2 * smooth((t - 13.6) / 5.5) + (t > 30 ? 0 : 0);
    for (const m of [this.lidMat, this.lidSideMat]) m.envMapRotation.set(0, er, 0);

    // Traces.
    const tu = this.traceMat.uniforms;
    tu.uTime.value = t;
    tu.uFlow.value = ctx?.fx?.traceFlow ?? 1;
    if (pose) tu.uCamPos.value.copy(pose.p);
    this.faceMat.emissiveIntensity = ctx?.fx?.dieGlow ?? 1;
  }
}
