import * as THREE from 'three';
import { clamp, smooth, lerp } from '../lib/util.js';

// Procedural modern EV sedan built from lofted cross-sections.
// Car frame: +Z forward, +Y up, +X = car's left. Units: metres.

export const CAR = {
  L: 2.42, // half length
  W: 0.95, // half width
  wheelR: 0.355,
  wheelZ: [1.47, -1.43],
  track: 0.83, // wheel centre |x|
  glassFront: 0.98, // windshield base station
  glassRear: -2.0,
};

const sgnpow = (v, p) => Math.sign(v) * Math.pow(Math.abs(v), p);

// Centripetal Catmull-Rom through 2D points, resampled evenly by arc length.
function sampleSpline(pts, n) {
  const P = pts.map(([x, y]) => new THREE.Vector2(x, y));
  const dense = [];
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[Math.max(0, i - 1)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(P.length - 1, i + 2)];
    for (let k = 0; k < 24; k++) {
      const t = k / 24, t2 = t * t, t3 = t2 * t;
      const f = (a, b, c, d) => 0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
      dense.push([f(p0.x, p1.x, p2.x, p3.x), f(p0.y, p1.y, p2.y, p3.y)]);
    }
  }
  dense.push([P[P.length - 1].x, P[P.length - 1].y]);
  const acc = [0];
  for (let i = 1; i < dense.length; i++) acc.push(acc[i - 1] + Math.hypot(dense[i][0] - dense[i - 1][0], dense[i][1] - dense[i - 1][1]));
  const L = acc[acc.length - 1] || 1;
  const out = [];
  let j = 0;
  for (let k = 0; k < n; k++) {
    const target = (k / (n - 1)) * L;
    while (j < acc.length - 2 && acc[j + 1] < target) j++;
    const u = (target - acc[j]) / Math.max(1e-9, acc[j + 1] - acc[j]);
    out.push([lerp(dense[j][0], dense[j + 1][0], clamp(u)), lerp(dense[j][1], dense[j + 1][1], clamp(u))]);
  }
  return out;
}

// Piecewise-linear then smoothed profile helper.
function profile(pts) {
  return (z) => {
    if (z >= pts[0][0]) return pts[0][1];
    for (let i = 1; i < pts.length; i++) {
      if (z >= pts[i][0]) {
        const [z0, y0] = pts[i - 1], [z1, y1] = pts[i];
        const u = (z - z0) / (z1 - z0);
        return lerp(y0, y1, u * u * (3 - 2 * u));
      }
    }
    return pts[pts.length - 1][1];
  };
}

// Top (roof / hood / deck) line, front (+z) to rear.
const topLine = profile([
  [2.42, 0.6], [2.3, 0.71], [2.05, 0.79], [1.5, 0.87], [CAR.glassFront, 0.93],
  [0.4, 1.3], [0.05, 1.415], [-0.55, 1.445], [-1.1, 1.4], [-1.6, 1.24],
  [CAR.glassRear, 1.03], [-2.25, 0.99], [-2.42, 0.9],
]);

const beltLine = (z) => 0.93 + 0.045 * clamp((-z + 1) / 3.4);

function bottomLine(z) {
  let y = 0.2;
  if (z > 1.95) y += (z - 1.95) ** 2 * 0.75;
  if (z < -2.0) y += (-2.0 - z) ** 2 * 1.2;
  for (const wz of CAR.wheelZ) {
    const R = 0.425, dz = z - wz;
    if (Math.abs(dz) < R) y = Math.max(y, 0.345 + Math.sqrt(R * R - dz * dz));
  }
  return y;
}

function halfWidth(z) {
  const u = Math.abs(z) / CAR.L;
  const e = z > 0 ? 3.4 : 4.6;
  let w = CAR.W * Math.pow(Math.max(0, 1 - Math.pow(u, e)), 1 / e);
  // Slight waist between the wheels, fuller haunches.
  w *= 1 - 0.012 * Math.exp(-((z - 0.0) ** 2) / 0.6);
  return w;
}

// Build a closed lofted body. Returns geometries split into body / greenhouse / hood.
export function buildCarBody() {
  // Stations: dense at the ends, with exact stations at glass boundaries.
  const zs = [];
  const NS = 120;
  for (let i = 0; i <= NS; i++) {
    const u = -1 + (2 * i) / NS;
    zs.push(CAR.L * Math.sin((Math.PI / 2) * u));
  }
  zs.push(CAR.glassFront, CAR.glassRear, 1.0 + 0.02, 2.2);
  for (const wz of CAR.wheelZ) for (const d of [-0.425, -0.42, 0.42, 0.425]) zs.push(wz + d);
  zs.sort((a, b) => a - b);
  const Z = zs.filter((z, i) => i === 0 || z - zs[i - 1] > 0.004);
  Z[0] = -CAR.L; Z[Z.length - 1] = CAR.L;

  const NL = 24; // lower-part points (bottom centre -> shoulder), per side
  const NU = 22; // upper-part points (ledge -> top centre), per side
  const perSide = NL + 1 + NU; // lower + shoulder + upper
  const ring = perSide * 2; // both sides, top/bottom centres duplicated per side

  const pos = [];
  const info = []; // per vertex: part (0 lower, 1 ledge, 2 upper), gh factor
  const contourFront = [], contourRear = [];

  for (const z of Z) {
    const w = Math.max(halfWidth(z), 0.0008);
    const yb = bottomLine(z);
    const yt = Math.max(topLine(z), yb + 0.02);
    const ys0 = beltLine(z);
    const ys = Math.min(ys0, yt - 0.03);
    const gh = smooth((yt - ys - 0.07) / 0.2); // greenhouse factor
    const sectionSide = (side) => {
      // Designed control points (right half, x >= 0), bottom centre -> shoulder.
      const h = ys - yb;
      const lower = [
        [0, yb], [0.55 * w, yb], [0.86 * w, yb + 0.004], [0.955 * w, yb + 0.05],
        [0.985 * w, yb + 0.3 * h], [1.0 * w, yb + 0.7 * h], [0.975 * w, ys],
      ];
      const lowerPts = sampleSpline(lower, NL + 1); // includes shoulder as last point
      const pts = lowerPts.map(([x, y], i) => [x * side, y, 0, gh]);
      // Upper: ledge -> tumblehome greenhouse -> flat-ish roof centre.
      const ki = lerp(0.975, 0.905, gh);
      const ledge = lerp(0.0, 0.014, gh);
      const H2 = yt - ys - ledge;
      const upper = [
        [w * ki, ys + ledge],
        [w * lerp(ki - 0.01, 0.86, gh), ys + ledge + H2 * 0.35],
        [w * lerp(ki - 0.04, 0.76, gh), ys + ledge + H2 * 0.8],
        [w * lerp(ki - 0.12, 0.62, gh), yt - 0.012 * gh],
        [w * lerp(0.5, 0.35, gh), yt],
        [0, yt],
      ];
      const upperPts = sampleSpline(upper, NU);
      upperPts.forEach(([x, y], i) => pts.push([x * side, y, i === 0 ? 1 : 2, gh]));
      return pts;
    };
    const right = sectionSide(-1); // car's right is -X
    const left = sectionSide(1);
    // Ring order: right side bottom->top, then left side top->bottom.
    const ringPts = [...right, ...left.reverse()];
    for (const p of ringPts) { pos.push(p[0], p[1], z); info.push(p[2], p[3]); }

    // Contours for light bars.
    const findAt = (yq) => {
      for (let i = 0; i < NL; i++) {
        const a = right[i], b = right[i + 1];
        if ((a[1] - yq) * (b[1] - yq) <= 0 && a[1] !== b[1]) {
          const u = (yq - a[1]) / (b[1] - a[1]);
          return Math.abs(lerp(a[0], b[0], u));
        }
      }
      return null;
    };
    if (z > 1.7) { const x = findAt(0.715); if (x != null) contourFront.push([x, z]); }
    if (z < -1.9) { const x = findAt(0.9); if (x != null) contourRear.push([x, z]); }
  }

  // Index quads, partitioned into three groups.
  const idx = { body: [], glass: [], hood: [] };
  const NZ = Z.length;
  for (let s = 0; s < NZ - 1; s++) {
    for (let k = 0; k < ring; k++) {
      const k2 = (k + 1) % ring;
      const a = s * ring + k, b = s * ring + k2, c = (s + 1) * ring + k, d = (s + 1) * ring + k2;
      const zc = (Z[s] + Z[s + 1]) / 2;
      const partA = info[a * 2], partB = info[b * 2];
      const upper = partA >= 1 && partB >= 1 && !(k === perSide - 1 && k2 === perSide);
      const topSeam = (k === perSide - 1) || (k === ring - 1);
      const isUpper = upper || (topSeam && partA === 2);
      const gh = Math.min(info[a * 2 + 1], info[(s + 1) * ring * 2 + k * 2 + 1]);
      let g = 'body';
      if (isUpper && zc < CAR.glassFront && zc > CAR.glassRear && gh > 0.35) g = 'glass';
      else if (isUpper && zc > CAR.glassFront + 0.02 && zc < 2.2) g = 'hood';
      idx[g].push(a, c, b, b, c, d);
    }
  }
  const P = new Float32Array(pos);
  const make = (list) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(P, 3));
    g.setIndex(list);
    g.computeVertexNormals();
    return g;
  };
  // Normals computed on the full surface for smooth seams, then shared.
  const full = make([...idx.body, ...idx.glass, ...idx.hood]);
  const nrm = full.getAttribute('normal');
  const split = (list) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(P, 3));
    g.setAttribute('normal', nrm);
    g.setIndex(list);
    return g;
  };
  return {
    body: split(idx.body), glass: split(idx.glass), hood: split(idx.hood),
    contourFront, contourRear,
  };
}

// Thin emissive strip following a plan-view contour at height y.
export function lightBar(contour, y, h, outward = 0.006, front = true) {
  const pts = [];
  const sorted = contour.slice().sort((a, b) => (front ? a[1] - b[1] : b[1] - a[1]));
  // right side (x<0) from back to tip, then left side tip to back
  const right = sorted.map(([x, z]) => [-x - outward * 0.3, z]);
  const left = sorted.slice().reverse().map(([x, z]) => [x + outward * 0.3, z]);
  const tipZ = front ? Math.max(...contour.map((c) => c[1])) : Math.min(...contour.map((c) => c[1]));
  for (const p of right) pts.push(p);
  pts.push([0, tipZ + (front ? outward : -outward)]);
  for (const p of left) pts.push(p);
  const pos = [], uv = [];
  let len = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x, z] = pts[i];
    if (i > 0) len += Math.hypot(x - pts[i - 1][0], z - pts[i - 1][1]);
    const zz = z + (front ? outward : -outward);
    pos.push(x, y - h / 2, zz, x, y + h / 2, zz);
    uv.push(len, 0, len, 1);
  }
  const index = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = i * 2;
    index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(index);
  g.userData.length = len;
  return g;
}

export function buildWheel(materials) {
  const g = new THREE.Group();
  const R = CAR.wheelR;
  // Tire: lathe of a rounded profile around X.
  const prof = [];
  const tw = 0.125, rr = 0.235;
  for (let i = 0; i <= 16; i++) {
    const a = -Math.PI / 2 + (i / 16) * Math.PI;
    prof.push(new THREE.Vector2(R - 0.03 + Math.cos(a) * 0.03, Math.sin(a) * tw));
  }
  prof.unshift(new THREE.Vector2(rr, -tw * 0.85));
  prof.push(new THREE.Vector2(rr, tw * 0.85));
  const tire = new THREE.Mesh(new THREE.LatheGeometry(prof, 48), materials.tire);
  tire.rotation.z = Math.PI / 2;
  g.add(tire);
  // Rim face: dark disc + spokes.
  const rim = new THREE.Mesh(new THREE.CylinderGeometry(rr, rr, 0.18, 40, 1, true), materials.rimInner);
  rim.rotation.z = Math.PI / 2;
  g.add(rim);
  const face = new THREE.Group();
  const disc = new THREE.Mesh(new THREE.CircleGeometry(rr * 0.98, 40), materials.rimDark);
  disc.position.x = 0.07;
  disc.rotation.y = Math.PI / 2;
  face.add(disc);
  const spokeGeo = new THREE.BoxGeometry(0.018, rr * 0.82, 0.05);
  for (let i = 0; i < 5; i++) {
    for (const off of [-0.09, 0.09]) {
      const s = new THREE.Mesh(spokeGeo, materials.rim);
      const a = (i / 5) * Math.PI * 2 + off;
      s.position.set(0.085, Math.cos(a) * rr * 0.5, Math.sin(a) * rr * 0.5);
      s.rotation.x = a;
      face.add(s);
    }
  }
  const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.05, 0.03, 20), materials.rim);
  hub.rotation.z = Math.PI / 2;
  hub.position.x = 0.09;
  face.add(hub);
  const ringM = new THREE.Mesh(new THREE.TorusGeometry(rr * 0.985, 0.008, 6, 48), materials.rim);
  ringM.rotation.y = Math.PI / 2;
  ringM.position.x = 0.085;
  face.add(ringM);
  g.add(face);
  g.userData.face = face;
  return g;
}

// Paint material with darkened back faces (so an opened body reads as a shell).
export function paintMaterial(color, env, opts = {}) {
  const m = new THREE.MeshPhysicalMaterial({
    color, metalness: opts.metalness ?? 0.55, roughness: opts.roughness ?? 0.32,
    clearcoat: 1, clearcoatRoughness: 0.06, envMap: env, envMapIntensity: opts.envI ?? 1.1,
    side: THREE.DoubleSide,
  });
  m.onBeforeCompile = (s) => {
    s.fragmentShader = s.fragmentShader.replace(
      '#include <opaque_fragment>',
      'if (!gl_FrontFacing) outgoingLight *= 0.12;\n#include <opaque_fragment>',
    );
  };
  return m;
}
