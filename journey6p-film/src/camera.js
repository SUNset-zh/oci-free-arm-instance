import * as THREE from 'three';
import { hermite } from './lib/util.js';
import { Pose } from './frames.js';

// Keyframed camera rail. Keys: { t, p:[x,y,z], l:[x,y,z], up?, fov?, roll?, f?, ap?, near? }
// Position / target / lens values are interpolated with a C1 Hermite spline in
// time, so camera velocity is continuous through every key.
export class KeyCam {
  constructor(frame, keys, { endZero = true } = {}) {
    this.frame = frame;
    this.endZero = endZero;
    let prev = { up: [0, 1, 0], fov: 40, roll: 0, ap: 0, near: 0, f: null };
    this.keys = keys.map((k) => {
      const full = {
        t: k.t, p: k.p, l: k.l,
        up: k.up ?? prev.up, fov: k.fov ?? prev.fov, roll: k.roll ?? prev.roll,
        ap: k.ap ?? prev.ap, near: k.near ?? prev.near,
        f: k.f !== undefined ? k.f : null,
      };
      prev = full;
      return full;
    });
    this.t0 = this.keys[0].t;
    this.t1 = this.keys[this.keys.length - 1].t;
    this.ts = this.keys.map((k) => k.t);
    this.P = this.keys.map((k) => k.p);
    this.L = this.keys.map((k) => k.l);
    this.U = this.keys.map((k) => k.up);
    // Focus distance defaults to |p - l| when not given.
    this.S = this.keys.map((k) => {
      const d = Math.hypot(k.p[0] - k.l[0], k.p[1] - k.l[1], k.p[2] - k.l[2]);
      return [k.fov, k.roll, k.ap, Math.log(k.f ?? d), k.near];
    });
    this._a = [0, 0, 0];
    this._s = [0, 0, 0, 0, 0];
  }
  sample(t, pose = new Pose()) {
    const a = this._a;
    hermite(this.ts, this.P, t, 3, a, this.endZero); pose.p.set(a[0], a[1], a[2]);
    hermite(this.ts, this.L, t, 3, a, this.endZero); pose.l.set(a[0], a[1], a[2]);
    hermite(this.ts, this.U, t, 3, a, this.endZero); pose.up.set(a[0], a[1], a[2]).normalize();
    const s = hermite(this.ts, this.S, t, 5, this._s, this.endZero);
    pose.fov = s[0]; pose.roll = s[1]; pose.ap = Math.max(0, s[2]); pose.focus = Math.exp(s[3]);
    pose.near = Math.max(0, s[4]);
    pose.frame = this.frame;
    return pose;
  }
  // Key helper for chaining: sample this rail at t and return a key object in another frame.
  keyAt(t, frame, extra = {}) {
    const pose = this.sample(t).to(frame);
    return {
      t: extra.t ?? t,
      p: pose.p.toArray(), l: pose.l.toArray(), up: pose.up.toArray(),
      fov: pose.fov, roll: pose.roll, ap: pose.ap, f: pose.focus, near: pose.near,
      ...extra,
    };
  }
}

// Procedural camera: fn(t, pose) fills the pose.
export class FnCam {
  constructor(frame, t0, t1, fn) {
    this.frame = frame; this.t0 = t0; this.t1 = t1; this.fn = fn;
  }
  sample(t, pose = new Pose()) {
    pose.frame = this.frame;
    pose.near = 0;
    pose.roll = 0;
    pose.up.set(0, 1, 0);
    this.fn(t, pose);
    return pose;
  }
}

export class CameraRig {
  constructor(tracks) { this.tracks = tracks.slice().sort((a, b) => a.t0 - b.t0); }
  sample(t, pose) {
    let tr = this.tracks[0];
    for (const k of this.tracks) if (t >= k.t0) tr = k;
    return tr.sample(t, pose);
  }
}

export const V = (x, y, z) => new THREE.Vector3(x, y, z);
