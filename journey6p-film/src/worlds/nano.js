import * as THREE from 'three';
import { clamp, smooth, smoother, rng, lerp, win } from '../lib/util.js';
import { anchorFrom } from '../frames.js';

// NANO WORLD — copper interconnect stack and FinFETs, in nanometres.
// A clear vertical "shaft" at x = z = 0 runs through every metal layer; the
// camera descends through it and the zoom-out climbs back up through it.
// Structures are physically plausible for a modern FinFET node, but generic.

export const LAYERS = [
  // name, direction ('x' = runs along x), pitch, width, thickness, y bottom
  { n: 'M1', d: 'x', p: 40, w: 20, t: 36, y: 150 },
  { n: 'M2', d: 'z', p: 42, w: 21, t: 40, y: 222 },
  { n: 'M3', d: 'x', p: 84, w: 42, t: 70, y: 300 },
  { n: 'M4', d: 'z', p: 168, w: 84, t: 130, y: 440 },
  { n: 'M5', d: 'x', p: 336, w: 168, t: 250, y: 690 },
  { n: 'M6', d: 'z', p: 800, w: 400, t: 500, y: 1150 },
  { n: 'M7', d: 'x', p: 1800, w: 900, t: 1000, y: 2050 },
  { n: 'M8', d: 'z', p: 4000, w: 2000, t: 2400, y: 4400 },
];
export const FIN = { w: 7, top: 62, sti: 20, pitch: 30 };
export const GATE = { pitch: 54, len: 16, top: 80 };
export const CELL = { h: 240, zc: 30 };
export const TGATE_X = -27; // the transistor we visit (gate over fin z = 0)
// Lattice frame (ångström) sits on the top surface of our fin, in the drain.
export const LAT_ANCHOR = anchorFrom({ position: [0, FIN.top, 0], scale: 0.1 });

const WIRE_VERT = /* glsl */`
attribute vec4 aInfo; // dir (0 x, 1 z, 2 via), pitch, seed, extent
varying vec3 vW; varying vec3 vN; flat varying vec4 vInfo; varying vec3 vL;
void main() {
  vec4 w = modelMatrix * instanceMatrix * vec4(position, 1.0);
  vW = w.xyz; vL = position;
  vN = normalize(mat3(modelMatrix) * mat3(instanceMatrix) * normal);
  vInfo = aInfo;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const WIRE_FRAG = /* glsl */`
precision highp float;
uniform vec3 uCamPos; uniform vec3 uKey; uniform float uTime; uniform float uFlow; uniform float uLightR;
uniform vec3 uBase; uniform float uFade; uniform float uFogScale; uniform vec3 uLampPos; uniform float uClip;
varying vec3 vW; varying vec3 vN; flat varying vec4 vInfo; varying vec3 vL;
float h11(float p) { return fract(sin(p * 78.233) * 43758.5453); }
void main() {
  vec3 N = normalize(vN);
  vec3 V = normalize(uCamPos - vW);
  vec3 L = normalize(uKey);
  vec3 cu = uBase;
  // Copper is a metal: no diffuse, colour lives in the reflections.
  vec3 H = normalize(L + V);
  float nh = max(dot(N, H), 0.0);
  float sp = pow(nh, 90.0) * 4.0 + pow(nh, 12.0) * 0.18;
  float dc = length(uCamPos - vW);
  // Wires that come too close to the lens dissolve (dithered) instead of clipping.
  float dz = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
  if (dc < uClip * (0.75 + 0.5 * dz)) discard;
  vec3 toL = uLampPos - vW;
  float dl = length(toL);
  vec3 Lc = toL / dl;
  float att = 1.0 / (1.0 + pow(dl / uLightR, 2.0));
  float nlc = max(dot(N, Lc), 0.0);
  float spc = pow(max(dot(N, normalize(Lc + V)), 0.0), 60.0);
  // Procedural studio reflections: two soft boxes and a dim gradient.
  vec3 R = reflect(-V, N);
  float e1 = smoothstep(0.8, 0.97, dot(R, normalize(vec3(-0.45, 0.8, 0.4))));
  float e2 = smoothstep(0.72, 0.95, dot(R, normalize(vec3(0.75, 0.3, -0.6))));
  float e3 = smoothstep(0.9, 0.99, dot(R, normalize(vec3(0.1, 0.45, 0.9))));
  float grad = 0.015 + 0.05 * smoothstep(-0.3, 1.0, R.y);
  vec3 env = vec3(1.0, 0.98, 0.95) * (e1 * 1.3 + e2 * 0.55 + e3 * 0.8 + grad);
  float fr = pow(1.0 - max(dot(N, V), 0.0), 5.0);
  vec3 F = cu + (vec3(1.0) - cu) * fr;
  vec3 col = F * env + cu * (sp * max(dot(N, L), 0.0) * 0.6 + spc * 2.0 * att);
  // lit edges of the wire tops read as fine bright lines
  col += cu * smoothstep(0.35, 0.5, max(abs(vL.x), abs(vL.z))) * step(0.5, N.y) * 0.25 * (0.3 + att);
  // current pulses travelling along the wire
  float dir = vInfo.x, pitch = vInfo.y, seed = vInfo.z;
  if (dir < 1.5) {
    float s = (dir < 0.5 ? vW.x : vW.z) / pitch;
    float x = s * 0.35 - uTime * 1.6 + seed * 7.0;
    float id = floor(x), f = fract(x);
    float on = step(0.72, h11(id + seed * 13.0));
    float pk = on * smoothstep(0.0, 0.04, f) * (1.0 - smoothstep(0.08, 0.3, f));
    col += vec3(0.45, 0.8, 1.0) * pk * 2.2 * uFlow;
  }
  // detail fades toward the edge of the modelled patch
  float r = length(vW.xz);
  float fade = smoothstep(vInfo.w, vInfo.w * 0.45, r);
  // depth haze relative to the current viewing scale
  float fog = 1.0 - exp(-dc / uFogScale);
  col = mix(col, vec3(0.0), fog);
  gl_FragColor = vec4(col * fade * uFade, 1.0);
}`;

const FIN_VERT = /* glsl */`
varying vec3 vW; varying vec3 vN;
void main() {
  vec4 w = modelMatrix * instanceMatrix * vec4(position, 1.0);
  vW = w.xyz; vN = normalize(mat3(modelMatrix) * mat3(instanceMatrix) * normal);
  gl_Position = projectionMatrix * viewMatrix * w;
}`;
const FIN_FRAG = /* glsl */`
precision highp float;
uniform vec3 uCamPos; uniform vec3 uKey; uniform float uOn; uniform float uAlpha; uniform float uAtoms;
uniform float uLightR; uniform float uInside;
varying vec3 vW; varying vec3 vN;
float grid(vec2 p, float period) {
  vec2 f = abs(fract(p / period) - 0.5);
  vec2 w = fwidth(p / period);
  float d = length(f);
  float dots = 1.0 - smoothstep(0.18, 0.18 + length(w) * 1.5, d);
  return mix(dots, 0.1, smoothstep(0.15, 0.4, length(w)));
}
void main() {
  vec3 N = normalize(vN);
  if (!gl_FrontFacing) N = -N;
  vec3 V = normalize(uCamPos - vW);
  float fres = pow(1.0 - abs(dot(N, V)), 2.5);
  vec3 si = vec3(0.12, 0.2, 0.34);
  float nl = max(dot(N, normalize(uKey)), 0.0);
  float dc = length(uCamPos - vW);
  float att = 1.0 / (1.0 + pow(dc / uLightR, 2.0));
  vec3 col = si * (0.35 + nl * 0.9 + att * 0.4) * (0.45 + fres * 1.4);
  col += vec3(0.3, 0.6, 1.0) * pow(fres, 2.0) * 0.6;
  // glowing ridge along the fin top
  col += vec3(0.35, 0.65, 1.0) * smoothstep(59.5, 62.0, vW.y) * 0.4 * (gl_FrontFacing ? 1.0 : 0.2);
  if (!gl_FrontFacing) col *= 0.3;
  // doped source/drain regions read slightly warmer
  float sd = 1.0 - smoothstep(6.0, 9.0, abs(mod(vW.x + 27.0, 54.0) - 27.0));
  col = mix(col, col * vec3(1.25, 1.05, 0.85), sd * 0.6);
  // crystal: atom rows resolve when close
  vec2 pa = abs(N.y) > 0.5 ? vW.xz : (abs(N.x) > 0.5 ? vW.zy : vW.xy);
  float at = grid(pa, 0.384);
  col += vec3(0.5, 0.65, 0.9) * at * uAtoms * 0.35;
  // conducting channel under our gate when ON
  float ch = (1.0 - smoothstep(7.0, 10.0, abs(vW.x + 27.0))) * (1.0 - smoothstep(4.0, 6.0, abs(vW.z)));
  col += vec3(0.35, 0.75, 1.0) * ch * uOn * 0.9;
  float a = clamp(0.28 + fres * 0.6, 0.0, 1.0) * uAlpha;
  if (!gl_FrontFacing) a *= 0.4;
  // from inside our fin, the neighbours recede so the tunnel stays dark
  a *= mix(1.0, 0.18, uInside * step(5.0, abs(vW.z)));
  gl_FragColor = vec4(col * a, a);
}`;

const GATE_FRAG = /* glsl */`
precision highp float;
uniform vec3 uCamPos; uniform vec3 uKey; uniform float uTime; uniform float uTarget; uniform float uSea; uniform float uLightR;
uniform float uIso;
varying vec3 vW; varying vec3 vN; flat varying float vOn; flat varying float vTgt;
void main() {
  vec3 N = normalize(vN);
  vec3 V = normalize(uCamPos - vW);
  vec3 L = normalize(uKey);
  vec3 base = vec3(0.2, 0.17, 0.14);
  float nl = max(dot(N, L), 0.0);
  float sp = pow(max(dot(N, normalize(L + V)), 0.0), 50.0);
  float dc = length(uCamPos - vW);
  float att = 1.0 / (1.0 + pow(dc / uLightR, 2.0));
  float fres = pow(1.0 - max(dot(N, V), 0.0), 3.0);
  vec3 R = reflect(-V, N);
  float env = smoothstep(0.8, 0.97, dot(R, normalize(vec3(-0.45, 0.8, 0.4)))) + 0.4 * smoothstep(0.72, 0.95, dot(R, normalize(vec3(0.75, 0.3, -0.6))));
  vec3 col = base * (0.05 + nl * 0.7 + att * 0.35) + vec3(0.75, 0.72, 0.68) * (sp * 0.4 + env * 0.25) + vec3(0.25, 0.3, 0.4) * fres * 0.2;
  float e = mix(vOn * uSea * (1.0 - uIso), uTarget, vTgt);
  col += vec3(0.18, 0.55, 1.0) * e * 0.55;
  col *= mix(1.0, mix(0.35, 1.0, vTgt), uIso);
  gl_FragColor = vec4(col, 1.0);
}`;
const GATE_VERT = /* glsl */`
attribute float aSeed; attribute float aTgt;
uniform float uTime;
varying vec3 vW; varying vec3 vN; flat varying float vOn; flat varying float vTgt;
float h11v(float p) { return fract(sin(p * 78.233) * 43758.5453); }
void main() {
  vec4 w = modelMatrix * instanceMatrix * vec4(position, 1.0);
  vW = w.xyz; vN = normalize(mat3(modelMatrix) * mat3(instanceMatrix) * normal);
  // each gate flips on/off at its own rhythm (computed once per instance)
  float rate = 1.5 + 3.0 * h11v(aSeed);
  float ph = uTime * rate + h11v(aSeed + 3.0) * 10.0;
  float on = smoothstep(0.35, 0.5, fract(ph)) * (1.0 - smoothstep(0.85, 1.0, fract(ph)));
  vOn = on * step(0.25, h11v(aSeed + 7.0));
  vTgt = aTgt;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const E_VERT = /* glsl */`
attribute float aBright;
uniform float uSize;
varying vec2 vUv; varying float vB;
void main() {
  vUv = uv;
  vec4 c = viewMatrix * modelMatrix * instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  float near = clamp(-c.z / (uSize * 6.0), 0.15, 1.0);
  vB = aBright * near;
  c.xy += position.xy * uSize * near;
  gl_Position = projectionMatrix * c;
}`;
const E_FRAG = /* glsl */`
precision highp float;
uniform float uAlpha;
varying vec2 vUv; varying float vB;
void main() {
  float d = length(vUv - 0.5) * 2.0;
  float a = exp(-d * d * 6.0) * 0.7 + exp(-d * 18.0) * 1.6;
  gl_FragColor = vec4(vec3(0.45, 0.8, 1.0) * a * uAlpha * vB, 1.0);
}`;

export class NanoWorld {
  constructor(envs) {
    this.name = 'nano';
    this.frame = 'nano';
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x000000);
    this.camera = new THREE.PerspectiveCamera(40, 16 / 9, 1, 1e6);
    this.envs = envs;
    this.nearMul = 0.012; this.farMul = 60; this.farMax = 4e5; this.nearMin = 0.02;
  }

  init() {
    const S = this.scene;
    const r = rng(314);
    const key = new THREE.Vector3(-0.5, 0.75, 0.45).normalize();
    this.key = key;
    this.wireMat = new THREE.ShaderMaterial({
      vertexShader: WIRE_VERT, fragmentShader: WIRE_FRAG,
      uniforms: {
        uCamPos: { value: new THREE.Vector3() }, uKey: { value: key }, uTime: { value: 0 }, uFlow: { value: 1 },
        uLightR: { value: 1000 }, uBase: { value: new THREE.Color(0.95, 0.58, 0.4) }, uFade: { value: 1 }, uFogScale: { value: 1e5 },
        uLampPos: { value: new THREE.Vector3() }, uClip: { value: 0 },
      },
    });
    // --- metal layers ------------------------------------------------------
    const wires = [];
    const vias = [];
    LAYERS.forEach((L, li) => {
      const N = li < 5 ? 44 : li === 5 ? 40 : li === 6 ? 34 : 30;
      const ext = N * L.p;
      for (let k = -N; k < N; k++) {
        const c = (k + 0.5) * L.p; // track position (z for 'x' lines, x for 'z' lines)
        let s = -ext;
        const seg = r.range(0, 4) * L.p;
        s += seg;
        while (s < ext) {
          const len = L.p * (li > 5 ? r.range(6, 30) : r.range(3, 16));
          const e = Math.min(ext, s + len);
          wires.push({ L, li, c, s0: s, s1: e, ext });
          s = e + L.p * r.range(0.8, 2.5);
        }
      }
    });
    // Vias between consecutive layers at crossings (avoiding the shaft).
    for (let li = 0; li < LAYERS.length - 1; li++) {
      const A = LAYERS[li], B = LAYERS[li + 1];
      const n = li < 4 ? 1400 : li < 6 ? 700 : 400;
      for (let i = 0; i < n; i++) {
        const ka = r.int(-30, 29), kb = r.int(-30, 29);
        const ca = (ka + 0.5) * A.p, cb = (kb + 0.5) * B.p;
        const x = A.d === 'z' ? ca : cb, z = A.d === 'z' ? cb : ca;
        if (Math.abs(x) < B.p && Math.abs(z) < B.p) continue;
        const size = Math.min(A.w, B.w) * 0.9;
        vias.push({ x, z, y0: A.y + A.t, y1: B.y, size, ext: Math.min(30 * A.p, 30 * B.p) });
      }
    }
    const box = new THREE.BoxGeometry(1, 1, 1);
    const count = wires.length + vias.length;
    const info = new Float32Array(count * 4);
    const wm = new THREE.InstancedMesh(box.clone(), this.wireMat, count);
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    let i = 0;
    for (const w of wires) {
      const { L } = w;
      const mid = (w.s0 + w.s1) / 2, len = w.s1 - w.s0;
      if (L.d === 'x') m.compose(new THREE.Vector3(mid, L.y + L.t / 2, w.c), q, new THREE.Vector3(len, L.t, L.w));
      else m.compose(new THREE.Vector3(w.c, L.y + L.t / 2, mid), q, new THREE.Vector3(L.w, L.t, len));
      wm.setMatrixAt(i, m);
      info.set([L.d === 'x' ? 0 : 1, L.p, r() * 10, w.ext], i * 4);
      i++;
    }
    for (const v of vias) {
      m.compose(new THREE.Vector3(v.x, (v.y0 + v.y1) / 2, v.z), q, new THREE.Vector3(v.size, v.y1 - v.y0, v.size));
      wm.setMatrixAt(i, m);
      info.set([2, 1, 0, v.ext], i * 4);
      i++;
    }
    wm.geometry.setAttribute('aInfo', new THREE.InstancedBufferAttribute(info, 4));
    wm.frustumCulled = false;
    S.add(wm);
    this.wires = wm;

    // --- front end: substrate, STI, fins, gates, contacts --------------------
    this.fe = new THREE.Group();
    S.add(this.fe);
    const PATCH_X = 600, ROWS = [-2, -1, 0, 1, 2];
    const sub = new THREE.Mesh(new THREE.BoxGeometry(PATCH_X * 2.4, 40, CELL.h * 6), new THREE.MeshStandardMaterial({ color: 0x151a24, roughness: 0.55, metalness: 0.3, envMap: this.envs.lab }));
    sub.position.y = -20 + FIN.sti - 0.1;
    this.fe.add(sub);
    const stiMat = new THREE.MeshStandardMaterial({ color: 0x0b0f18, roughness: 0.18, metalness: 0.2, envMap: this.envs.lab, envMapIntensity: 1.2 });
    const sti = new THREE.Mesh(new THREE.PlaneGeometry(PATCH_X * 2.4, CELL.h * 6), stiMat);
    sti.rotation.x = -Math.PI / 2; sti.position.y = FIN.sti;
    this.fe.add(sti);
    // Fins (translucent crystal).
    this.finMat = new THREE.ShaderMaterial({
      vertexShader: FIN_VERT, fragmentShader: FIN_FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      uniforms: { uCamPos: { value: new THREE.Vector3() }, uKey: { value: key }, uOn: { value: 0 }, uAlpha: { value: 1 }, uAtoms: { value: 0 }, uLightR: { value: 200 }, uInside: { value: 0 } },
    });
    const finZ = [];
    for (const row of ROWS) {
      const zc = CELL.zc + row * CELL.h;
      for (const off of [-60, -30, 60, 90]) finZ.push(zc + off);
    }
    this.finZ = finZ;
    const fins = new THREE.InstancedMesh(box.clone(), this.finMat, finZ.length);
    finZ.forEach((z, k) => {
      m.compose(new THREE.Vector3(0, (FIN.top + FIN.sti) / 2 - 4, z), q, new THREE.Vector3(PATCH_X * 2, FIN.top - FIN.sti + 8, FIN.w));
      fins.setMatrixAt(k, m);
    });
    fins.renderOrder = 2;
    this.fe.add(fins);
    this.fins = fins;
    // Gates: metal that wraps each fin on three sides (pieces between fins + caps over fins).
    const gatePieces = [];
    const ox = 1.6; // high-k gate dielectric gap
    for (let g = -11; g < 11; g++) {
      const gx = (g + 0.5) * GATE.pitch;
      for (const row of ROWS) {
        const zc = CELL.zc + row * CELL.h;
        const z0 = zc - CELL.h / 2 + 12, z1 = zc + CELL.h / 2 - 12;
        const fz = finZ.filter((z) => z > z0 && z < z1).sort((a, b) => a - b);
        const seed = g * 13.1 + row * 7.7;
        const tgt = Math.abs(gx - TGATE_X) < 1 && row === 0 ? 1 : 0;
        let zs = z0;
        for (const f of fz) {
          const a = zs, b = f - FIN.w / 2 - ox;
          if (b > a) gatePieces.push({ x: gx, y0: FIN.sti, y1: GATE.top, z0: a, z1: b, seed, tgt });
          gatePieces.push({ x: gx, y0: FIN.top + ox, y1: GATE.top, z0: f - FIN.w / 2 - ox, z1: f + FIN.w / 2 + ox, seed, tgt });
          zs = f + FIN.w / 2 + ox;
        }
        gatePieces.push({ x: gx, y0: FIN.sti, y1: GATE.top, z0: zs, z1, seed, tgt });
      }
    }
    this.gateMat = new THREE.ShaderMaterial({
      vertexShader: GATE_VERT, fragmentShader: GATE_FRAG,
      uniforms: {
        uCamPos: { value: new THREE.Vector3() }, uKey: { value: key }, uTime: { value: 0 }, uTarget: { value: 0 }, uSea: { value: 0 },
        uLightR: { value: 200 }, uIso: { value: 0 },
      },
    });
    const gGeo = box.clone();
    const gSeed = new Float32Array(gatePieces.length), gTgt = new Float32Array(gatePieces.length);
    const gates = new THREE.InstancedMesh(gGeo, this.gateMat, gatePieces.length);
    gatePieces.forEach((p, k) => {
      m.compose(new THREE.Vector3(p.x, (p.y0 + p.y1) / 2, (p.z0 + p.z1) / 2), q, new THREE.Vector3(GATE.len, p.y1 - p.y0, p.z1 - p.z0));
      gates.setMatrixAt(k, m);
      gSeed[k] = p.seed; gTgt[k] = p.tgt;
    });
    gGeo.setAttribute('aSeed', new THREE.InstancedBufferAttribute(gSeed, 1));
    gGeo.setAttribute('aTgt', new THREE.InstancedBufferAttribute(gTgt, 1));
    this.fe.add(gates);
    this.gates = gates;
    // Spacers (silicon nitride) on both sides of every gate.
    const spMat = new THREE.MeshStandardMaterial({ color: 0x5b6270, roughness: 0.6, metalness: 0.1, envMap: this.envs.lab, transparent: true, opacity: 0.55, depthWrite: false });
    const sp = new THREE.InstancedMesh(box.clone(), spMat, 22 * ROWS.length * 2);
    let si = 0;
    for (let g = -11; g < 11; g++) for (const row of ROWS) for (const s of [-1, 1]) {
      const zc = CELL.zc + row * CELL.h;
      m.compose(new THREE.Vector3((g + 0.5) * GATE.pitch + s * (GATE.len / 2 + 2.5), (FIN.sti + GATE.top - 8) / 2, zc), q, new THREE.Vector3(5, GATE.top - 8 - FIN.sti, CELL.h - 24));
      sp.setMatrixAt(si++, m);
    }
    sp.renderOrder = 1;
    // (spacers kept out of the scene: they cluttered the read of fin vs gate)
    // Trench contacts on some source/drain regions (never in the shaft).
    const cMat = new THREE.MeshStandardMaterial({ color: 0x8e939c, roughness: 0.35, metalness: 1, envMap: this.envs.lab });
    const contacts = [];
    for (let g = -10; g < 10; g++) for (const row of ROWS) {
      const x = g * GATE.pitch;
      if (Math.abs(x) < 1 && row === 0) continue;
      if (r() < 0.45) continue;
      const zc = CELL.zc + row * CELL.h;
      const n = r() < 0.5 ? -1 : 1;
      contacts.push({ x, z: zc + n * 45 + (n > 0 ? 30 : -30) * 0.5 });
    }
    const cm = new THREE.InstancedMesh(box.clone(), cMat, contacts.length);
    contacts.forEach((c, k) => { m.compose(new THREE.Vector3(c.x, (FIN.top + 116) / 2, c.z), q, new THREE.Vector3(12, 116 - FIN.top, 36)); cm.setMatrixAt(k, m); });
    this.fe.add(cm);

    // --- electrons -------------------------------------------------------------
    this.eN = 420;
    const eg = new THREE.PlaneGeometry(1, 1);
    const eb = new Float32Array(this.eN);
    for (let k = 0; k < this.eN; k++) eb[k] = 0.5 + r() * 0.8;
    eg.setAttribute('aBright', new THREE.InstancedBufferAttribute(eb, 1));
    this.eMat = new THREE.ShaderMaterial({
      vertexShader: E_VERT, fragmentShader: E_FRAG, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uSize: { value: 2.2 }, uAlpha: { value: 1 } },
    });
    this.electrons = new THREE.InstancedMesh(eg, this.eMat, this.eN);
    this.electrons.frustumCulled = false;
    this.electrons.renderOrder = 5;
    this.eSeeds = Array.from({ length: this.eN }, () => [r(), r(), r(), r()]);
    S.add(this.electrons);
  }

  // Cumulative "gate open" time: electrons advance only while the gate conducts.
  gateOn(t) {
    // OFF (blocked) until 38.9, then ON.
    return smooth((t - 38.9) / 0.35);
  }
  flow(t) {
    // integral of gateOn from 38.9
    const a = 38.9;
    if (t <= a) return 0;
    return Math.max(0, t - a - 0.175);
  }

  update(t, pose, ctx) {
    const cam = pose.p;
    const h = Math.max(1, cam.y - FIN.top);
    const wu = this.wireMat.uniforms;
    wu.uCamPos.value.copy(cam);
    wu.uTime.value = t;
    wu.uLightR.value = Math.max(40, pose.focus * 1.2);
    // Lamp rides above-left of the camera, off the lens axis, so surfaces model.
    const camObj = this.camera;
    const off = new THREE.Vector3(-0.55, 0.45, 0.25).multiplyScalar(pose.focus * 0.6);
    wu.uLampPos.value.copy(cam).add(off);
    wu.uClip.value = Math.max(0, cam.y - FIN.top) * 0.12;
    wu.uFogScale.value = Math.max(60, pose.focus * 1.8);
    wu.uFlow.value = ctx.fx.wireFlow ?? 1;
    const cut = ctx.fx.metal ?? 1;
    wu.uFade.value = cut;
    this.wires.visible = cut > 0.003;
    // Front end only matters once we are low enough.
    this.fe.visible = cam.y < 9000;
    const on = this.gateOn(t);
    const fu = this.finMat.uniforms;
    fu.uCamPos.value.copy(cam);
    fu.uOn.value = on * (ctx.fx.channel ?? 1);
    fu.uLightR.value = Math.max(20, pose.focus * 1.5);
    fu.uAtoms.value = smooth((25 - pose.focus) / 18);
    fu.uInside.value = (Math.abs(cam.z) < 6 && cam.y < FIN.top + 3) ? 1 : 0;
    const gu = this.gateMat.uniforms;
    gu.uCamPos.value.copy(cam);
    gu.uTime.value = t;
    gu.uTarget.value = on;
    gu.uSea.value = ctx.fx.sea ?? 0;
    gu.uIso.value = ctx.fx.iso ?? 0;
    gu.uLightR.value = Math.max(30, pose.focus * 1.5);

    // Electrons along our fin (z = 0), plus a few in neighbours.
    const m = new THREE.Matrix4();
    const vis = ctx.fx.electrons ?? 0;
    this.electrons.visible = vis > 0.001;
    this.eMat.uniforms.uAlpha.value = vis;
    this.eMat.uniforms.uSize.value = clamp(pose.focus * 0.02, 0.35, 2.6);
    if (vis > 0.001) {
      const F = this.flow(t);
      const L = 260; // loop length (nm)
      for (let k = 0; k < this.eN; k++) {
        const [a, b, c, d] = this.eSeeds[k];
        const speed = 22 + 16 * c;
        // Position along the loop; blocked electrons pile up at the source side of the gate.
        let x = -140 + ((a * L + F * speed) % L);
        const gateEdge = TGATE_X - GATE.len / 2 - 2;
        if (on < 0.5 && x > gateEdge - 2 && x < 40) x = gateEdge - 2 - b * 30;
        if (on < 0.5 && x > 40) x = -140 + b * 60;
        const jitter = 0.7 * Math.sin(t * (7 + 5 * d) + k);
        const y = FIN.sti + 6 + (FIN.top - FIN.sti - 9) * (0.25 + 0.75 * b) + jitter;
        const z = (c - 0.5) * (FIN.w - 2) + 0.5 * Math.cos(t * (6 + 4 * a) + k * 0.7);
        m.makeTranslation(x, y, z);
        this.electrons.setMatrixAt(k, m);
      }
      this.electrons.instanceMatrix.needsUpdate = true;
    }
  }
}
