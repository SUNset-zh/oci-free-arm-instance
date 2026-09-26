import * as THREE from 'three';
import { rng } from './util.js';

// Procedural environment maps (prefiltered with PMREM) for believable
// reflections on paint, metal and silicon. No image assets are used.

function gradientSphere(top, mid, bottom, power = 1) {
  const m = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    uniforms: { top: { value: new THREE.Color(top) }, mid: { value: new THREE.Color(mid) }, bottom: { value: new THREE.Color(bottom) }, power: { value: power } },
    vertexShader: 'varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} ',
    fragmentShader: `uniform vec3 top; uniform vec3 mid; uniform vec3 bottom; uniform float power; varying vec3 vP;
      void main(){ float y = vP.y; vec3 c = y > 0.0 ? mix(mid, top, pow(y, power)) : mix(mid, bottom, pow(-y, 0.6)); gl_FragColor = vec4(c,1.0);} `,
  });
  return new THREE.Mesh(new THREE.SphereGeometry(50, 48, 24), m);
}

function panel(scene, w, h, color, intensity, pos, look) {
  const m = new THREE.Mesh(
    new THREE.PlaneGeometry(w, h),
    new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(intensity), side: THREE.DoubleSide }),
  );
  m.position.set(...pos);
  m.lookAt(new THREE.Vector3(...look));
  scene.add(m);
  return m;
}

export function makeEnvironments(renderer) {
  const pmrem = new THREE.PMREMGenerator(renderer);
  const out = {};

  // Studio: black room, big soft key, two strip rims, a warm kicker.
  {
    const s = new THREE.Scene();
    s.add(gradientSphere(0x0b0c0f, 0x050506, 0x020202));
    panel(s, 30, 18, 0xffffff, 2.2, [0, 30, 8], [0, 0, 0]);
    panel(s, 4, 40, 0xdfe8ff, 2.6, [-38, 8, -10], [0, 0, 0]);
    panel(s, 4, 40, 0xdfe8ff, 1.6, [38, 6, -14], [0, 0, 0]);
    panel(s, 30, 3, 0xffd6a8, 1.1, [0, 4, 40], [0, 0, 0]);
    panel(s, 60, 2, 0xffffff, 0.8, [0, -6, -40], [0, 0, 0]);
    out.studio = pmrem.fromScene(s, 0.02).texture;
  }

  // Night city: deep blue-black sky, sodium/LED specks on the horizon, overhead lamps.
  {
    const s = new THREE.Scene();
    s.add(gradientSphere(0x05070c, 0x0f1622, 0x020203, 0.5));
    const r = rng(7);
    const geo = new THREE.PlaneGeometry(1, 1);
    for (let i = 0; i < 260; i++) {
      const a = r() * Math.PI * 2;
      const y = r() * r() * 9 - 0.5;
      const d = 44;
      const warm = r() < 0.55;
      const c = new THREE.Color(warm ? 0xffc890 : 0xcfe0ff).multiplyScalar(r.range(0.6, 3.5));
      const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: c, side: THREE.DoubleSide }));
      m.position.set(Math.cos(a) * d, y, Math.sin(a) * d);
      m.scale.set(r.range(0.3, 1.6), r.range(0.3, 1.2), 1);
      m.lookAt(0, 0, 0);
      s.add(m);
    }
    for (let i = -3; i <= 3; i++) panel(s, 2.5, 1.2, 0xfff2e0, 6, [i * 9, 22, 10], [i * 9, 0, 10]);
    panel(s, 90, 8, 0x1a2436, 1.0, [0, 3, -45], [0, 0, 0]);
    out.night = pmrem.fromScene(s, 0.01).texture;
  }

  // Lab: almost black, a couple of thin highlight strips for crisp speculars.
  {
    const s = new THREE.Scene();
    s.add(gradientSphere(0x07080b, 0x030304, 0x010101));
    panel(s, 60, 5, 0xffffff, 1.6, [0, 26, -12], [0, 0, 0]);
    panel(s, 3, 50, 0xcfe0ff, 1.4, [-35, 10, 8], [0, 0, 0]);
    panel(s, 3, 50, 0xffe0c0, 0.7, [35, 10, 8], [0, 0, 0]);
    out.lab = pmrem.fromScene(s, 0.03).texture;
  }
  pmrem.dispose();
  return out;
}

// Canvas-backed texture helper.
export function canvasTexture(w, h, draw, { srgb = true, repeat = false, aniso = 8, mipmaps = true } = {}) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d');
  draw(g, w, h);
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  if (repeat) t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = aniso;
  t.generateMipmaps = mipmaps;
  t.minFilter = mipmaps ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter;
  t.needsUpdate = true;
  return t;
}
