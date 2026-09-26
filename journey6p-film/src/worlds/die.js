import * as THREE from 'three';
import { clamp, smooth, rng } from '../lib/util.js';
import { anchorFrom } from '../frames.js';

// DIE WORLD — the silicon die's active face, in micrometres.
// An *illustrative* SoC floorplan (not Journey 6P's real layout): CPU cores,
// caches, media blocks, memory PHYs and two large parallel compute arrays.

export const DIE = { hx: 9000, hz: 8000 };
export const CLUSTER = { x0: 600, x1: 7850, z0: -6850, z1: 2300, cols: 8, rows: 9, base: 6, tileH: 20 };
CLUSTER.px = (CLUSTER.x1 - CLUSTER.x0) / CLUSTER.cols;
CLUSTER.pz = (CLUSTER.z1 - CLUSTER.z0) / CLUSTER.rows;
CLUSTER.tw = CLUSTER.px - 66;
CLUSTER.td = CLUSTER.pz - 66;
export const PE_N = 16;
export const TARGET = { col: 2, row: 5, pa: 5, pb: 9 };
export const TILE_TOP = CLUSTER.base + CLUSTER.tileH;

export function tileCenter(cx0, col, row) {
  return [cx0 + CLUSTER.px * (col + 0.5), CLUSTER.z0 + CLUSTER.pz * (row + 0.5)];
}
export function targetPE() {
  const [tx, tz] = tileCenter(CLUSTER.x0, TARGET.col, TARGET.row);
  const pw = CLUSTER.tw / PE_N, pd = CLUSTER.td / PE_N;
  return [tx - CLUSTER.tw / 2 + pw * (TARGET.pa + 0.5), tz - CLUSTER.td / 2 + pd * (TARGET.pb + 0.5)];
}
const [PEX, PEZ] = targetPE();
// Nano frame: origin 6.8 µm below the tile's top surface, right under the target PE.
export const NANO_TOP = 6800; // nm, top of the metal stack
export const NANO_ANCHOR = anchorFrom({ position: [PEX, TILE_TOP - NANO_TOP / 1000, PEZ], scale: 0.001 });

// Block list: [x0, z0, x1, z1, type, height]
// types: 1 io, 2 phy, 3 cpu core, 4 sram, 5 logic, 7 noc, 8 cluster base
function floorplan() {
  const B = [];
  const add = (x0, z0, x1, z1, type, h) => B.push([x0, z0, x1, z1, type, h]);
  for (const s of [-1, 1]) {
    for (let i = 0; i < 4; i++) {
      const x0 = -8300 + i * 4175, x1 = x0 + 4000;
      add(x0, s > 0 ? 7050 : -7550, x1, s > 0 ? 7550 : -7050, 2, 8);
    }
  }
  for (let i = 0; i < 4; i++) add(8050, -6600 + i * 3350, 8550, -6600 + i * 3350 + 3150, 2, 8);
  for (let i = 0; i < 2; i++) add(-8550, -6600 + i * 6700, -8050, -6600 + i * 6700 + 6000, 2, 8);
  const cx = [[-8400, -6450], [-6300, -4350], [-4200, -2300]];
  const cz = [[2500, 4550], [4750, 6850]];
  for (const [x0, x1] of cx) for (const [z0, z1] of cz) add(x0, z0, x1, z1, 3, 14);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 2; j++) add(-2100 + i * 1210, 2500 + j * 2200, -2100 + i * 1210 + 1140, 2500 + j * 2200 + 2150, 4, 10);
  add(2900, 2500, 5200, 6850, 5, 12);
  add(5400, 2500, 7850, 4550, 5, 12);
  add(5400, 4750, 7850, 6850, 5, 12);
  add(-450, -6850, 450, 2300, 7, 7);
  add(-7850, -6850, -600, 2300, 8, CLUSTER.base);
  add(600, -6850, 7850, 2300, 8, CLUSTER.base);
  return B;
}

const DIE_VERT = /* glsl */`
varying vec3 vW; varying vec3 vN; varying float vTile; varying vec2 vTileC; varying vec2 vTileG;
attribute float aTile; attribute vec2 aTileC; attribute vec2 aTileG;
void main() {
  vec4 w = modelMatrix * instanceMatrix * vec4(position, 1.0);
  vW = w.xyz;
  vN = normalize(mat3(modelMatrix) * mat3(instanceMatrix) * normal);
  vTile = aTile; vTileC = aTileC; vTileG = aTileG;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const DIE_FRAG = /* glsl */`
precision highp float;
uniform float uTime; uniform vec3 uCamPos; uniform vec3 uKey; uniform float uWave; uniform vec2 uAnchor;
uniform vec4 uBlocks[40]; uniform vec2 uBlockInfo[40]; uniform int uNB;
uniform vec4 uCluster; // x0 (A), x0 (B), z0, unused
uniform vec4 uTile; // px, pz, tw, td
uniform float uBake;
varying vec3 vW; varying vec3 vN; varying float vTile; varying vec2 vTileC; varying vec2 vTileG;

float h21(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vnoise(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h21(i), h21(i + vec2(1, 0)), f.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), f.x), f.y); }
// Anti-aliased stripe: 1 on the line, fades to duty when sub-pixel.
float stripe(float x, float period, float duty) {
  float fw = fwidth(x) / period;
  float f = fract(x / period);
  float e = max(fw, 0.0005);
  float s = smoothstep(0.5 - duty * 0.5 - e, 0.5 - duty * 0.5 + e, f) - smoothstep(0.5 + duty * 0.5 - e, 0.5 + duty * 0.5 + e, f);
  return mix(s, duty, smoothstep(0.25, 0.6, fw));
}
float grid(vec2 p, float period, float duty) { return max(stripe(p.x, period, duty), stripe(p.y, period, duty)); }
vec3 thinfilm(float k) { return 0.5 + 0.5 * cos(6.2831 * (vec3(0.0, 0.33, 0.67) + k)); }

void main() {
  vec2 p = vW.xz;
  vec3 N = normalize(vN);
  vec3 V = normalize(uCamPos - vW);
  bool top = N.y > 0.5;
  vec3 alb = vec3(0.045, 0.047, 0.055);
  float metal = 0.35;
  vec3 emit = vec3(0.0);
  float fwp = length(fwidth(p));

  // Which block?
  int type = 0;
  vec4 blk = vec4(0.0);
  float bseed = 0.0;
  for (int i = 0; i < 40; i++) {
    if (i >= uNB) break;
    vec4 b = uBlocks[i];
    if (p.x >= b.x && p.x <= b.z && p.y >= b.y && p.y <= b.w) { type = int(uBlockInfo[i].x); blk = b; bseed = float(i); }
  }
  if (vTile > 0.5) type = 9;
  vec2 lp = p - blk.xy;
  vec2 bs = blk.zw - blk.xy;

  if (!top) {
    alb = vec3(0.03, 0.03, 0.035);
  } else if (type == 0) {
    // filler + top-level routing channels
    float r1 = stripe(p.x, 12.0, 0.35) * 0.5 + stripe(p.y, 9.0, 0.3) * 0.3;
    alb = mix(vec3(0.03, 0.032, 0.04), vec3(0.14, 0.11, 0.08), r1 * 0.6);
    float edge = step(abs(p.x), 8940.0) * step(abs(p.y), 7940.0);
    float io = 1.0 - step(abs(p.x), 8600.0) * step(abs(p.y), 7600.0);
    if (io > 0.5) {
      vec2 c = fract(p / 150.0) - 0.5;
      float pad = 1.0 - smoothstep(0.26, 0.26 + fwidth(p.x) / 150.0 * 1.5, length(c));
      alb = mix(vec3(0.05, 0.05, 0.06), vec3(0.55, 0.42, 0.25), pad);
      metal = mix(0.3, 0.95, pad);
    }
    alb *= mix(0.3, 1.0, edge);
  } else if (type == 2) {
    // PHY: repeated slices
    float sl = stripe(lp.x + lp.y * 0.0, 60.0, 0.55);
    float tr = stripe(lp.y, 7.0, 0.4);
    alb = mix(vec3(0.07, 0.065, 0.06), vec3(0.3, 0.24, 0.16), sl * 0.6 + tr * 0.2);
    metal = 0.6;
  } else if (type == 3) {
    // CPU core: L2 macro + logic
    vec2 u = lp / bs;
    float l2 = step(0.58, u.x) * step(0.1, u.y) * step(u.y, 0.9) * step(u.x, 0.95);
    float logic = vnoise(p / 14.0) * 0.6 + vnoise(p / 5.0) * 0.4;
    float rows = stripe(p.y, 3.2, 0.5);
    vec3 lg = mix(vec3(0.05, 0.05, 0.065), vec3(0.16, 0.13, 0.1), logic * 0.7 + rows * 0.15);
    vec3 sr = mix(vec3(0.09, 0.08, 0.1), vec3(0.2, 0.2, 0.26), grid(p, 6.0, 0.35));
    alb = mix(lg, sr, l2);
    metal = mix(0.4, 0.7, l2);
  } else if (type == 4) {
    // SRAM macro: bitcell array with periphery spine
    vec2 u = lp / bs;
    float spine = step(abs(u.x - 0.5), 0.04) + step(abs(u.y - 0.5), 0.05);
    float cells = grid(p, 2.4, 0.3);
    alb = mix(vec3(0.1, 0.09, 0.12), vec3(0.24, 0.23, 0.3), cells * 0.8);
    alb = mix(alb, vec3(0.08, 0.07, 0.06), clamp(spine, 0.0, 1.0));
    metal = 0.75;
  } else if (type == 5) {
    // random logic "city": standard-cell rows, macros
    float n = vnoise(p / 40.0 + bseed) * 0.5 + vnoise(p / 9.0) * 0.5;
    float rows = stripe(p.y, 3.0, 0.5);
    float mac = step(0.72, vnoise(floor(p / 380.0) + bseed * 3.1));
    alb = mix(vec3(0.05, 0.05, 0.06), vec3(0.17, 0.14, 0.1), n * 0.7 + rows * 0.15);
    alb = mix(alb, vec3(0.16, 0.16, 0.22) * (0.7 + 0.3 * grid(p, 5.0, 0.3)), mac);
    metal = 0.45;
  } else if (type == 7) {
    float l = stripe(p.x, 5.0, 0.45);
    alb = mix(vec3(0.05, 0.05, 0.06), vec3(0.33, 0.25, 0.16), l * 0.8);
    metal = 0.8;
  } else if (type == 8) {
    // cluster floor between tiles: dense routing channels
    float l = stripe(p.x, 6.0, 0.4) * 0.6 + stripe(p.y, 6.0, 0.4) * 0.4;
    alb = mix(vec3(0.035, 0.035, 0.045), vec3(0.22, 0.17, 0.11), l * 0.6);
    metal = 0.7;
  } else if (type == 9) {
    // compute tile: 16x16 processing elements, each a MAC array + local SRAM
    vec2 tsize = uTile.zw;
    vec2 tl = p - (vTileC - 0.5 * tsize);
    vec2 pe = tsize / 16.0;
    vec2 pid = floor(tl / pe);
    vec2 pu = fract(tl / pe);
    float ch = 1.0 - (step(0.035, pu.x) * step(pu.x, 0.965) * step(0.035, pu.y) * step(pu.y, 0.965));
    float sram = step(0.72, pu.x);
    float mac = grid(tl, pe.x / 12.0, 0.25);
    vec3 macc = mix(vec3(0.07, 0.065, 0.08), vec3(0.2, 0.16, 0.12), mac * 0.7 + vnoise(tl / 2.0) * 0.3);
    vec3 src = mix(vec3(0.12, 0.12, 0.16), vec3(0.26, 0.26, 0.34), grid(tl, 1.6, 0.3));
    alb = mix(macc, src, sram);
    alb = mix(alb, vec3(0.03, 0.03, 0.035), ch);
    metal = 0.6;
    // top metal power grid, aligned with the nano world's M8 (pitch 4 um) and M7 (1.8 um)
    float m8 = stripe(p.x - uAnchor.x - 2.0, 4.0, 0.5);
    float m7 = stripe(p.y - uAnchor.y - 0.9, 1.8, 0.5);
    float mvis = smoothstep(4.0, 0.8, fwp);
    alb = mix(alb, mix(vec3(0.33, 0.21, 0.13), vec3(0.62, 0.4, 0.24), m8) , mvis * max(m8, m7 * 0.45));
    metal = mix(metal, 0.95, mvis * m8);
    // systolic activity: a diagonal wavefront sweeping the array
    vec2 g = vTileG * 16.0 + pid;
    float ph = (g.x + g.y) / 60.0 - uTime * 0.55;
    float w = exp(-pow(fract(ph) - 0.5, 2.0) * 90.0);
    float w2 = exp(-pow(fract(ph * 2.0 + 0.3) - 0.5, 2.0) * 160.0) * 0.4;
    float cell = (1.0 - ch) * (1.0 - sram) * (0.6 + 0.4 * h21(pid + vTileG * 17.0));
    emit += vec3(0.35, 0.75, 1.0) * (w + w2) * cell * 2.2 * uWave;
    // data lanes entering along rows
    float lane = step(abs(pu.y - 0.5), 0.03) * (1.0 - sram);
    float mv = step(0.8, fract(tl.x / 22.0 - uTime * 1.3 + pid.y * 0.37));
    emit += vec3(0.4, 0.8, 1.0) * lane * mv * 0.8 * uWave;
  }

  // Shading: key light + fake env + thin-film iridescence.
  vec3 L = normalize(uKey);
  vec3 H = normalize(L + V);
  float nl = max(dot(N, L), 0.0);
  float nh = max(dot(N, H), 0.0);
  float fres = pow(1.0 - max(dot(N, V), 0.0), 5.0);
  vec3 film = thinfilm(0.35 + 0.6 * dot(N, V) + 0.00004 * (p.x + p.y));
  vec3 spec = mix(vec3(0.04), alb * 3.0, metal) * (pow(nh, 60.0) * 3.0 + pow(nh, 8.0) * 0.25);
  vec3 col = alb * (0.12 + nl * 1.6) * (1.0 - metal * 0.5) + spec * nl;
  col += film * 0.035 * (0.4 + fres) * (top ? 1.0 : 0.3);
  col += vec3(0.25, 0.3, 0.38) * fres * 0.15;
  col += emit;
  gl_FragColor = vec4(col, 1.0);
}`;

export class DieWorld {
  constructor(envs) {
    this.name = 'die';
    this.frame = 'die';
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x000000);
    this.camera = new THREE.PerspectiveCamera(40, 16 / 9, 1, 1e6);
    this.envs = envs;
    this.nearMul = 0.01; this.farMul = 80; this.farMax = 3e5; this.nearMin = 0.2;
  }

  init() {
    const blocks = floorplan();
    this.blocks = blocks;
    const u = {
      uTime: { value: 0 }, uCamPos: { value: new THREE.Vector3() }, uKey: { value: new THREE.Vector3(-0.55, 0.45, 0.7).normalize() },
      uWave: { value: 1 }, uAnchor: { value: new THREE.Vector2(PEX, PEZ) },
      uBlocks: { value: blocks.map((b) => new THREE.Vector4(b[0], b[1], b[2], b[3])).concat(Array.from({ length: 40 - blocks.length }, () => new THREE.Vector4())) },
      uBlockInfo: { value: blocks.map((b) => new THREE.Vector2(b[4], b[5])).concat(Array.from({ length: 40 - blocks.length }, () => new THREE.Vector2())) },
      uNB: { value: blocks.length },
      uCluster: { value: new THREE.Vector4(-CLUSTER.x1, CLUSTER.x0, CLUSTER.z0, 0) },
      uTile: { value: new THREE.Vector4(CLUSTER.px, CLUSTER.pz, CLUSTER.tw, CLUSTER.td) },
      uBake: { value: 0 },
    };
    this.mat = new THREE.ShaderMaterial({ vertexShader: DIE_VERT, fragmentShader: DIE_FRAG, uniforms: u });
    // Die slab (the whole surface, 780 µm thick).
    const count = 1 + blocks.length + CLUSTER.cols * CLUSTER.rows * 2;
    const geo = new THREE.BoxGeometry(1, 1, 1);
    const aTile = new Float32Array(count), aTileC = new Float32Array(count * 2), aTileG = new Float32Array(count * 2);
    const mesh = new THREE.InstancedMesh(geo, this.mat, count);
    const m = new THREE.Matrix4();
    let i = 0;
    m.compose(new THREE.Vector3(0, -390, 0), new THREE.Quaternion(), new THREE.Vector3(DIE.hx * 2, 780, DIE.hz * 2));
    mesh.setMatrixAt(i++, m);
    for (const b of blocks) {
      const [x0, z0, x1, z1, , h] = b;
      m.compose(new THREE.Vector3((x0 + x1) / 2, h / 2, (z0 + z1) / 2), new THREE.Quaternion(), new THREE.Vector3(x1 - x0, h, z1 - z0));
      mesh.setMatrixAt(i++, m);
    }
    for (const side of [-1, 1]) {
      const cx0 = side < 0 ? -CLUSTER.x1 : CLUSTER.x0;
      for (let c = 0; c < CLUSTER.cols; c++) for (let r = 0; r < CLUSTER.rows; r++) {
        const [x, z] = tileCenter(cx0, c, r);
        m.compose(new THREE.Vector3(x, CLUSTER.base + CLUSTER.tileH / 2, z), new THREE.Quaternion(), new THREE.Vector3(CLUSTER.tw, CLUSTER.tileH, CLUSTER.td));
        aTile[i] = 1;
        aTileC[i * 2] = x; aTileC[i * 2 + 1] = z;
        // global grid index: the two clusters form one wide systolic array
        aTileG[i * 2] = side < 0 ? c : c + CLUSTER.cols + 1; aTileG[i * 2 + 1] = r;
        mesh.setMatrixAt(i++, m);
      }
    }
    geo.setAttribute('aTile', new THREE.InstancedBufferAttribute(aTile, 1));
    geo.setAttribute('aTileC', new THREE.InstancedBufferAttribute(aTileC, 2));
    geo.setAttribute('aTileG', new THREE.InstancedBufferAttribute(aTileG, 2));
    mesh.frustumCulled = false;
    this.scene.add(mesh);
    this.mesh = mesh;
  }

  // Orthographic top-down bake of the die face (used on the die in the board world).
  bake(renderer) {
    const W = 2048, H = Math.round(2048 * (DIE.hz / DIE.hx));
    const rt = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter, samples: 4 });
    const cam = new THREE.OrthographicCamera(-DIE.hx, DIE.hx, DIE.hz, -DIE.hz, 10, 10000);
    cam.position.set(0, 3000, 0);
    cam.up.set(0, 0, -1);
    cam.lookAt(0, 0, 0);
    this.mat.uniforms.uTime.value = 26;
    this.mat.uniforms.uCamPos.value.set(0, 30000, 0);
    this.mat.uniforms.uWave.value = 0.6;
    renderer.setRenderTarget(rt);
    renderer.clear();
    renderer.render(this.scene, cam);
    renderer.setRenderTarget(null);
    return rt.texture;
  }

  update(t, pose, ctx) {
    const u = this.mat.uniforms;
    u.uTime.value = t;
    u.uCamPos.value.copy(pose.p);
    u.uWave.value = ctx.fx.wave ?? 1;
  }
}
