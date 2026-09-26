import * as THREE from 'three';

// The film lives in a chain of nested coordinate frames, each authored in
// comfortable units. A child frame is anchored inside its parent with a
// (uniformly scaled) matrix, so any camera pose can be carried losslessly
// from one scale world into the next. This is what makes the scale jumps
// seamless: at every hand-off both worlds are rendered from the *same* pose.
//
//   road  (metres, car-centric world; the environment scrolls past)
//    └ car   (metres, the hero car's body frame)
//       └ board (millimetres, the driving computer: housing + PCB + SoC)
//          └ die   (micrometres, the silicon die's active face)
//             └ nano  (nanometres, metal stack + transistors)
//                └ lat   (ångström, silicon crystal)

export const ORDER = ['road', 'car', 'board', 'die', 'nano', 'lat'];
export const UNIT = { road: 1, car: 1, board: 1e-3, die: 1e-6, nano: 1e-9, lat: 1e-10 };

const anchors = {}; // child -> parent matrices
const inverses = {};
for (const f of ORDER.slice(1)) { anchors[f] = new THREE.Matrix4(); inverses[f] = new THREE.Matrix4(); }

export function setAnchor(frame, matrix) {
  anchors[frame].copy(matrix);
  inverses[frame].copy(matrix).invert();
}

export function anchorFrom({ position = [0, 0, 0], rotation = [0, 0, 0], scale = 1 }) {
  const m = new THREE.Matrix4();
  m.compose(
    new THREE.Vector3(...position),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(...rotation, 'YXZ')),
    new THREE.Vector3(scale, scale, scale),
  );
  return m;
}

export function getAnchor(frame) { return anchors[frame]; }

function walk(v, from, to, isDir) {
  let i = ORDER.indexOf(from);
  const j = ORDER.indexOf(to);
  while (i > j) { // going up (child -> parent)
    const f = ORDER[i];
    if (isDir) v.transformDirection(anchors[f]); else v.applyMatrix4(anchors[f]);
    i--;
  }
  while (i < j) { // going down (parent -> child)
    const f = ORDER[i + 1];
    if (isDir) v.transformDirection(inverses[f]); else v.applyMatrix4(inverses[f]);
    i++;
  }
  return v;
}

export const convertPoint = (v, from, to) => (from === to ? v : walk(v, from, to, false));
export const convertDir = (v, from, to) => (from === to ? v : walk(v, from, to, true));
export const scaleRatio = (from, to) => UNIT[from] / UNIT[to];

// A camera pose: position, look target, up vector and lens parameters.
export class Pose {
  constructor() {
    this.p = new THREE.Vector3();
    this.l = new THREE.Vector3(0, 0, -1);
    this.up = new THREE.Vector3(0, 1, 0);
    this.fov = 40;
    this.roll = 0;
    this.focus = 1; // focus distance (frame units)
    this.ap = 0; // aperture: circle-of-confusion scale
    this.near = 0; // 0 = automatic
    this.frame = 'road';
  }
  copy(o) {
    this.p.copy(o.p); this.l.copy(o.l); this.up.copy(o.up);
    this.fov = o.fov; this.roll = o.roll; this.focus = o.focus; this.ap = o.ap;
    this.near = o.near; this.frame = o.frame;
    return this;
  }
  to(frame, out = new Pose()) {
    out.copy(this);
    if (frame === this.frame) return out;
    convertPoint(out.p, this.frame, frame);
    convertPoint(out.l, this.frame, frame);
    convertDir(out.up, this.frame, frame);
    const s = scaleRatio(this.frame, frame);
    out.focus *= s;
    out.near *= s;
    out.frame = frame;
    return out;
  }
  // Metres covered by the full frame width at the focus distance.
  widthMetres(aspect) {
    return 2 * this.focus * Math.tan((this.fov * Math.PI) / 360) * aspect * UNIT[this.frame];
  }
  apply(camera, nearMul = 0.01, farMul = 2000, farMax = Infinity, nearMin = 0) {
    camera.position.copy(this.p);
    camera.up.copy(this.up);
    camera.lookAt(this.l);
    if (this.roll) camera.rotateZ(this.roll);
    camera.fov = this.fov;
    const near = this.near > 0 ? this.near : Math.max(nearMin, this.focus * nearMul);
    camera.near = near;
    camera.far = Math.min(farMax, Math.max(near * 50, this.focus * farMul));
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
  }
}
