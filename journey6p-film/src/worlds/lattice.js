import * as THREE from 'three';
import { clamp, smooth, rng } from '../lib/util.js';

// LATTICE WORLD — diamond-cubic silicon, in ångström.
// Oriented like a FinFET on a (001) wafer: the fin / channel runs along [110]
// (film +x), the fin top is the (001) surface (film +y, top layer at y = 0),
// and [1-10] is film z. The target atom sits at the origin on that surface.

export const A0 = 5.431; // lattice constant (Å)
export const REGION = { x0: -170, x1: 120, y0: -46, z: 33 };

const ATOM_VERT = /* glsl */`
attribute vec3 aPos; attribute float aSeed;
uniform float uR; uniform vec3 uHide;
varying vec2 vUv; varying vec3 vC; varying float vSeed; varying float vHide;
void main() {
  vUv = position.xy;
  vec4 c = viewMatrix * modelMatrix * vec4(aPos, 1.0);
  vC = c.xyz; vSeed = aSeed;
  vHide = step(length(aPos - uHide), 0.01);
  c.xy += position.xy * uR * 1.02;
  gl_Position = projectionMatrix * c;
}`;
const ATOM_FRAG = /* glsl */`
precision highp float;
uniform float uR; uniform mat4 projectionMatrix; uniform vec3 uKey; uniform float uHideAmt; uniform float uAlpha;
varying vec2 vUv; varying vec3 vC; varying float vSeed; varying float vHide;
void main() {
  float r2 = dot(vUv, vUv);
  if (r2 > 1.0) discard;
  if (vHide > 0.5 && uHideAmt > 0.999) discard;
  float z = sqrt(1.0 - r2);
  vec3 n = vec3(vUv, z);
  vec3 p = vC + n * uR;
  vec4 clip = projectionMatrix * vec4(p, 1.0);
  gl_FragDepth = clip.z / clip.w * 0.5 + 0.5;
  vec3 L = normalize(uKey);
  float diff = max(dot(n, L), 0.0);
  float rim = pow(1.0 - z, 2.5);
  float sp = pow(max(dot(n, normalize(L + vec3(0, 0, 1))), 0.0), 40.0);
  vec3 base = vec3(0.46, 0.52, 0.62);
  vec3 col = base * (0.08 + diff * 0.9) + vec3(0.55, 0.75, 1.0) * rim * 0.55 + vec3(1.0) * sp * 0.5;
  float fade = vHide > 0.5 ? 1.0 - uHideAmt : 1.0;
  gl_FragColor = vec4(col * fade * uAlpha, 1.0);
}`;

const BOND_VERT = /* glsl */`
attribute vec3 aA; attribute vec3 aB;
uniform float uW;
varying float vX; varying vec3 vMid;
void main() {
  vec3 a = (viewMatrix * modelMatrix * vec4(aA, 1.0)).xyz;
  vec3 b = (viewMatrix * modelMatrix * vec4(aB, 1.0)).xyz;
  vec3 d = b - a;
  vec3 side = normalize(cross(d, -normalize(mix(a, b, 0.5)))) * uW;
  vec3 p = mix(a, b, position.y + 0.5) + side * position.x * 2.0;
  vX = position.x * 2.0;
  vMid = mix(a, b, 0.5);
  gl_Position = projectionMatrix * vec4(p, 1.0);
}`;
const BOND_FRAG = /* glsl */`
precision highp float;
uniform float uAlpha;
varying float vX; varying vec3 vMid;
void main() {
  float s = sqrt(max(0.0, 1.0 - vX * vX));
  vec3 col = vec3(0.24, 0.3, 0.4) * (0.25 + 0.75 * s) + vec3(0.35, 0.55, 0.8) * pow(1.0 - s, 3.0) * 0.4;
  gl_FragColor = vec4(col * uAlpha, 1.0);
}`;

const CLOUD_VERT = /* glsl */`
attribute vec4 aP; // xyz, shell
uniform float uTime; uniform float uSize;
varying float vA; varying float vShell;
float h(float n) { return fract(sin(n) * 43758.5453); }
void main() {
  vec3 p = aP.xyz;
  // quantum shimmer: every point re-samples its radius along its own ray
  float id = float(gl_VertexID);
  float cyc = uTime * (1.5 + h(id) * 2.0) + h(id * 1.7) * 10.0;
  float k = fract(cyc);
  float jitter = 0.82 + 0.36 * h(floor(cyc) + id * 0.37);
  p *= jitter;
  vA = sin(k * 3.14159);
  vShell = aP.w;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = clamp(uSize / -mv.z, 1.0, 3.0);
}`;
const CLOUD_FRAG = /* glsl */`
precision highp float;
uniform float uAlpha;
varying float vA; varying float vShell;
void main() {
  vec2 d = gl_PointCoord - 0.5;
  if (dot(d, d) > 0.25) discard;
  vec3 c = mix(vec3(0.5, 0.8, 1.0), vec3(1.0, 0.95, 0.9), vShell);
  gl_FragColor = vec4(c * vA * uAlpha * 0.5, 1.0);
}`;

export class LatticeWorld {
  constructor(envs) {
    this.name = 'lat';
    this.frame = 'lat';
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x000000);
    this.camera = new THREE.PerspectiveCamera(40, 16 / 9, 0.1, 1e5);
    this.envs = envs;
    this.nearMul = 0.03; this.farMul = 120; this.farMax = 2e4; this.nearMin = 0.02;
  }

  init() {
    // Diamond cubic basis in cubic coordinates.
    const fcc = [[0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0]];
    const basis = [...fcc, ...fcc.map(([a, b, c]) => [a + 0.25, b + 0.25, c + 0.25])];
    const s2 = Math.SQRT1_2;
    // cubic (X,Y,Z) -> film (x,y,z): x=[110], y=[001], z=[1-10]
    const toFilm = (X, Y, Z) => [(X + Y) * s2 * A0, Z * A0, (X - Y) * s2 * A0];
    const atoms = [];
    const R = REGION;
    const n = Math.ceil(Math.max(Math.abs(R.x0), R.x1) / (A0 * s2)) + 3;
    const nz = Math.ceil(Math.abs(R.y0) / A0) + 2;
    for (let i = -n; i <= n; i++) for (let j = -n; j <= n; j++) for (let k = -nz; k <= 1; k++) {
      for (const [a, b, c] of basis) {
        const [x, y, z] = toFilm(i + a, j + b, k + c);
        if (x < R.x0 || x > R.x1 || y > 0.01 || y < R.y0 || Math.abs(z) > R.z) continue;
        atoms.push([x, y, z]);
      }
    }
    this.atoms = atoms;
    // Bonds: nearest neighbours at a0*sqrt(3)/4 = 2.352 Å.
    const bl = A0 * Math.sqrt(3) / 4;
    const key = (x, y, z) => `${Math.round(x * 100)},${Math.round(y * 100)},${Math.round(z * 100)}`;
    const map = new Map(atoms.map((p, i) => [key(...p), i]));
    // Neighbour offsets in film coords (for sublattice A; B uses the negatives).
    const offs = [[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]].map(([a, b, c]) => toFilm(a / 4, b / 4, c / 4));
    const bonds = [];
    atoms.forEach((p, i) => {
      for (const sgn of [1, -1]) for (const o of offs) {
        const q = [p[0] + sgn * o[0], p[1] + sgn * o[1], p[2] + sgn * o[2]];
        const j = map.get(key(...q));
        if (j !== undefined && j > i) bonds.push([i, j]);
      }
    });
    this.bonds = bonds;
    this.bondLen = bl;

    // Atoms: instanced impostor quads.
    const quad = new THREE.PlaneGeometry(2, 2);
    const ig = new THREE.InstancedBufferGeometry();
    ig.index = quad.index;
    ig.setAttribute('position', quad.attributes.position);
    const aPos = new Float32Array(atoms.length * 3), aSeed = new Float32Array(atoms.length);
    const r = rng(5);
    atoms.forEach((p, i) => { aPos.set(p, i * 3); aSeed[i] = r(); });
    ig.setAttribute('aPos', new THREE.InstancedBufferAttribute(aPos, 3));
    ig.setAttribute('aSeed', new THREE.InstancedBufferAttribute(aSeed, 1));
    ig.instanceCount = atoms.length;
    this.atomMat = new THREE.ShaderMaterial({
      vertexShader: ATOM_VERT, fragmentShader: ATOM_FRAG,
      uniforms: { uR: { value: 0.58 }, uKey: { value: new THREE.Vector3(-0.4, 0.7, 0.6).normalize() }, uHide: { value: new THREE.Vector3(0, 0, 0) }, uHideAmt: { value: 0 }, uAlpha: { value: 1 } },
    });
    this.atomMesh = new THREE.Mesh(ig, this.atomMat);
    this.atomMesh.frustumCulled = false;
    this.scene.add(this.atomMesh);

    // Bonds: camera-facing ribbons.
    const bq = new THREE.PlaneGeometry(1, 1);
    const bg = new THREE.InstancedBufferGeometry();
    bg.index = bq.index;
    bg.setAttribute('position', bq.attributes.position);
    const aA = new Float32Array(bonds.length * 3), aB = new Float32Array(bonds.length * 3);
    bonds.forEach(([i, j], k) => { aA.set(atoms[i], k * 3); aB.set(atoms[j], k * 3); });
    bg.setAttribute('aA', new THREE.InstancedBufferAttribute(aA, 3));
    bg.setAttribute('aB', new THREE.InstancedBufferAttribute(aB, 3));
    bg.instanceCount = bonds.length;
    this.bondMat = new THREE.ShaderMaterial({ vertexShader: BOND_VERT, fragmentShader: BOND_FRAG, uniforms: { uW: { value: 0.13 }, uAlpha: { value: 1 } } });
    this.bondMesh = new THREE.Mesh(bg, this.bondMat);
    this.bondMesh.frustumCulled = false;
    this.scene.add(this.bondMesh);

    // Electron cloud of the target atom: sp3 lobes toward its four neighbours + core.
    const dirs = [[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]].map(([a, b, c]) => new THREE.Vector3(...toFilm(a / 4, b / 4, c / 4)).normalize());
    const N = 26000;
    const cp = new Float32Array(N * 4);
    const g = new THREE.Vector3();
    const gauss = () => { let u = 0, v = 0; while (u === 0) u = r(); v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
    for (let i = 0; i < N; i++) {
      const pick = r();
      if (pick < 0.12) {
        // inner shells (1s 2s 2p): compact, bright
        g.set(gauss(), gauss(), gauss()).multiplyScalar(0.14);
        cp.set([g.x, g.y, g.z, 1], i * 4);
      } else {
        const d = dirs[Math.floor(r() * 4)];
        // radial profile peaking ~0.75 Å along the lobe, with a small back-lobe
        const back = r() < 0.12;
        const rad = Math.abs(0.75 + gauss() * 0.32) * (back ? 0.45 : 1);
        g.set(gauss(), gauss(), gauss()).multiplyScalar(0.3 + rad * 0.28);
        g.addScaledVector(d, back ? -rad : rad);
        cp.set([g.x, g.y, g.z, 0], i * 4);
      }
    }
    const cg = new THREE.BufferGeometry();
    cg.setAttribute('position', new THREE.BufferAttribute(new Float32Array(N * 3), 3));
    cg.setAttribute('aP', new THREE.BufferAttribute(cp, 4));
    this.cloudMat = new THREE.ShaderMaterial({
      vertexShader: CLOUD_VERT, fragmentShader: CLOUD_FRAG, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uSize: { value: 8 }, uAlpha: { value: 0 } },
    });
    this.cloud = new THREE.Points(cg, this.cloudMat);
    this.cloud.frustumCulled = false;
    this.scene.add(this.cloud);
    // Nucleus.
    this.nucleus = new THREE.Mesh(new THREE.SphereGeometry(0.035, 12, 8), new THREE.MeshBasicMaterial({ color: new THREE.Color(1.0, 0.92, 0.8).multiplyScalar(30) }));
    this.scene.add(this.nucleus);

    // Travelling electrons (continuing the flow from the nano world).
    this.eN = 60;
    const eg = new THREE.PlaneGeometry(1, 1);
    this.eMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uAlpha: { value: 1 }, uSize: { value: 0.5 } },
      vertexShader: `uniform float uSize; varying vec2 vUv; void main(){ vUv = uv; vec4 c = viewMatrix * modelMatrix * instanceMatrix * vec4(0,0,0,1); c.xy += position.xy * uSize; gl_Position = projectionMatrix * c; }`,
      fragmentShader: `uniform float uAlpha; varying vec2 vUv; void main(){ float d = length(vUv-0.5)*2.0; float a = exp(-d*d*6.0)*0.6 + exp(-d*16.0)*1.5; gl_FragColor = vec4(vec3(0.45,0.8,1.0)*a*uAlpha,1.0);} `,
    });
    this.electrons = new THREE.InstancedMesh(eg, this.eMat, this.eN);
    this.electrons.frustumCulled = false;
    this.eSeeds = Array.from({ length: this.eN }, () => [r(), r(), r(), r()]);
    this.scene.add(this.electrons);

    this.findChannels();
  }

  // Locate open channels numerically so the camera never clips an atom.
  findChannels() {
    const atoms = this.atoms;
    // [110] channel (runs along x): best (y,z) near y=-8, z=0.
    const proj = atoms.filter((p) => p[0] > -20 && p[0] < 20).map((p) => [p[1], p[2]]);
    let best = null;
    for (let y = -14; y <= -4; y += 0.05) for (let z = -3; z <= 3; z += 0.05) {
      let md = 1e9;
      for (const [py, pz] of proj) { const d = (py - y) ** 2 + (pz - z) ** 2; if (d < md) md = d; }
      if (!best || md > best.d) best = { y, z, d: md };
    }
    this.channel = { y: best.y, z: best.z, clear: Math.sqrt(best.d) };
  }

  // Minimum clearance from a point to any atom centre (Å).
  clearance(p) {
    let md = 1e9;
    for (const a of this.atoms) {
      const d = (a[0] - p.x) ** 2 + (a[1] - p.y) ** 2 + (a[2] - p.z) ** 2;
      if (d < md) md = d;
    }
    return Math.sqrt(md);
  }

  update(t, pose, ctx) {
    const cu = this.cloudMat.uniforms;
    const ca = ctx.fx.atomCloud ?? 0;
    cu.uTime.value = t;
    cu.uAlpha.value = ca;
    cu.uSize.value = ctx.pixelHeight / 1080 * 6;
    this.cloud.visible = ca > 0.001;
    this.nucleus.visible = ca > 0.05;
    this.nucleus.material.color.setRGB(1.0, 0.92, 0.8).multiplyScalar(30 * ca);
    this.atomMat.uniforms.uHideAmt.value = ca;
    this.atomMat.uniforms.uAlpha.value = ctx.fx.latAlpha ?? 1;
    this.bondMat.uniforms.uAlpha.value = ctx.fx.latAlpha ?? 1;
    // Electrons drift along +x through the channels.
    const ev = ctx.fx.latElectrons ?? 0;
    this.electrons.visible = ev > 0.001;
    this.eMat.uniforms.uAlpha.value = ev;
    if (ev > 0.001) {
      const m = new THREE.Matrix4();
      const ch = this.channel;
      for (let k = 0; k < this.eN; k++) {
        const [a, b, c, d] = this.eSeeds[k];
        const L = 260;
        const x = -170 + ((a * L + t * (26 + 30 * b)) % L);
        // mostly in our channel's row, some in parallel channels
        const row = Math.floor(c * 5) - 2;
        const y = ch.y + (d < 0.5 ? 0 : row * A0 * 0.5) + 0.2 * Math.sin(t * 3 + k);
        const z = ch.z + row * A0 * Math.SQRT1_2 + 0.2 * Math.cos(t * 2.3 + k);
        m.makeTranslation(x, Math.min(y, -1), z);
        this.electrons.setMatrixAt(k, m);
      }
      this.electrons.instanceMatrix.needsUpdate = true;
    }
  }
}
