// Small deterministic math toolkit shared by every world.
// Everything in the film is a pure function of time, so no state lives here.

export const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, t) => a + (b - a) * t;
export const invLerp = (a, b, x) => clamp((x - a) / (b - a));
export const remap = (x, a, b, c, d) => lerp(c, d, invLerp(a, b, x));
export const smooth = (t) => { t = clamp(t); return t * t * (3 - 2 * t); };
export const smoother = (t) => { t = clamp(t); return t * t * t * (t * (t * 6 - 15) + 10); };
export const sstep = (a, b, x) => smooth((x - a) / (b - a));
export const fract = (x) => x - Math.floor(x);
export const TAU = Math.PI * 2;

export const ease = {
  linear: (t) => clamp(t),
  in2: (t) => clamp(t) ** 2,
  out2: (t) => 1 - (1 - clamp(t)) ** 2,
  in3: (t) => clamp(t) ** 3,
  out3: (t) => 1 - (1 - clamp(t)) ** 3,
  inOut2: (t) => { t = clamp(t); return t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2; },
  inOut3: (t) => { t = clamp(t); return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2; },
  inOut4: (t) => { t = clamp(t); return t < 0.5 ? 8 * t ** 4 : 1 - (-2 * t + 2) ** 4 / 2; },
  inOut5: (t) => { t = clamp(t); return t < 0.5 ? 16 * t ** 5 : 1 - (-2 * t + 2) ** 5 / 2; },
  outExpo: (t) => { t = clamp(t); return t === 1 ? 1 : 1 - 2 ** (-10 * t); },
  inExpo: (t) => { t = clamp(t); return t === 0 ? 0 : 2 ** (10 * t - 10); },
  inOutExpo: (t) => {
    t = clamp(t);
    if (t === 0 || t === 1) return t;
    return t < 0.5 ? 2 ** (20 * t - 10) / 2 : (2 - 2 ** (-20 * t + 10)) / 2;
  },
  outBack: (t) => { t = clamp(t); const c = 1.4; return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2; },
  smooth,
  smoother,
};

// Window: rises over [a, a+fi], holds, falls over [b-fo, b].
export function win(t, a, b, fi = 0.3, fo = 0.3) {
  if (t <= a || t >= b) return 0;
  return Math.min(fi > 0 ? smooth((t - a) / fi) : 1, fo > 0 ? smooth((b - t) / fo) : 1);
}

// Deterministic PRNG (mulberry32).
export function rng(seed = 1) {
  let a = seed >>> 0;
  const f = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  f.range = (a, b) => a + (b - a) * f();
  f.int = (a, b) => Math.floor(a + (b - a + 1) * f());
  f.pick = (arr) => arr[Math.floor(f() * arr.length)];
  f.sign = () => (f() < 0.5 ? -1 : 1);
  return f;
}

export const hash1 = (n) => fract(Math.sin(n * 127.1 + 311.7) * 43758.5453123);

// Scalar keyframe track: [[t, v], [t, v, easeName], ...]. The ease on a key
// applies to the segment that ends at that key.
export function keys(t, list) {
  if (t <= list[0][0]) return list[0][1];
  for (let i = 1; i < list.length; i++) {
    const [t1, v1, e] = list[i];
    if (t <= t1) {
      const [t0, v0] = list[i - 1];
      const f = (ease[e || 'inOut2'])((t - t0) / (t1 - t0 || 1));
      return v0 + (v1 - v0) * f;
    }
  }
  return list[list.length - 1][1];
}

// Log-space interpolation (for scale dives).
export const expLerp = (a, b, t) => a * Math.pow(b / a, t);

// Hermite spline sampling over non-uniform keys (C1, Catmull-Rom tangents in time).
export function hermite(ts, vs, t, dim, out, endZero = true) {
  const n = ts.length;
  if (n === 1 || t <= ts[0]) { for (let d = 0; d < dim; d++) out[d] = vs[0][d]; return out; }
  if (t >= ts[n - 1]) { for (let d = 0; d < dim; d++) out[d] = vs[n - 1][d]; return out; }
  let i = 0;
  while (i < n - 2 && t > ts[i + 1]) i++;
  const t0 = ts[i], t1 = ts[i + 1], h = t1 - t0;
  const u = (t - t0) / h;
  const u2 = u * u, u3 = u2 * u;
  const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u, h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
  for (let d = 0; d < dim; d++) {
    const p0 = vs[i][d], p1 = vs[i + 1][d];
    let m0, m1;
    if (i === 0) m0 = endZero ? 0 : (p1 - p0) / h;
    else m0 = (p1 - vs[i - 1][d]) / (t1 - ts[i - 1]);
    if (i + 1 === n - 1) m1 = endZero ? 0 : (p1 - p0) / h;
    else m1 = (vs[i + 2][d] - p0) / (ts[i + 2] - t0);
    out[d] = h00 * p0 + h10 * h * m0 + h01 * p1 + h11 * h * m1;
  }
  return out;
}

// Format a length in metres for the scale readout.
export function formatLength(m) {
  const units = [
    [1, 'm'], [1e-2, 'cm'], [1e-3, 'mm'], [1e-6, 'µm'], [1e-9, 'nm'], [1e-12, 'pm'],
  ];
  if (m >= 1) return `${m >= 10 ? m.toFixed(0) : m.toFixed(1)} m`;
  for (let i = 1; i < units.length; i++) {
    const [u, name] = units[i];
    const v = m / u;
    if (v >= 1 || i === units.length - 1) {
      if (name === 'nm' && v < 1) return `${(m / 1e-12).toFixed(0)} pm`;
      return `${v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(0) : v.toFixed(1)} ${name}`;
    }
  }
  return `${m} m`;
}
