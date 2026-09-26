import * as THREE from 'three';
import { clamp, smooth, smoother, rng, win, lerp, keys } from '../lib/util.js';
import { RoundedBoxGeometry } from '../lib/rounded.js';
import { buildCarBody, buildWheel, lightBar, paintMaterial, CAR } from './car.js';
import { buildHousing, housingMaterials, HOUSING } from './housing.js';
import { anchorFrom } from '../frames.js';

// ROAD WORLD — a wet night expressway, in metres, centred on the hero car.
// The environment scrolls past the car (so precision stays perfect near it).

export const SPEED = 16.5; // m/s
export const LANE = 3.6;
export const T_SCAN = 0.4; // first lidar pulse
export const LANE_CHANGE = [59.4, 61.8];
export const REASSEMBLE = 57.2; // car body closes again during the zoom-out

// Where the driving computer sits inside the car (car frame).
export const BOARD_ANCHOR = anchorFrom({ position: [0, 0.405, 0.2], rotation: [0, -Math.PI / 2, 0], scale: 0.001 });

export const travel = (t) => SPEED * t;
export function laneX(t) { return LANE * smoother((t - LANE_CHANGE[0]) / (LANE_CHANGE[1] - LANE_CHANGE[0])); }

// Traffic, in the car-centric frame: x lane, z(t) relative position.
const TRAFFIC = [
  { x: -LANE, z0: 30, dv: -1.2, paint: 0x2a2c30 }, // right lane ahead (lidar target)
  { x: LANE, z0: -16, dv: 1.1, paint: 0xb9bcc2 },
  { x: 0, z0: 26 + 6.2 * 59.4, dv: -6.2, paint: 0x5a1e22 }, // the slower car we overtake at the end
  { x: -LANE, z0: 150, dv: -3, paint: 0x1d2a3a },
  { x: LANE, z0: 260, dv: -4, paint: 0x3a3a3a },
];
const ONCOMING = [0, 90, 170, 260, 330, 430, 520].map((z0, i) => ({ x: 10.2 + (i % 2) * 3.6, z0, dv: -2 * SPEED - 3 }));
const PED = { x: -8.6, z0: 34 };

const wrap = (v, lo, period) => ((((v - lo) % period) + period) % period) + lo;

const ROAD_VERT = /* glsl */`
uniform mat4 uTexMat;
varying vec3 vW; varying vec4 vRefl;
void main() {
  vec4 w = modelMatrix * vec4(position, 1.0);
  vW = w.xyz; vRefl = uTexMat * w;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const NOISE = /* glsl */`
float h21(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vnoise(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h21(i), h21(i + vec2(1, 0)), f.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), f.x), f.y); }
float fbm(vec2 p) { float s = 0.0, a = 0.5; for (int i = 0; i < 4; i++) { s += a * vnoise(p); p *= 2.07; a *= 0.5; } return s; }
`;

const ROAD_FRAG = /* glsl */`
precision highp float;
uniform float uTravel; uniform sampler2D tRefl; uniform float uReflOn;
uniform vec3 uCamPos; uniform vec3 uFog; uniform float uFogD;
uniform float uLampI; uniform vec3 uLampCol;
uniform vec4 uCars[10]; // x, z, yaw, kind(0 ours, 1 traffic same dir, 2 oncoming)
uniform float uHead; uniform float uAmb; uniform float uTime; uniform vec2 uReflTexel;
varying vec3 vW; varying vec4 vRefl;
${NOISE}
float lampRow(vec2 p, float lx, float spacing, float phase, float h) {
  float zz = p.y + uTravel - phase;
  float k = floor(zz / spacing + 0.5);
  float e = 0.0;
  for (int i = -2; i <= 2; i++) {
    float lz = (k + float(i)) * spacing + phase - uTravel;
    vec2 d = p - vec2(lx, lz);
    float r2 = dot(d, d);
    e += h * h * h / pow(h * h + r2, 1.5);
  }
  return e;
}
float box2(vec2 p, vec2 b, float r) { vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
void main() {
  vec2 p = vW.xz;
  float zw = p.y + uTravel;
  // --- surface type
  float asph = step(-6.95, p.x) * step(p.x, 6.45) + step(7.75, p.x) * step(p.x, 19.2);
  float walk = step(p.x, -7.2) * step(-11.5, p.x) + step(19.6, p.x) * step(p.x, 23.0);
  float curb = 1.0 - asph - walk;
  vec2 q = vec2(p.x, zw);
  float n1 = fbm(q * 1.7), n2 = vnoise(q * 23.0), n3 = fbm(q * 0.11 + 3.1);
  vec3 alb = vec3(0.032, 0.033, 0.036) * (0.75 + 0.5 * n1) * (0.85 + 0.3 * n2);
  // lane markings (retro-reflective paint)
  float mk = 0.0;
  float dash = step(fract(zw / 15.0), 0.4);
  mk += (1.0 - smoothstep(0.065, 0.085, abs(p.x - 1.8))) * dash;
  mk += (1.0 - smoothstep(0.065, 0.085, abs(p.x + 1.8))) * dash;
  mk += 1.0 - smoothstep(0.07, 0.09, abs(p.x + 5.5));
  mk += 1.0 - smoothstep(0.07, 0.09, abs(p.x - 6.2));
  mk += (1.0 - smoothstep(0.065, 0.085, abs(p.x - 11.4))) * dash;
  mk += (1.0 - smoothstep(0.065, 0.085, abs(p.x - 15.0))) * dash;
  mk = clamp(mk, 0.0, 1.0) * asph * (0.75 + 0.25 * n2);
  alb = mix(alb, vec3(0.42, 0.42, 0.4), mk);
  // sidewalk pavers
  vec2 pv = fract(vec2(p.x, zw) / vec2(0.6, 0.6));
  float grout = step(0.95, max(pv.x, pv.y));
  alb = mix(alb, vec3(0.075, 0.074, 0.07) * (0.8 + 0.4 * n1) * (1.0 - grout * 0.5), walk);
  alb = mix(alb, vec3(0.1, 0.1, 0.1), curb);
  // wetness / puddles
  float puddle = smoothstep(0.52, 0.68, n3 + 0.12 * n1);
  float wet = mix(0.55, 1.0, puddle) * (1.0 - mk * 0.6);
  alb *= mix(1.0, 0.55, wet * 0.8);

  // --- lighting (illuminance, lux-like)
  float E = uAmb;
  vec3 Ec = vec3(uAmb) * vec3(0.55, 0.65, 0.9);
  float el = lampRow(p, 4.1, 34.0, 0.0, 9.2) + lampRow(p, 10.2, 34.0, 0.0, 9.2) + 0.8 * lampRow(p, -6.4, 34.0, 17.0, 8.0);
  Ec += uLampCol * el * uLampI;
  // Car headlights and tail lights.
  for (int i = 0; i < 10; i++) {
    vec4 c = uCars[i];
    if (c.w < -0.5) continue;
    float kind = c.w;
    vec2 fwd = vec2(sin(c.z), cos(c.z));
    if (kind > 1.5) fwd = -fwd;
    vec2 side = vec2(fwd.y, -fwd.x);
    vec2 d = p - c.xy;
    float u = dot(d, fwd) - 2.3;
    float v = dot(d, side);
    float intensity = kind < 0.5 ? uHead : 0.55 * uHead + 0.4;
    float cone = smoothstep(0.0, 2.5, u) * exp(-u / 26.0) * exp(-v * v / (0.35 + pow(u * 0.23, 2.0)));
    Ec += vec3(1.0, 0.97, 0.92) * cone * 38.0 * intensity;
    float ub = -dot(d, fwd) - 2.45;
    float tail = exp(-(ub * ub) * 0.25 - v * v * 1.2) * step(0.0, ub) + exp(-dot(d + fwd * 2.45, d + fwd * 2.45) * 1.4);
    Ec += vec3(1.0, 0.06, 0.03) * tail * (kind > 1.5 ? 0.0 : 1.6);
    // contact shadow
    vec2 lp = vec2(dot(d, side), dot(d, fwd));
    float sd = box2(lp, vec2(0.95, 2.35), 0.5);
    float sh = 1.0 - 0.85 * (1.0 - smoothstep(-0.15, 0.55, sd));
    Ec *= sh;
  }
  vec3 col = alb / 3.14159 * Ec;
  // marking retro-reflection from our headlights
  col += mk * vec3(0.9, 0.9, 0.85) * 0.02 * uHead * smoothstep(40.0, 5.0, length(p - uCars[0].xy));

  // --- wet reflection
  vec3 V = normalize(uCamPos - vW);
  float cosv = clamp(V.y, 0.0, 1.0);
  float F = 0.03 + 0.97 * pow(1.0 - cosv, 5.0);
  float rough = mix(0.55, 0.06, puddle) + mk * 0.3;
  vec2 ruv = vRefl.xy / vRefl.w;
  vec2 nrm = (vec2(vnoise(q * 9.0), vnoise(q * 9.0 + 7.3)) - 0.5) * 0.012 * (0.3 + rough);
  vec3 refl = vec3(0.0);
  if (uReflOn > 0.5) {
    float spread = mix(0.001, 0.045, rough);
    float tw = 0.0;
    for (int i = -4; i <= 4; i++) {
      float f = float(i) / 4.0;
      float w = exp(-f * f * 2.0);
      refl += texture2D(tRefl, ruv + nrm + vec2(0.0, f * spread) + vec2(f * spread * 0.08, 0.0)).rgb * w;
      tw += w;
    }
    refl /= tw;
  }
  float reflAmt = F * wet * mix(0.35, 1.0, puddle) * (asph + walk * 0.35);
  col += refl * reflAmt;
  // fog
  float dist = length(vW - uCamPos);
  float fog = 1.0 - exp(-dist * uFogD);
  col = mix(col, uFog, fog);
  gl_FragColor = vec4(col, 1.0);
}`;

const BUILDING_VERT = /* glsl */`
attribute vec3 aSize; attribute float aSeed;
varying vec3 vLocal; varying vec3 vN; varying vec3 vW; varying float vSeed; varying vec3 vSize;
void main() {
  vec3 p = position * aSize; p.y += aSize.y * 0.5;
  vec4 w = modelMatrix * instanceMatrix * vec4(p, 1.0);
  vLocal = p; vN = normal; vW = w.xyz; vSeed = aSeed; vSize = aSize;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const BUILDING_FRAG = /* glsl */`
precision highp float;
uniform vec3 uCamPos; uniform vec3 uFog; uniform float uFogD; uniform float uWin;
varying vec3 vLocal; varying vec3 vN; varying vec3 vW; varying float vSeed; varying vec3 vSize;
float h21(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
void main() {
  vec2 uv; float roof = 0.0;
  if (abs(vN.x) > 0.5) uv = vec2(vLocal.z + vSize.z * 0.5, vLocal.y);
  else if (abs(vN.z) > 0.5) uv = vec2(vLocal.x + vSize.x * 0.5, vLocal.y);
  else { uv = vLocal.xz; roof = 1.0; }
  float s = vSeed;
  float fh = 3.4 + 0.8 * h21(vec2(s, 1.7));
  float cw = 2.0 + 1.6 * h21(vec2(s, 3.1));
  vec2 cuv = uv / vec2(cw, fh);
  vec2 cell = floor(cuv);
  vec2 f = fract(cuv);
  vec2 fw = fwidth(cuv);
  float detail = 1.0 - smoothstep(0.18, 0.45, max(fw.x, fw.y));
  float style = h21(vec2(s, 9.2));
  float wx = style > 0.6 ? 0.05 : 0.16;
  float win = step(wx, f.x) * step(f.x, 1.0 - wx) * step(0.24, f.y) * step(f.y, 0.84);
  // Lights come in clusters (offices / floors), most of the facade is dark.
  float grp = h21(vec2(floor(cell.x / 6.0) + s * 3.7, cell.y * 1.13));
  float busy = 0.1 + 0.25 * h21(vec2(s, 5.5));
  float lit = step(grp, busy) * step(0.25, h21(cell + s * 17.13));
  float warm = step(0.55, h21(vec2(floor(cell.x / 6.0), cell.y) + s));
  vec3 wc = mix(vec3(0.72, 0.84, 1.0), vec3(1.0, 0.74, 0.46), warm) * (0.55 + 0.6 * h21(cell + 4.4));
  vec3 col = vec3(0.006, 0.007, 0.009);
  col = mix(col, vec3(0.011, 0.013, 0.018), win);
  col += win * lit * wc * uWin * (1.0 - roof);
  vec3 avg = vec3(0.008, 0.009, 0.012) + vec3(0.95, 0.82, 0.66) * 0.18 * busy * uWin * (1.0 - roof);
  col = mix(avg, col, detail);
  // roof edge lights on some towers
  float edge = step(0.82, style) * smoothstep(vSize.y - 0.5, vSize.y - 0.2, vLocal.y) * (1.0 - roof);
  col += edge * vec3(1.0, 0.25, 0.2) * 1.5 * step(0.5, fract(uv.x * 0.08));
  col = mix(col, vec3(0.004), roof);
  float dist = length(vW - uCamPos);
  col = mix(col, uFog, 1.0 - exp(-dist * uFogD));
  gl_FragColor = vec4(col, 1.0);
}`;

const LIDAR_VERT = /* glsl */`
attribute float aT; attribute float aCat; attribute float aH;
uniform float uTime; uniform float uScroll; uniform vec3 uObj[8]; uniform float uSize; uniform float uT0;
varying float vA; varying float vH; varying float vFlash; varying float vNear;
void main() {
  vec3 p = position;
  vNear = smoothstep(2.5, 10.0, length(position.xz));
  int c = int(aCat + 0.5);
  if (c == 0) p.z -= uScroll;
  else if (c >= 2) p += uObj[c - 2];
  float age = uTime - (uT0 + aT);
  vA = smoothstep(0.0, 0.04, age);
  vFlash = exp(-max(age, 0.0) * 5.0) * vA;
  vH = aH;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = clamp(uSize / -mv.z, 1.2, 5.0);
}`;
const LIDAR_FRAG = /* glsl */`
precision highp float;
uniform float uAlpha; uniform float uBoost;
varying float vA; varying float vH; varying float vFlash; varying float vNear;
void main() {
  vec2 d = gl_PointCoord - 0.5;
  float r = dot(d, d);
  if (r > 0.25) discard;
  vec3 c = mix(vec3(0.3, 0.72, 1.0), vec3(0.95, 0.98, 1.0), smoothstep(0.2, 3.5, vH));
  float a = vA * uAlpha * (0.55 + vFlash * 3.0) * (1.0 - r * 3.0) * (0.25 + 0.75 * vNear);
  gl_FragColor = vec4(c * a * uBoost, 1.0);
}`;

const STREAM_VERT = /* glsl */`
attribute float aU; attribute float aAng;
uniform vec3 uP0; uniform vec3 uP1; uniform vec3 uP2; uniform vec3 uP3; uniform float uRad;
varying float vU; varying vec3 vN; varying vec3 vW;
vec3 bez(float t) { float s = 1.0 - t; return s*s*s*uP0 + 3.0*s*s*t*uP1 + 3.0*s*t*t*uP2 + t*t*t*uP3; }
void main() {
  vec3 p = bez(aU);
  vec3 tg = normalize(bez(min(aU + 0.005, 1.0)) - bez(max(aU - 0.005, 0.0)));
  vec3 up = abs(tg.y) > 0.9 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 1.0, 0.0);
  vec3 b1 = normalize(cross(tg, up)); vec3 b2 = cross(tg, b1);
  vec3 n = cos(aAng) * b1 + sin(aAng) * b2;
  vec4 w = modelMatrix * vec4(p + n * uRad, 1.0);
  vU = aU; vN = normalize(mat3(modelMatrix) * n); vW = w.xyz;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;
const STREAM_FRAG = /* glsl */`
precision highp float;
uniform float uTime; uniform float uReveal; uniform float uAlpha; uniform float uLen; uniform float uSeed; uniform vec3 uCol;
uniform vec3 uCamPos;
varying float vU; varying vec3 vN; varying vec3 vW;
float h11(float p) { return fract(sin(p * 91.3458) * 47453.5453); }
void main() {
  if (vU > uReveal) discard;
  float s = vU * uLen;
  // packets travel from sensor (u=0) toward the computer (u=1)
  float x = s * 7.0 - uTime * 3.2 * 7.0 + uSeed * 13.0;
  float id = floor(x);
  float f = fract(x);
  float on = step(0.45, h11(id + uSeed));
  float pk = on * smoothstep(0.0, 0.1, f) * (1.0 - smoothstep(0.25, 0.6, f));
  float head = exp(-(uReveal - vU) * 60.0) * step(uReveal, 0.999);
  vec3 V = normalize(uCamPos - vW);
  float rim = 0.35 + 0.65 * (1.0 - abs(dot(V, vN)));
  float I = (0.22 + pk * 2.8 + head * 4.0) * rim;
  gl_FragColor = vec4(uCol * I * uAlpha, 1.0);
}`;

const RIBBON_FRAG = /* glsl */`
precision highp float;
uniform float uTime; uniform float uAlpha;
varying vec2 vUv;
void main() {
  float edge = smoothstep(0.0, 0.18, vUv.y) * smoothstep(1.0, 0.82, vUv.y);
  float core = exp(-pow((vUv.y - 0.5) * 7.0, 2.0));
  float along = smoothstep(0.0, 0.08, vUv.x) * (1.0 - smoothstep(0.6, 1.0, vUv.x));
  float chev = smoothstep(0.55, 1.0, fract(vUv.x * 14.0 - uTime * 1.6 - abs(vUv.y - 0.5) * 1.2));
  vec3 c = vec3(0.55, 0.85, 1.0) * (edge * 0.18 + core * 0.55 + chev * edge * 0.5);
  gl_FragColor = vec4(c * along * uAlpha, 1.0);
}`;

export class RoadWorld {
  constructor(envs) {
    this.name = 'road';
    this.frame = 'road';
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x020306);
    this.camera = new THREE.PerspectiveCamera(40, 16 / 9, 0.1, 2000);
    this.envs = envs;
    this.nearMul = 0.012; this.farMul = 4000; this.farMax = 1600; this.nearMin = 0.0004;
    this.fogColor = new THREE.Color(0x05070c);
    this.carMatrix = new THREE.Matrix4();
    this._tmp = new THREE.Vector3();
  }

  init() {
    const env = this.envs.night;
    const S = this.scene;
    this.fogD = 0.0065;

    // Sky dome with light-pollution glow on the horizon.
    const sky = new THREE.Mesh(new THREE.SphereGeometry(1400, 32, 16), new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false, fog: false,
      uniforms: {},
      vertexShader: 'varying vec3 vP; void main(){ vP = normalize(position); vec4 p = projectionMatrix*modelViewMatrix*vec4(position,1.0); gl_Position = p.xyww; }',
      fragmentShader: `varying vec3 vP; void main(){ float y = vP.y; vec3 c = mix(vec3(0.03,0.04,0.06), vec3(0.004,0.006,0.012), smoothstep(-0.02, 0.35, y));
        c += vec3(0.05,0.035,0.03) * exp(-abs(y) * 22.0); gl_FragColor = vec4(c, 1.0);} `,
    }));
    sky.renderOrder = -10;
    sky.frustumCulled = false;
    S.add(sky);
    this.sky = sky;

    // --- road surface with reflections -------------------------------------
    this.reflRT = new THREE.WebGLRenderTarget(512, 288, { type: THREE.HalfFloatType, samples: 0 });
    this.mirrorCam = new THREE.PerspectiveCamera();
    this.texMat = new THREE.Matrix4();
    this.roadMat = new THREE.ShaderMaterial({
      vertexShader: ROAD_VERT, fragmentShader: ROAD_FRAG,
      uniforms: {
        uTravel: { value: 0 }, tRefl: { value: this.reflRT.texture }, uReflOn: { value: 1 }, uTexMat: { value: this.texMat },
        uCamPos: { value: new THREE.Vector3() }, uFog: { value: this.fogColor }, uFogD: { value: this.fogD },
        uLampI: { value: 17 }, uLampCol: { value: new THREE.Color(1.0, 0.86, 0.7) },
        uCars: { value: Array.from({ length: 10 }, () => new THREE.Vector4(0, 0, 0, -1)) },
        uHead: { value: 1 }, uAmb: { value: 0.35 }, uTime: { value: 0 }, uReflTexel: { value: new THREE.Vector2() },
      },
    });
    const road = new THREE.Mesh(new THREE.PlaneGeometry(90, 900, 1, 1), this.roadMat);
    road.rotation.x = -Math.PI / 2;
    road.position.set(8, 0, 200);
    S.add(road);
    this.road = road;

    // Median barrier and curbs.
    const concrete = new THREE.MeshStandardMaterial({ color: 0x6b6b68, roughness: 0.85, metalness: 0, envMap: env, envMapIntensity: 0.3 });
    const barrier = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.85, 900), concrete);
    barrier.position.set(7.1, 0.425, 200);
    S.add(barrier);
    const barrierCap = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.12, 900), concrete);
    barrierCap.position.set(7.1, 0.9, 200);
    S.add(barrierCap);
    const curb = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.15, 900), concrete);
    curb.position.set(-7.05, 0.075, 200);
    S.add(curb);

    // --- street lights (instanced, recycled as we drive) ----------------------
    const poleMat = new THREE.MeshStandardMaterial({ color: 0x3c3e42, roughness: 0.5, metalness: 0.7, envMap: env });
    const headMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(1.0, 0.9, 0.78).multiplyScalar(28) });
    this.lamps = [];
    for (let i = 0; i < 16; i++) this.lamps.push({ x: 7.1, z0: i * 34, arms: [-3.0, 3.1], h: 9.4 });
    for (let i = 0; i < 16; i++) this.lamps.push({ x: -8.2, z0: i * 34 + 17, arms: [1.8], h: 8.2 });
    const armCount = this.lamps.reduce((a, l) => a + l.arms.length, 0);
    this.poleMesh = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.09, 0.14, 1, 10), poleMat, this.lamps.length);
    this.armMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 0.08, 0.1), poleMat, armCount);
    this.headMesh = new THREE.InstancedMesh(new RoundedBoxGeometry(0.75, 0.1, 0.32, 2, 0.04), headMat, armCount);
    S.add(this.poleMesh, this.armMesh, this.headMesh);
    // Glow halos (atmospheric scatter) around lamp heads.
    const haloMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uCol: { value: new THREE.Color(1.0, 0.82, 0.62) }, uI: { value: 0.35 } },
      vertexShader: `varying vec2 vUv; void main(){ vUv = uv; vec4 c = modelViewMatrix * instanceMatrix * vec4(0.0,0.0,0.0,1.0); c.xy += position.xy * 3.2; gl_Position = projectionMatrix * c; }`,
      fragmentShader: `uniform vec3 uCol; uniform float uI; varying vec2 vUv; void main(){ float d = length(vUv - 0.5) * 2.0; float a = exp(-d*d*5.0) * 0.6 + exp(-d * 9.0) * 0.8; gl_FragColor = vec4(uCol * a * uI, 1.0);} `,
    });
    this.haloMesh = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), haloMat, armCount);
    this.haloMesh.frustumCulled = false;
    S.add(this.haloMesh);
    this.lampLights = [];
    for (let i = 0; i < 4; i++) {
      const L = new THREE.PointLight(0xffdcb4, 650, 45, 2);
      S.add(L);
      this.lampLights.push(L);
    }

    // --- buildings ---------------------------------------------------------
    const r = rng(42);
    const B = [];
    const P = 760;
    const addRow = (xNear, dir, count, minH, maxH, depthMin, depthMax) => {
      let z = 0;
      while (z < P && B.length < 400) {
        const w = r.range(14, 42);
        const h = r() < 0.12 ? r.range(maxH * 0.9, maxH * 1.9) : r.range(minH, maxH);
        const d = r.range(depthMin, depthMax);
        B.push({ x: xNear + dir * (d / 2 + r.range(0, 6)), z0: z + w / 2, size: [d, h, w], seed: r() * 100 });
        z += w + r.range(2, 12);
      }
    };
    addRow(-15, -1, 0, 10, 48, 14, 30);
    addRow(27, 1, 0, 12, 60, 16, 34);
    addRow(-62, -1, 0, 30, 110, 25, 50);
    addRow(75, 1, 0, 30, 120, 25, 50);
    this.buildings = B;
    this.bPeriod = P;
    const bGeo = new THREE.BoxGeometry(1, 1, 1);
    const bSize = new Float32Array(B.length * 3), bSeed = new Float32Array(B.length);
    B.forEach((b, i) => { bSize.set(b.size, i * 3); bSeed[i] = b.seed; });
    bGeo.setAttribute('aSize', new THREE.InstancedBufferAttribute(bSize, 3));
    bGeo.setAttribute('aSeed', new THREE.InstancedBufferAttribute(bSeed, 1));
    this.bMat = new THREE.ShaderMaterial({
      vertexShader: BUILDING_VERT, fragmentShader: BUILDING_FRAG,
      uniforms: { uCamPos: { value: new THREE.Vector3() }, uFog: { value: this.fogColor }, uFogD: { value: this.fogD * 0.8 }, uWin: { value: 1.1 } },
    });
    this.bMesh = new THREE.InstancedMesh(bGeo, this.bMat, B.length);
    this.bMesh.frustumCulled = false;
    S.add(this.bMesh);

    // --- lights ------------------------------------------------------------
    this.hemi = new THREE.HemisphereLight(0x2a3550, 0x050505, 0.25);
    S.add(this.hemi);

    // --- hero car ------------------------------------------------------------
    this.carGeo = buildCarBody();
    this.car = this.buildCar(0x2c3036, true);
    S.add(this.car.root);
    this.traffic = TRAFFIC.map((tr) => { const c = this.buildCar(tr.paint, false); S.add(c.root); return { ...tr, car: c }; });
    this.oncoming = ONCOMING.map((tr) => { const c = this.buildCar(0x303236, false, true); S.add(c.root); return { ...tr, car: c }; });

    // Headlight spot for our car (lights objects ahead).
    const head = new THREE.SpotLight(0xfff4e6, 900, 70, 0.42, 0.7, 2);
    head.position.set(0, 0.7, 2.3);
    head.target.position.set(0, 0.2, 20);
    this.car.root.add(head, head.target);
    this.headSpot = head;

    // --- pedestrian ---------------------------------------------------------
    this.ped = this.buildPedestrian();
    S.add(this.ped);

    // --- lidar ---------------------------------------------------------------
    this.buildLidar();

    // --- detection boxes -------------------------------------------------------
    const boxMat = new THREE.LineBasicMaterial({ color: new THREE.Color(0.75, 0.92, 1.0).multiplyScalar(2.2), transparent: true, opacity: 0 });
    this.detBoxes = [
      { target: 'traffic0', size: [2.0, 1.55, 4.9] },
      { target: 'ped', size: [0.8, 1.9, 0.7] },
      { target: 'traffic1', size: [2.0, 1.55, 4.9] },
    ].map((d) => {
      const g = new THREE.EdgesGeometry(new THREE.BoxGeometry(...d.size));
      const m = new THREE.LineSegments(g, boxMat);
      m.userData = d;
      S.add(m);
      return m;
    });
    this.boxMat = boxMat;

    // --- data streams ------------------------------------------------------------
    this.buildStreams();

    // --- planned trajectory ribbon -------------------------------------------
    const N = 64;
    const rg = new THREE.BufferGeometry();
    const rp = new Float32Array(N * 2 * 3), ruv = new Float32Array(N * 2 * 2), ri = [];
    for (let i = 0; i < N; i++) {
      ruv.set([i / (N - 1), 0, i / (N - 1), 1], i * 4);
      if (i < N - 1) { const a = i * 2; ri.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
    }
    rg.setAttribute('position', new THREE.BufferAttribute(rp, 3));
    rg.setAttribute('uv', new THREE.BufferAttribute(ruv, 2));
    rg.setIndex(ri);
    this.ribbonMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uAlpha: { value: 0 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} ',
      fragmentShader: RIBBON_FRAG,
    });
    this.ribbon = new THREE.Mesh(rg, this.ribbonMat);
    this.ribbon.frustumCulled = false;
    this.ribbonN = N;
    S.add(this.ribbon);
  }

  buildCar(paint, hero, oncoming = false) {
    const env = this.envs.night;
    const root = new THREE.Group();
    const bodyGroup = new THREE.Group();
    root.add(bodyGroup);
    const paintM = paintMaterial(paint, env, hero ? { metalness: 0.72, roughness: 0.3, envI: 1.6 } : { metalness: 0.5, roughness: 0.36, envI: 1.2 });
    const glassM = new THREE.MeshPhysicalMaterial({
      color: 0x050608, metalness: 0.1, roughness: 0.04, clearcoat: 1, clearcoatRoughness: 0.02,
      envMap: env, envMapIntensity: 1.4, side: THREE.DoubleSide,
    });
    const body = new THREE.Mesh(this.carGeo.body, paintM);
    const glass = new THREE.Mesh(this.carGeo.glass, glassM);
    const hood = new THREE.Mesh(this.carGeo.hood, paintM);
    bodyGroup.add(body);
    const ghGroup = new THREE.Group(); ghGroup.add(glass); root.add(ghGroup);
    const hoodGroup = new THREE.Group(); hoodGroup.add(hood); root.add(hoodGroup);
    // Under-chassis filler.
    const dark = new THREE.MeshStandardMaterial({ color: 0x050505, roughness: 0.9 });
    const chassis = new THREE.Mesh(new THREE.BoxGeometry(1.35, 0.16, 4.2), dark);
    chassis.position.set(0, 0.22, -0.02);
    bodyGroup.add(chassis);
    // Wheel wells close the arches from inside.
    for (const z of CAR.wheelZ) {
      const well = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.5, 0.95), dark);
      well.position.set(0, 0.55, z);
      bodyGroup.add(well);
    }
    // Wheels.
    const wm = {
      tire: new THREE.MeshStandardMaterial({ color: 0x0b0b0c, roughness: 0.75, envMap: env, envMapIntensity: 0.3 }),
      rim: new THREE.MeshStandardMaterial({ color: 0x9a9da2, metalness: 1, roughness: 0.25, envMap: env }),
      rimDark: new THREE.MeshStandardMaterial({ color: 0x121315, metalness: 0.6, roughness: 0.5, envMap: env }),
      rimInner: new THREE.MeshStandardMaterial({ color: 0x1a1b1d, metalness: 0.8, roughness: 0.4, envMap: env }),
    };
    const wheels = [];
    for (const z of CAR.wheelZ) for (const s of [-1, 1]) {
      const w = buildWheel(wm);
      w.position.set(s * CAR.track, CAR.wheelR, z);
      if (s < 0) w.rotation.y = Math.PI;
      root.add(w);
      wheels.push({ w, s });
    }
    // Light bars.
    const frontM = new THREE.MeshBasicMaterial({ color: new THREE.Color(1, 0.97, 0.93).multiplyScalar(oncoming ? 30 : 16), side: THREE.DoubleSide });
    const rearM = new THREE.MeshBasicMaterial({ color: new THREE.Color(1, 0.04, 0.02).multiplyScalar(oncoming ? 3 : 7), side: THREE.DoubleSide });
    const fb = new THREE.Mesh(lightBar(this.carGeo.contourFront, 0.715, 0.022, 0.008, true), frontM);
    const rb = new THREE.Mesh(lightBar(this.carGeo.contourRear, 0.9, 0.035, 0.008, false), rearM);
    bodyGroup.add(fb, rb);
    const car = { root, bodyGroup, ghGroup, hoodGroup, wheels, paintM, frontM, rearM };
    if (!hero) return car;

    // Roof lidar crown + mirrors (hero only).
    const blackGloss = new THREE.MeshPhysicalMaterial({ color: 0x060607, roughness: 0.15, clearcoat: 1, envMap: env });
    const crown = new THREE.Mesh(new RoundedBoxGeometry(0.34, 0.07, 0.22, 3, 0.03), blackGloss);
    crown.position.set(0, 1.405, 0.33);
    ghGroup.add(crown);
    const lens = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.03, 0.01), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.05, 0.12, 0.22) }));
    lens.position.set(0, 1.405, 0.442);
    ghGroup.add(lens);
    for (const s of [-1, 1]) {
      const m = new THREE.Mesh(new RoundedBoxGeometry(0.18, 0.09, 0.07, 3, 0.03), paintM);
      m.position.set(s * 0.98, 1.0, 0.9);
      bodyGroup.add(m);
    }

    // Interior (visible once the body opens).
    const leather = new THREE.MeshStandardMaterial({ color: 0x141312, roughness: 0.82, envMap: env, envMapIntensity: 0.4 });
    const trim = new THREE.MeshStandardMaterial({ color: 0x0a0a0b, roughness: 0.6, metalness: 0.2, envMap: env, envMapIntensity: 0.5 });
    const inter = new THREE.Group();
    const seatBase = new RoundedBoxGeometry(0.5, 0.14, 0.52, 3, 0.05);
    const seatBack = new RoundedBoxGeometry(0.5, 0.62, 0.14, 3, 0.05);
    for (const s of [-1, 1]) {
      const b = new THREE.Mesh(seatBase, leather); b.position.set(s * 0.4, 0.46, -0.05); inter.add(b);
      const k = new THREE.Mesh(seatBack, leather); k.position.set(s * 0.4, 0.8, -0.33); k.rotation.x = -0.18; inter.add(k);
    }
    const rear = new THREE.Mesh(new RoundedBoxGeometry(1.35, 0.14, 0.5, 3, 0.05), leather); rear.position.set(0, 0.47, -1.02); inter.add(rear);
    const rearB = new THREE.Mesh(new RoundedBoxGeometry(1.35, 0.55, 0.14, 3, 0.05), leather); rearB.position.set(0, 0.78, -1.3); rearB.rotation.x = -0.2; inter.add(rearB);
    const dash = new THREE.Mesh(new RoundedBoxGeometry(1.7, 0.2, 0.36, 3, 0.06), trim); dash.position.set(0, 0.84, 0.92); inter.add(dash);
    const screen = new THREE.Mesh(new RoundedBoxGeometry(0.36, 0.17, 0.02, 2, 0.01), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.05, 0.08, 0.12) }));
    screen.position.set(0, 0.9, 0.66); screen.rotation.x = -0.35; inter.add(screen);
    const wheel = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.02, 10, 40), trim);
    wheel.position.set(0.38, 0.9, 0.62); wheel.rotation.x = -0.35; inter.add(wheel);
    const floor = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.03, 3.4), new THREE.MeshStandardMaterial({ color: 0x080808, roughness: 1 }));
    floor.position.set(0, 0.3, -0.2); inter.add(floor);
    // Centre console that houses the computer.
    const cons = new THREE.Group();
    const cw = 0.24, cl = 0.3;
    const side = new THREE.BoxGeometry(0.02, 0.2, 0.62);
    for (const s of [-1, 1]) { const m = new THREE.Mesh(side, trim); m.position.set(s * (cw / 2 + 0.01), 0.39, 0.2); cons.add(m); }
    const endG = new THREE.BoxGeometry(cw + 0.04, 0.2, 0.02);
    for (const s of [-1, 1]) { const m = new THREE.Mesh(endG, trim); m.position.set(0, 0.39, 0.2 + s * cl); cons.add(m); }
    inter.add(cons);
    const lid = new THREE.Mesh(new RoundedBoxGeometry(cw + 0.05, 0.03, 0.66, 3, 0.012), leather);
    lid.position.set(0, 0.5, 0.2);
    inter.add(lid);
    bodyGroup.add(inter);
    car.consoleLid = lid;

    // The driving computer, in its own board frame (mm -> m).
    const hm = housingMaterials(this.envs.studio);
    const housing = buildHousing(hm, { lowDetail: true });
    const boardRoot = new THREE.Group();
    boardRoot.matrixAutoUpdate = false;
    boardRoot.matrix.copy(BOARD_ANCHOR);
    boardRoot.add(housing);
    this.pcbPlane = new THREE.Mesh(
      new THREE.BoxGeometry(230, 1.6, 160),
      new THREE.MeshStandardMaterial({ color: 0x0c140f, roughness: 0.5, metalness: 0.1, envMap: this.envs.studio }),
    );
    this.pcbPlane.position.y = -0.8;
    boardRoot.add(this.pcbPlane);
    bodyGroup.add(boardRoot);
    // A cool key light that singles out the computer as we dive toward it.
    const keyL = new THREE.PointLight(0xdce8ff, 0, 1.4, 2);
    keyL.position.set(-0.12, 0.8, 0.55);
    bodyGroup.add(keyL);
    this.consoleLight = keyL;
    car.housing = housing;
    car.boardRoot = boardRoot;
    return car;
  }

  setPCBTexture(tex) {
    this.pcbPlane.material = [
      this.pcbPlane.material, this.pcbPlane.material,
      new THREE.MeshStandardMaterial({ map: tex, roughness: 0.45, metalness: 0.2, envMap: this.envs.studio, envMapIntensity: 0.6 }),
      this.pcbPlane.material, this.pcbPlane.material, this.pcbPlane.material,
    ];
  }

  buildPedestrian() {
    const g = new THREE.Group();
    const cloth = new THREE.MeshStandardMaterial({ color: 0x1b1d22, roughness: 0.8 });
    const skin = new THREE.MeshStandardMaterial({ color: 0x5a4538, roughness: 0.7 });
    const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.19, 0.5, 6, 12), cloth);
    torso.position.y = 1.22; g.add(torso);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.11, 16, 12), skin);
    head.position.y = 1.68; g.add(head);
    const legGeo = new THREE.CapsuleGeometry(0.075, 0.72, 4, 8);
    legGeo.translate(0, -0.42, 0);
    const legs = [];
    for (const s of [-1, 1]) {
      const l = new THREE.Mesh(legGeo, cloth); l.position.set(s * 0.1, 0.92, 0); g.add(l); legs.push(l);
    }
    const armGeo = new THREE.CapsuleGeometry(0.055, 0.55, 4, 8);
    armGeo.translate(0, -0.3, 0);
    const arms = [];
    for (const s of [-1, 1]) {
      const a = new THREE.Mesh(armGeo, cloth); a.position.set(s * 0.25, 1.45, 0); g.add(a); arms.push(a);
    }
    g.userData = { legs, arms };
    return g;
  }

  // ---------------------------------------------------------------- lidar
  buildLidar() {
    const origin = new THREE.Vector3(0, 1.45, 0.33);
    const s0 = travel(T_SCAN);
    // Scene boxes at scan time (car-centric frame).
    const boxes = [];
    const addBox = (min, max, cat) => boxes.push({ min, max, cat });
    for (const b of this.buildings) {
      const z = wrap(b.z0 - s0, -260, this.bPeriod);
      addBox([b.x - b.size[0] / 2, 0, z - b.size[2] / 2], [b.x + b.size[0] / 2, b.size[1], z + b.size[2] / 2], 0);
    }
    addBox([6.82, 0, -300], [7.38, 0.95, 400], 0); // barrier
    addBox([-7.2, 0, -300], [-6.9, 0.15, 400], 0); // curb
    for (const l of this.lamps) {
      const z = wrap(l.z0 - s0, -120, 16 * 34);
      addBox([l.x - 0.12, 0, z - 0.12], [l.x + 0.12, l.h, z + 0.12], 0);
    }
    TRAFFIC.slice(0, 2).forEach((tr, i) => {
      const z = tr.z0 + tr.dv * T_SCAN;
      addBox([tr.x - 0.93, 0.22, z - 2.35], [tr.x + 0.93, 0.95, z + 2.35], 2 + i);
      addBox([tr.x - 0.72, 0.95, z - 1.6], [tr.x + 0.72, 1.42, z + 0.9], 2 + i);
    });
    {
      const z = PED.z0 - s0;
      addBox([PED.x - 0.22, 0, z - 0.14], [PED.x + 0.22, 1.78, z + 0.14], 4);
    }
    const pos = [], aT = [], aCat = [], aH = [];
    const dir = new THREE.Vector3();
    const r = rng(9);
    const channels = 72;
    for (let c = 0; c < channels; c++) {
      const u = c / (channels - 1);
      const el = THREE.MathUtils.degToRad(-24 + 36 * Math.pow(u, 1.35));
      const azSteps = 1300;
      for (let a = 0; a < azSteps; a++) {
        const az = (a / azSteps) * Math.PI * 2 + r() * 0.002;
        dir.set(Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el));
        let tBest = 90, cat = -1;
        // ground
        if (dir.y < -1e-4) {
          const tg = -origin.y / dir.y;
          const gx = origin.x + dir.x * tg;
          if (tg < tBest && gx > -24 && gx < 30) { tBest = tg; cat = 1; }
        }
        for (const b of boxes) {
          let t0 = 0, t1 = tBest;
          let hit = true;
          for (let k = 0; k < 3; k++) {
            const o = origin.getComponent(k), d = dir.getComponent(k);
            if (Math.abs(d) < 1e-8) { if (o < b.min[k] || o > b.max[k]) { hit = false; break; } continue; }
            let ta = (b.min[k] - o) / d, tb = (b.max[k] - o) / d;
            if (ta > tb) [ta, tb] = [tb, ta];
            t0 = Math.max(t0, ta); t1 = Math.min(t1, tb);
            if (t0 > t1) { hit = false; break; }
          }
          if (hit && t0 < tBest && t0 > 0.5) { tBest = t0; cat = b.cat; }
        }
        if (cat < 0) continue;
        if (cat === 1 && r() > Math.min(1, 0.15 + tBest / 16)) continue; // thin the dense near rings
        const p = origin.clone().addScaledVector(dir, tBest);
        let pc = cat;
        if (cat >= 2) {
          // store object points relative to the object's scan-time position
          if (cat === 4) p.z -= PED.z0 - s0; else p.z -= TRAFFIC[cat - 2].z0 + TRAFFIC[cat - 2].dv * T_SCAN;
          if (cat !== 4) p.x -= TRAFFIC[cat - 2].x; else p.x -= PED.x;
        }
        pos.push(p.x, p.y, p.z);
        aT.push(tBest / 55);
        aCat.push(pc);
        aH.push(p.y);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('aT', new THREE.Float32BufferAttribute(aT, 1));
    g.setAttribute('aCat', new THREE.Float32BufferAttribute(aCat, 1));
    g.setAttribute('aH', new THREE.Float32BufferAttribute(aH, 1));
    this.lidarMat = new THREE.ShaderMaterial({
      vertexShader: LIDAR_VERT, fragmentShader: LIDAR_FRAG,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: {
        uTime: { value: 0 }, uScroll: { value: 0 }, uObj: { value: Array.from({ length: 8 }, () => new THREE.Vector3()) },
        uSize: { value: 60 }, uT0: { value: T_SCAN }, uAlpha: { value: 1 }, uBoost: { value: 1 },
      },
    });
    this.lidar = new THREE.Points(g, this.lidarMat);
    this.lidar.frustumCulled = false;
    this.lidarCount = aT.length;
    this.scene.add(this.lidar);
  }

  // ---------------------------------------------------------------- streams
  buildStreams() {
    // Endpoints in the car frame. Sensors -> computer connectors (+x board = car forward).
    const conn = (i) => {
      // board frame connector i -> car frame
      const zc = -66 + (i % 8) * 16.5;
      return new THREE.Vector3(HOUSING.outerX + 16, 0.5, zc).applyMatrix4(BOARD_ANCHOR);
    };
    this.streamDefs = [
      { from: [0, 1.39, 0.44], part: 'gh', c1: [0, 1.1, 0.9], ci: 0 }, // lidar crown
      { from: [0.08, 1.3, 0.62], part: 'gh', c1: [0.1, 1.0, 1.0], ci: 1 }, // front camera L
      { from: [-0.08, 1.3, 0.62], part: 'gh', c1: [-0.1, 1.0, 1.0], ci: 2 }, // front camera R
      { from: [0, 0.48, 2.38], part: 'body', c1: [0, 0.4, 1.6], ci: 3 }, // front radar
      { from: [0.82, 0.52, 2.12], part: 'body', c1: [0.5, 0.4, 1.4], ci: 4 }, // corner radar L
      { from: [-0.82, 0.52, 2.12], part: 'body', c1: [-0.5, 0.4, 1.4], ci: 5 }, // corner radar R
      { from: [0.98, 1.0, 0.9], part: 'body', c1: [0.7, 0.55, 0.9], ci: 6 }, // side camera L
      { from: [-0.98, 1.0, 0.9], part: 'body', c1: [-0.7, 0.55, 0.9], ci: 7 }, // side camera R
    ];
    const NU = 160, NA = 6;
    const geo = new THREE.BufferGeometry();
    const aU = [], aAng = [], idx = [];
    for (let i = 0; i <= NU; i++) for (let j = 0; j <= NA; j++) { aU.push(i / NU); aAng.push((j / NA) * Math.PI * 2); }
    for (let i = 0; i < NU; i++) for (let j = 0; j < NA; j++) {
      const a = i * (NA + 1) + j, b = a + NA + 1;
      idx.push(a, b, a + 1, a + 1, b, b + 1);
    }
    geo.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(aU.length * 3), 3));
    geo.setAttribute('aU', new THREE.Float32BufferAttribute(aU, 1));
    geo.setAttribute('aAng', new THREE.Float32BufferAttribute(aAng, 1));
    geo.setIndex(idx);
    this.streams = this.streamDefs.map((d, i) => {
      const m = new THREE.ShaderMaterial({
        vertexShader: STREAM_VERT, fragmentShader: STREAM_FRAG,
        transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
        uniforms: {
          uP0: { value: new THREE.Vector3() }, uP1: { value: new THREE.Vector3() }, uP2: { value: new THREE.Vector3() }, uP3: { value: new THREE.Vector3() },
          uRad: { value: 0.0022 }, uTime: { value: 0 }, uReveal: { value: 0 }, uAlpha: { value: 1 }, uLen: { value: 2 },
          uSeed: { value: i * 1.37 }, uCol: { value: new THREE.Color(0.45, 0.8, 1.0) }, uCamPos: { value: new THREE.Vector3() },
        },
      });
      const mesh = new THREE.Mesh(geo, m);
      mesh.frustumCulled = false;
      this.car.root.add(mesh);
      const end = conn(d.ci);
      return { mesh, m, def: d, end };
    });
  }

  // ------------------------------------------------------------ car motion
  carState(t) {
    const x = laneX(t);
    const dt = 0.02;
    const vx = (laneX(t + dt) - laneX(t - dt)) / (2 * dt);
    const ax = (laneX(t + dt) - 2 * x + laneX(t - dt)) / (dt * dt);
    const yaw = Math.atan2(vx, SPEED);
    const bounce = 0.004 * Math.sin(t * 9.1) + 0.003 * Math.sin(t * 13.7 + 1.3);
    return { x, yaw, roll: -ax * 0.006, pitch: 0.002 * Math.sin(t * 5.3), bounce };
  }

  updateCarMatrix(t) {
    const s = this.carState(t);
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(s.pitch, s.yaw, s.roll, 'YXZ'));
    this.carMatrix.compose(new THREE.Vector3(s.x, s.bounce, 0), q, new THREE.Vector3(1, 1, 1));
    return this.carMatrix;
  }

  explodeAmount(t) {
    const open = smoother((t - 5.9) / 1.5);
    const close = smoother((t - (this.reassembleAt ?? REASSEMBLE)) / 0.9);
    return open * (1 - close);
  }

  // ------------------------------------------------------------ per frame
  update(t, pose, ctx) {
    const s = travel(t);
    const cam = this.camera;
    const camPos = pose.p;

    // Hero car.
    this.car.root.matrixAutoUpdate = false;
    this.car.root.matrix.copy(this.carMatrix);
    this.car.root.matrixWorldNeedsUpdate = true;
    const spin = s / CAR.wheelR;
    for (const { w } of this.car.wheels) w.rotation.x = spin;
    const e = this.explodeAmount(t);
    const gh = this.car.ghGroup;
    gh.position.set(0, 0.95 * e, -1.9 * e);
    gh.rotation.x = -0.22 * e;
    this.car.hoodGroup.position.set(0, 0.55 * e, 0.75 * e);
    this.car.hoodGroup.rotation.x = 0.4 * e;
    const le = smoother((t - 6.5) / 1.1) * (1 - smoother((t - (this.reassembleAt ?? REASSEMBLE) + 0.2) / 0.7));
    this.car.consoleLid.position.set(0, 0.5 + 0.34 * le, 0.2 - 0.6 * le);
    this.car.consoleLid.rotation.x = 0.55 * le;
    // Housing cover lifts in the car too (matches the board world).
    const coverLift = ctx.coverLift(t);
    this.car.housing.userData.cover.position.set(coverLift.x, coverLift.y, coverLift.z);
    this.car.housing.userData.cover.rotation.z = coverLift.rz;

    // Traffic.
    const cars = this.roadMat.uniforms.uCars.value;
    const cs = this.carState(t);
    cars[0].set(cs.x, 0, cs.yaw, 0);
    let ci = 1;
    const placeCar = (c, x, z, yaw, wheelSpin) => {
      c.root.position.set(x, 0, z);
      c.root.rotation.y = yaw;
      for (const { w } of c.wheels) w.rotation.x = wheelSpin;
    };
    this.traffic.forEach((tr, i) => {
      const z = tr.z0 + tr.dv * t;
      placeCar(tr.car, tr.x, z, 0, (s + tr.dv * t) / CAR.wheelR);
      tr.z = z;
      tr.car.root.visible = z > -120 && z < 420;
      if (ci < 10) cars[ci++].set(tr.x, z, 0, tr.car.root.visible ? 1 : -1);
    });
    this.oncoming.forEach((tr) => {
      const z = wrap(tr.z0 + tr.dv * t, -200, 640);
      placeCar(tr.car, tr.x, z, Math.PI, -s / CAR.wheelR);
      if (ci < 10) cars[ci++].set(tr.x, z, 0, 2);
    });
    // Pedestrian walks along the sidewalk.
    const pz = PED.z0 - s;
    this.ped.position.set(PED.x, 0, pz + 1.3 * t);
    this.ped.rotation.y = 0;
    const ph = t * 5.2;
    this.ped.userData.legs[0].rotation.x = Math.sin(ph) * 0.45;
    this.ped.userData.legs[1].rotation.x = -Math.sin(ph) * 0.45;
    this.ped.userData.arms[0].rotation.x = -Math.sin(ph) * 0.35;
    this.ped.userData.arms[1].rotation.x = Math.sin(ph) * 0.35;
    this.ped.visible = pz > -60 && pz < 200;

    // Street lights.
    const m4 = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const one = new THREE.Vector3(1, 1, 1);
    let ai = 0;
    const heads = [];
    this.lamps.forEach((l, i) => {
      const z = wrap(l.z0 - s, -120, 16 * 34);
      m4.compose(new THREE.Vector3(l.x, l.h / 2, z), q.identity(), new THREE.Vector3(1, l.h, 1));
      this.poleMesh.setMatrixAt(i, m4);
      for (const a of l.arms) {
        m4.compose(new THREE.Vector3(l.x + a / 2, l.h - 0.05, z), q, new THREE.Vector3(Math.abs(a), 1, 1));
        this.armMesh.setMatrixAt(ai, m4);
        const hp = new THREE.Vector3(l.x + a, l.h - 0.12, z);
        m4.compose(hp, q, one);
        this.headMesh.setMatrixAt(ai, m4);
        m4.makeTranslation(hp.x, hp.y - 0.25, hp.z);
        this.haloMesh.setMatrixAt(ai, m4);
        heads.push(hp);
        ai++;
      }
    });
    this.poleMesh.instanceMatrix.needsUpdate = true;
    this.armMesh.instanceMatrix.needsUpdate = true;
    this.headMesh.instanceMatrix.needsUpdate = true;
    this.haloMesh.instanceMatrix.needsUpdate = true;
    // Nearest lamp heads drive real point lights (moving reflections on the paint).
    heads.sort((a, b) => Math.abs(a.z - 1) + Math.abs(a.x) * 0.3 - (Math.abs(b.z - 1) + Math.abs(b.x) * 0.3));
    this.lampLights.forEach((L, i) => { L.position.copy(heads[i]); L.position.y -= 0.3; });

    // Buildings.
    this.buildings.forEach((b, i) => {
      const z = wrap(b.z0 - s, -260, this.bPeriod);
      m4.makeTranslation(b.x, 0, z);
      this.bMesh.setMatrixAt(i, m4);
    });
    this.bMesh.instanceMatrix.needsUpdate = true;

    // Road uniforms.
    const ru = this.roadMat.uniforms;
    ru.uTravel.value = s;
    ru.uCamPos.value.copy(camPos);
    ru.uTime.value = t;
    this.bMat.uniforms.uCamPos.value.copy(camPos);

    // Lidar.
    const lu = this.lidarMat.uniforms;
    lu.uTime.value = t;
    lu.uScroll.value = s - travel(T_SCAN);
    lu.uObj.value[0].set(TRAFFIC[0].x, 0, TRAFFIC[0].z0 + TRAFFIC[0].dv * t);
    lu.uObj.value[1].set(TRAFFIC[1].x, 0, TRAFFIC[1].z0 + TRAFFIC[1].dv * t);
    lu.uObj.value[2].set(PED.x, 0, PED.z0 - s + 1.3 * t);
    const la = ctx.fx.lidar;
    lu.uAlpha.value = la;
    lu.uBoost.value = 1 / Math.max(ctx.fx.exposure, 0.06);
    lu.uSize.value = 1.4 * ctx.pixelHeight / 1080 * 60;
    this.lidar.visible = la > 0.001;
    // In the dark hook only perception is visible; the lit world fades in.
    const world = ctx.fx.worldLight;
    this.roadMat.uniforms.uLampI.value = 17 * world;
    this.roadMat.uniforms.uHead.value = world;
    this.roadMat.uniforms.uAmb.value = 0.02 + 0.33 * world;
    this.bMat.uniforms.uWin.value = 1.1 * world;
    this.hemi.intensity = 0.25 * world;
    this.lampLights.forEach((L) => { L.intensity = 650 * world; });
    this.consoleLight.intensity = 0.9 * ctx.fx.consoleLight;
    this.headSpot.intensity = 900 * world;
    this.headMesh.material.color.setRGB(1.0, 0.9, 0.78).multiplyScalar(28 * world);
    this.haloMesh.material.uniforms.uI.value = 0.35 * world;
    for (const c of [this.car, ...this.traffic.map((x) => x.car), ...this.oncoming.map((x) => x.car)]) {
      c.frontM.color.setRGB(1, 0.97, 0.93).multiplyScalar((c === this.car ? 16 : 22) * Math.max(world, 0.02));
      c.rearM.color.setRGB(1, 0.04, 0.02).multiplyScalar(7 * Math.max(world, 0.02));
    }
    this.sky.visible = world > 0.01;

    // Detection boxes.
    const ba = ctx.fx.boxes;
    this.boxMat.opacity = ba;
    this.detBoxes.forEach((b) => {
      const d = b.userData;
      b.visible = ba > 0.001;
      if (d.target === 'ped') b.position.set(this.ped.position.x, 0.95, this.ped.position.z);
      else { const tr = this.traffic[d.target === 'traffic0' ? 0 : 1]; b.position.set(tr.x, 0.78, tr.z); }
    });

    // Data streams (in car frame).
    const camCar = this._tmp.copy(camPos).applyMatrix4(new THREE.Matrix4().copy(this.carMatrix).invert());
    const rev = ctx.fx.streams;
    this.streams.forEach((st, i) => {
      const d = st.def;
      const u = st.m.uniforms;
      const p0 = new THREE.Vector3(...d.from);
      const c1 = new THREE.Vector3(...d.c1);
      if (d.part === 'gh') { p0.applyMatrix4(gh.matrix.compose(gh.position, gh.quaternion, gh.scale)); c1.lerp(p0, 0.0); }
      u.uP0.value.copy(p0);
      u.uP1.value.copy(c1);
      u.uP2.value.copy(st.end).add(new THREE.Vector3(0, 0.02, 0.28));
      u.uP3.value.copy(st.end);
      u.uLen.value = p0.distanceTo(st.end) * 1.3;
      const local = clamp((rev - i * 0.035) / 0.72);
      u.uReveal.value = smooth(local);
      u.uAlpha.value = ctx.fx.streamAlpha;
      u.uTime.value = t;
      u.uCamPos.value.copy(camCar);
      st.mesh.visible = rev > 0.001 && ctx.fx.streamAlpha > 0.001;
      // Streams get thinner when the camera is close so they stay fine lines.
      const dist = camCar.distanceTo(p0.clone().lerp(st.end, 0.7));
      u.uRad.value = clamp(dist * 0.0022, 0.0012, 0.004);
    });

    // Planned-trajectory ribbon for the final decision.
    const ra = ctx.fx.ribbon;
    this.ribbon.visible = ra > 0.001;
    if (ra > 0.001) {
      const N = this.ribbonN;
      const pos = this.ribbon.geometry.attributes.position;
      for (let i = 0; i < N; i++) {
        const zf = 2.8 + (i / (N - 1)) * 46;
        const tf = t + zf / SPEED;
        const x = laneX(tf);
        const x2 = laneX(tf + 0.05);
        const yawf = Math.atan2((x2 - x) / 0.05, SPEED);
        const w = 0.95;
        const nx = Math.cos(yawf) * w, nz = -Math.sin(yawf) * w;
        pos.setXYZ(i * 2, x - nx, 0.025, zf - nz);
        pos.setXYZ(i * 2 + 1, x + nx, 0.025, zf + nz);
      }
      pos.needsUpdate = true;
      this.ribbonMat.uniforms.uTime.value = t;
      this.ribbonMat.uniforms.uAlpha.value = ra;
    }

    this.scene.fog = null;
  }

  // Planar reflection for the wet road.
  preRender(renderer, camera, size) {
    const w = Math.max(64, Math.floor(size.x * 0.5)), h = Math.max(36, Math.floor(size.y * 0.5));
    if (this.reflRT.width !== w || this.reflRT.height !== h) this.reflRT.setSize(w, h);
    const normal = new THREE.Vector3(0, 1, 0);
    const reflPos = new THREE.Vector3(0, 0, 0);
    const camPos = new THREE.Vector3().setFromMatrixPosition(camera.matrixWorld);
    if (camPos.y <= 0.001) { this.roadMat.uniforms.uReflOn.value = 0; return; }
    this.roadMat.uniforms.uReflOn.value = 1;
    const rot = new THREE.Matrix4().extractRotation(camera.matrixWorld);
    const view = new THREE.Vector3(camPos.x, -camPos.y, camPos.z);
    const look = new THREE.Vector3(0, 0, -1).applyMatrix4(rot).add(camPos);
    const target = new THREE.Vector3(look.x, -look.y, look.z);
    const vc = this.mirrorCam;
    vc.position.copy(view);
    vc.up.set(0, 1, 0).applyMatrix4(rot).reflect(normal);
    vc.lookAt(target);
    vc.far = camera.far; vc.near = camera.near;
    vc.updateMatrixWorld();
    vc.projectionMatrix.copy(camera.projectionMatrix);
    this.texMat.set(0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 0.5, 0.5, 0, 0, 0, 1);
    this.texMat.multiply(vc.projectionMatrix).multiply(vc.matrixWorldInverse);
    // Oblique near plane at the road surface.
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, reflPos).applyMatrix4(vc.matrixWorldInverse);
    const clip = new THREE.Vector4(plane.normal.x, plane.normal.y, plane.normal.z, plane.constant);
    const pm = vc.projectionMatrix;
    const qv = new THREE.Vector4(
      (Math.sign(clip.x) + pm.elements[8]) / pm.elements[0],
      (Math.sign(clip.y) + pm.elements[9]) / pm.elements[5],
      -1, (1 + pm.elements[10]) / pm.elements[14],
    );
    clip.multiplyScalar(2 / clip.dot(qv));
    pm.elements[2] = clip.x; pm.elements[6] = clip.y; pm.elements[10] = clip.z + 1 - 0.003; pm.elements[14] = clip.w;
    this.road.visible = false;
    const lidarVis = this.lidar.visible;
    this.lidar.visible = false;
    const rib = this.ribbon.visible;
    this.ribbon.visible = false;
    renderer.setRenderTarget(this.reflRT);
    renderer.clear();
    renderer.render(this.scene, vc);
    this.road.visible = true;
    this.lidar.visible = lidarVis;
    this.ribbon.visible = rib;
  }
}
