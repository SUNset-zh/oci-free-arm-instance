import * as THREE from 'three';

// Cinematic post pipeline.
//   world A (+ world B during a scale hand-off) -> composite (+ signed CoC)
//   -> half-res bokeh gather -> dual-filter bloom -> final grade
// Final grade: DOF mix, radial zoom blur, bloom, ACES, vignette, grain, dither.

const FS_VERT = /* glsl */`
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

const COMPOSITE = /* glsl */`
precision highp float;
varying vec2 vUv;
uniform sampler2D tA; uniform sampler2D dA;
uniform sampler2D tB; uniform sampler2D dB;
uniform float blend; uniform float useB;
uniform vec4 camA; // near, far, focus, aperture
uniform vec4 camB;
uniform float aspect;
float linZ(float d, vec2 nf) {
  float z = d * 2.0 - 1.0;
  return 2.0 * nf.x * nf.y / (nf.y + nf.x - z * (nf.y - nf.x));
}
float coc(float d, vec4 c) {
  float z = linZ(d, c.xy);
  return clamp(c.w * (z - c.z) / max(z, 1e-6), -1.0, 1.0);
}
void main() {
  vec4 a = texture2D(tA, vUv);
  float ca = coc(texture2D(dA, vUv).x, camA);
  if (useB > 0.5) {
    vec4 b = texture2D(tB, vUv);
    float cb = coc(texture2D(dB, vUv).x, camB);
    a.rgb = mix(a.rgb, b.rgb, blend);
    ca = mix(ca, cb, blend);
  }
  gl_FragColor = vec4(max(a.rgb, 0.0), ca);
}
`;

// Single-pass scatter-as-gather bokeh (after Kennedy / Gustafsson), Vogel disk.
const DOF = /* glsl */`
precision highp float;
varying vec2 vUv;
uniform sampler2D tColor;
uniform vec2 texel;
uniform float maxRadius; // pixels at this resolution
uniform int taps;
const float GOLDEN = 2.39996323;
void main() {
  vec4 c = texture2D(tColor, vUv);
  float centerCoc = c.a;
  float centerSize = abs(centerCoc) * maxRadius;
  vec3 acc = c.rgb; float tot = 1.0;
  // Radius of the gather disk: sized by the largest plausible CoC around here.
  float R = maxRadius;
  for (int i = 1; i < 64; i++) {
    if (i >= taps) break;
    float fi = float(i);
    float r = sqrt(fi / float(taps)) * R;
    float ang = fi * GOLDEN;
    vec2 uv = vUv + vec2(cos(ang), sin(ang)) * texel * r;
    vec4 s = texture2D(tColor, uv);
    float sSize = abs(s.a) * maxRadius;
    if (s.a > centerCoc) sSize = clamp(sSize, 0.0, centerSize * 2.0);
    float m = smoothstep(r - 1.5, r + 0.5, sSize);
    acc += mix(acc / tot, s.rgb, m);
    tot += 1.0;
  }
  gl_FragColor = vec4(acc / tot, centerCoc);
}
`;

const DOFMIX = /* glsl */`
precision highp float;
varying vec2 vUv;
uniform sampler2D tSharp; uniform sampler2D tBlur;
uniform float maxRadius;
void main() {
  vec4 s = texture2D(tSharp, vUv);
  vec4 b = texture2D(tBlur, vUv);
  float px = max(abs(s.a), abs(b.a) * 0.9) * maxRadius;
  float k = smoothstep(0.35, 1.6, px);
  gl_FragColor = vec4(mix(s.rgb, b.rgb, k), 1.0);
}
`;

const PREFILTER = /* glsl */`
precision highp float;
varying vec2 vUv;
uniform sampler2D tColor; uniform vec2 texel;
uniform float threshold; uniform float knee;
vec3 q(vec2 uv) { return texture2D(tColor, uv).rgb; }
void main() {
  vec3 c = q(vUv) * 0.5 + (q(vUv + texel * vec2(1.0, 1.0)) + q(vUv + texel * vec2(-1.0, 1.0)) +
           q(vUv + texel * vec2(1.0, -1.0)) + q(vUv + texel * vec2(-1.0, -1.0))) * 0.125;
  c = min(c, vec3(60.0));
  float br = max(c.r, max(c.g, c.b));
  float rq = clamp(br - threshold + knee, 0.0, 2.0 * knee);
  rq = rq * rq / (4.0 * knee + 1e-5);
  float w = max(rq, br - threshold) / max(br, 1e-5);
  gl_FragColor = vec4(c * w, 1.0);
}
`;

const DOWN = /* glsl */`
precision highp float;
varying vec2 vUv;
uniform sampler2D tColor; uniform vec2 texel;
void main() {
  vec3 s = texture2D(tColor, vUv).rgb * 4.0;
  s += texture2D(tColor, vUv - texel).rgb;
  s += texture2D(tColor, vUv + texel).rgb;
  s += texture2D(tColor, vUv + vec2(texel.x, -texel.y)).rgb;
  s += texture2D(tColor, vUv - vec2(texel.x, -texel.y)).rgb;
  gl_FragColor = vec4(s / 8.0, 1.0);
}
`;

const UP = /* glsl */`
precision highp float;
varying vec2 vUv;
uniform sampler2D tColor; uniform sampler2D tPrev; uniform vec2 texel; uniform float w;
void main() {
  vec3 s = texture2D(tColor, vUv + vec2(-texel.x * 2.0, 0.0)).rgb;
  s += texture2D(tColor, vUv + vec2(-texel.x, texel.y)).rgb * 2.0;
  s += texture2D(tColor, vUv + vec2(0.0, texel.y * 2.0)).rgb;
  s += texture2D(tColor, vUv + vec2(texel.x, texel.y)).rgb * 2.0;
  s += texture2D(tColor, vUv + vec2(texel.x * 2.0, 0.0)).rgb;
  s += texture2D(tColor, vUv + vec2(texel.x, -texel.y)).rgb * 2.0;
  s += texture2D(tColor, vUv + vec2(0.0, -texel.y * 2.0)).rgb;
  s += texture2D(tColor, vUv + vec2(-texel.x, -texel.y)).rgb * 2.0;
  gl_FragColor = vec4(s / 12.0 + texture2D(tPrev, vUv).rgb * w, 1.0);
}
`;

const FINAL = /* glsl */`
precision highp float;
varying vec2 vUv;
uniform sampler2D tColor; uniform sampler2D tBloom;
uniform float bloom; uniform float exposure; uniform float zoomBlur; uniform vec2 zoomCenter;
uniform float vignette; uniform float grain; uniform float time; uniform float fade;
uniform float ca; uniform float aspect; uniform vec3 lift; uniform vec3 gain; uniform float sat;
uniform float letterbox;

vec3 RRTAndODTFit(vec3 v) {
  vec3 a = v * (v + 0.0245786) - 0.000090537;
  vec3 b = v * (0.983729 * v + 0.4329510) + 0.238081;
  return a / b;
}
vec3 aces(vec3 c) {
  const mat3 IN = mat3(0.59719, 0.07600, 0.02840, 0.35458, 0.90834, 0.13383, 0.04823, 0.01566, 0.83777);
  const mat3 OUT = mat3(1.60475, -0.10208, -0.00327, -0.53108, 1.10813, -0.07276, -0.07367, -0.00605, 1.07602);
  c = IN * c; c = RRTAndODTFit(c); c = OUT * c;
  return clamp(c, 0.0, 1.0);
}
float h12(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
vec3 srgb(vec3 c) {
  return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}
vec3 sampleScene(vec2 uv) {
  vec2 d = uv - 0.5;
  vec3 c;
  c.g = texture2D(tColor, uv).g;
  c.r = texture2D(tColor, 0.5 + d * (1.0 + ca)).r;
  c.b = texture2D(tColor, 0.5 + d * (1.0 - ca)).b;
  return c;
}
void main() {
  vec2 uv = vUv;
  vec3 col;
  if (zoomBlur > 0.0005) {
    vec3 acc = vec3(0.0); float tw = 0.0;
    float j = h12(gl_FragCoord.xy + time) ;
    for (int i = 0; i < 14; i++) {
      float f = (float(i) + j) / 14.0;
      vec2 suv = zoomCenter + (uv - zoomCenter) * (1.0 - zoomBlur * f);
      float w = 1.0 - f * 0.5;
      acc += texture2D(tColor, suv).rgb * w; tw += w;
    }
    col = acc / tw;
  } else {
    col = sampleScene(uv);
  }
  col += texture2D(tBloom, uv).rgb * bloom;
  col *= exposure;
  // Grade in linear: gentle lift / gain, saturation.
  float l = dot(col, vec3(0.2126, 0.7152, 0.0722));
  col = mix(vec3(l), col, sat);
  col = col * gain + lift * (1.0 - clamp(l * 4.0, 0.0, 1.0)) * 0.02;
  col = aces(col);
  vec2 d = (uv - 0.5) * vec2(aspect, 1.0);
  float v = 1.0 - vignette * smoothstep(0.35, 1.05, length(d));
  col *= v;
  col = srgb(col);
  float g = h12(gl_FragCoord.xy * 0.73 + fract(time * 7.13) * 91.0) - 0.5;
  col += g * grain;
  col *= fade;
  float lb = step(letterbox, uv.y) * step(uv.y, 1.0 - letterbox);
  col *= lb;
  col += (h12(gl_FragCoord.xy + 0.5) - 0.5) / 255.0; // dither against banding
  gl_FragColor = vec4(col, 1.0);
}
`;

function rt(w, h, opts = {}) {
  const r = new THREE.WebGLRenderTarget(Math.max(1, w), Math.max(1, h), {
    type: THREE.HalfFloatType,
    format: THREE.RGBAFormat,
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    depthBuffer: !!opts.depth,
    samples: opts.samples || 0,
  });
  if (opts.depth) {
    r.depthTexture = new THREE.DepthTexture(Math.max(1, w), Math.max(1, h));
    r.depthTexture.type = THREE.UnsignedIntType;
  }
  r.texture.generateMipmaps = false;
  return r;
}

export class Post {
  constructor(renderer) {
    this.renderer = renderer;
    this.scene = new THREE.Scene();
    this.cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2));
    this.quad.frustumCulled = false;
    this.scene.add(this.quad);
    const mk = (fs, uniforms) => new THREE.ShaderMaterial({
      vertexShader: FS_VERT, fragmentShader: fs, uniforms, depthTest: false, depthWrite: false,
    });
    this.mComp = mk(COMPOSITE, {
      tA: { value: null }, dA: { value: null }, tB: { value: null }, dB: { value: null },
      blend: { value: 0 }, useB: { value: 0 }, camA: { value: new THREE.Vector4() },
      camB: { value: new THREE.Vector4() }, aspect: { value: 1 },
    });
    this.mDof = mk(DOF, {
      tColor: { value: null }, texel: { value: new THREE.Vector2() }, maxRadius: { value: 12 },
      taps: { value: 40 },
    });
    this.mDofMix = mk(DOFMIX, { tSharp: { value: null }, tBlur: { value: null }, maxRadius: { value: 12 } });
    this.mPre = mk(PREFILTER, {
      tColor: { value: null }, texel: { value: new THREE.Vector2() }, threshold: { value: 1.0 }, knee: { value: 0.5 },
    });
    this.mDown = mk(DOWN, { tColor: { value: null }, texel: { value: new THREE.Vector2() } });
    this.mUp = mk(UP, {
      tColor: { value: null }, tPrev: { value: null }, texel: { value: new THREE.Vector2() }, w: { value: 1 },
    });
    this.mFinal = mk(FINAL, {
      tColor: { value: null }, tBloom: { value: null }, bloom: { value: 0.6 }, exposure: { value: 1 },
      zoomBlur: { value: 0 }, zoomCenter: { value: new THREE.Vector2(0.5, 0.5) }, vignette: { value: 0.35 },
      grain: { value: 0.035 }, time: { value: 0 }, fade: { value: 1 }, ca: { value: 0.0015 },
      aspect: { value: 16 / 9 }, lift: { value: new THREE.Vector3(0.0, 0.02, 0.05) },
      gain: { value: new THREE.Vector3(1, 1, 1) }, sat: { value: 1 }, letterbox: { value: 0 },
    });
    this.samples = 4;
    this.dofTaps = 40;
    this.bloomLevels = 6;
    this.w = 0; this.h = 0;
  }

  setSize(w, h, samples = this.samples) {
    if (w === this.w && h === this.h && samples === this.samples && this.rtA) return;
    this.w = w; this.h = h; this.samples = samples;
    for (const r of this._all || []) r.dispose();
    this.rtA = rt(w, h, { depth: true, samples });
    this.rtB = rt(w, h, { depth: true, samples });
    this.rtComp = rt(w, h);
    this.rtMix = rt(w, h);
    const hw = Math.ceil(w / 2), hh = Math.ceil(h / 2);
    this.rtDof = rt(hw, hh);
    this.bloomDown = [];
    this.bloomUp = [];
    let bw = hw, bh = hh;
    for (let i = 0; i < this.bloomLevels; i++) {
      this.bloomDown.push(rt(bw, bh));
      this.bloomUp.push(rt(bw, bh));
      bw = Math.max(1, Math.ceil(bw / 2)); bh = Math.max(1, Math.ceil(bh / 2));
    }
    this._all = [this.rtA, this.rtB, this.rtComp, this.rtMix, this.rtDof, ...this.bloomDown, ...this.bloomUp];
  }

  pass(mat, target) {
    this.quad.material = mat;
    this.renderer.setRenderTarget(target);
    this.renderer.render(this.scene, this.cam);
  }

  // layers: [{scene, camera, pose(focus, ap)}] (1 or 2), blend = weight of layer B.
  render(layers, blend, fx, time) {
    const r = this.renderer;
    const A = layers[0], B = layers[1];
    r.setRenderTarget(this.rtA);
    r.clear();
    r.render(A.scene, A.camera);
    if (B) {
      r.setRenderTarget(this.rtB);
      r.clear();
      r.render(B.scene, B.camera);
    }
    const u = this.mComp.uniforms;
    u.tA.value = this.rtA.texture; u.dA.value = this.rtA.depthTexture;
    u.camA.value.set(A.camera.near, A.camera.far, A.focus, A.ap);
    u.useB.value = B ? 1 : 0;
    if (B) {
      u.tB.value = this.rtB.texture; u.dB.value = this.rtB.depthTexture;
      u.camB.value.set(B.camera.near, B.camera.far, B.focus, B.ap);
    }
    u.blend.value = blend;
    this.pass(this.mComp, this.rtComp);

    // Depth of field (half res gather).
    const hw = this.rtDof.width, hh = this.rtDof.height;
    const maxR = fx.dofMax * hh; // radius in half-res pixels
    const dofOn = Math.max(A.ap, B ? B.ap : 0) > 0.0005;
    let src = this.rtComp;
    if (dofOn) {
      const d = this.mDof.uniforms;
      d.tColor.value = this.rtComp.texture; d.texel.value.set(1 / hw, 1 / hh);
      d.maxRadius.value = maxR; d.taps.value = this.dofTaps;
      this.pass(this.mDof, this.rtDof);
      const m = this.mDofMix.uniforms;
      m.tSharp.value = this.rtComp.texture; m.tBlur.value = this.rtDof.texture; m.maxRadius.value = maxR * 2;
      this.pass(this.mDofMix, this.rtMix);
      src = this.rtMix;
    }

    // Bloom.
    const p = this.mPre.uniforms;
    p.tColor.value = src.texture; p.texel.value.set(1 / this.w, 1 / this.h);
    p.threshold.value = fx.bloomThreshold; p.knee.value = fx.bloomKnee;
    this.pass(this.mPre, this.bloomDown[0]);
    for (let i = 1; i < this.bloomLevels; i++) {
      const s = this.bloomDown[i - 1];
      this.mDown.uniforms.tColor.value = s.texture;
      this.mDown.uniforms.texel.value.set(1 / s.width, 1 / s.height);
      this.pass(this.mDown, this.bloomDown[i]);
    }
    let prev = this.bloomDown[this.bloomLevels - 1];
    for (let i = this.bloomLevels - 2; i >= 0; i--) {
      const uu = this.mUp.uniforms;
      uu.tColor.value = prev.texture;
      uu.texel.value.set(1 / prev.width, 1 / prev.height);
      uu.tPrev.value = this.bloomDown[i].texture;
      uu.w.value = 1;
      this.pass(this.mUp, this.bloomUp[i]);
      prev = this.bloomUp[i];
    }

    const f = this.mFinal.uniforms;
    f.tColor.value = src.texture; f.tBloom.value = prev.texture;
    f.bloom.value = fx.bloom / this.bloomLevels;
    f.exposure.value = fx.exposure; f.zoomBlur.value = fx.zoomBlur;
    f.vignette.value = fx.vignette; f.grain.value = fx.grain; f.time.value = time;
    f.fade.value = fx.fade; f.ca.value = fx.ca; f.aspect.value = this.w / this.h;
    f.sat.value = fx.sat; f.letterbox.value = fx.letterbox || 0;
    f.gain.value.set(...(fx.gain || [1, 1, 1]));
    this.pass(this.mFinal, null);
  }
}
