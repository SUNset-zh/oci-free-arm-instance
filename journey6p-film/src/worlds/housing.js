import * as THREE from 'three';
import { RoundedBoxGeometry } from '../lib/rounded.js';

// The intelligent-driving computer enclosure, in millimetres (board frame).
// PCB top surface is y = 0; the PCB spans x ∈ [-115, 115], z ∈ [-80, 80].
// +x faces the front of the car: that is where the sensor cables plug in.

export const HOUSING = {
  pcbX: 115, pcbZ: 80,
  outerX: 126, outerZ: 91,
  baseBottom: -13, wallTop: 5,
  coverY0: 17, coverY1: 21, finTop: 46,
  finPitch: 5, finT: 1.6,
};

export function fins() {
  const list = [];
  const n = Math.floor((HOUSING.outerZ * 2 - 6) / HOUSING.finPitch);
  const z0 = -((n - 1) * HOUSING.finPitch) / 2;
  for (let i = 0; i < n; i++) list.push(z0 + i * HOUSING.finPitch);
  return list;
}

export function buildHousing(mats, { lowDetail = false } = {}) {
  const H = HOUSING;
  const root = new THREE.Group();
  root.name = 'housing';

  // --- base tray (open top) ---------------------------------------------
  const base = new THREE.Group();
  const floor = new THREE.Mesh(new RoundedBoxGeometry(H.outerX * 2, 4, H.outerZ * 2, 3, 3), mats.alu);
  floor.position.y = H.baseBottom + 2;
  base.add(floor);
  const wallH = H.wallTop - H.baseBottom;
  const wallGeoX = new RoundedBoxGeometry(H.outerX * 2, wallH, 4, 2, 1.5);
  const wallGeoZ = new RoundedBoxGeometry(4, wallH, H.outerZ * 2, 2, 1.5);
  for (const s of [-1, 1]) {
    const wx = new THREE.Mesh(wallGeoX, mats.alu);
    wx.position.set(0, H.baseBottom + wallH / 2, s * (H.outerZ - 2));
    base.add(wx);
    const wz = new THREE.Mesh(wallGeoZ, mats.alu);
    wz.position.set(s * (H.outerX - 2), H.baseBottom + wallH / 2, 0);
    base.add(wz);
  }
  // Mounting flanges.
  const flangeGeo = new RoundedBoxGeometry(28, 3, 16, 2, 1.2);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const f = new THREE.Mesh(flangeGeo, mats.alu);
    f.position.set(sx * (H.outerX - 30), H.baseBottom + 1.5, sz * (H.outerZ + 7));
    base.add(f);
  }
  root.add(base);

  // --- connectors on the +x wall -----------------------------------------
  const conn = new THREE.Group();
  const bodyGeo = new RoundedBoxGeometry(16, 11, 12, 2, 1.6);
  const ringGeo = new THREE.CylinderGeometry(3.2, 3.2, 3, 20, 1, true);
  const keyColors = [0x3a3f8f, 0x7a5a2a, 0x2b6b5a, 0x6b2b3a, 0x2a2a2a, 0x445566, 0x3a3f8f, 0x7a5a2a];
  const connZ = [];
  for (let i = 0; i < 8; i++) connZ.push(-66 + i * 16.5);
  connZ.forEach((z, i) => {
    const b = new THREE.Mesh(bodyGeo, mats.plasticDark);
    b.position.set(H.outerX + 5, 0.5, z);
    conn.add(b);
    const r = new THREE.Mesh(ringGeo, new THREE.MeshStandardMaterial({ color: keyColors[i], roughness: 0.55, metalness: 0.1 }));
    r.rotation.z = Math.PI / 2;
    r.position.set(H.outerX + 13.2, 0.5, z);
    conn.add(r);
  });
  // Big main (power + ethernet) connector.
  const main = new THREE.Mesh(new RoundedBoxGeometry(14, 14, 40, 2, 2), mats.plasticDark);
  main.position.set(H.outerX + 4, 1, 68);
  conn.add(main);
  root.add(conn);
  root.userData.connZ = connZ;

  // --- cover with heat-sink fins -------------------------------------------
  const cover = new THREE.Group();
  const plate = new THREE.Mesh(new RoundedBoxGeometry(H.outerX * 2, H.coverY1 - H.coverY0, H.outerZ * 2, 3, 2.5), mats.aluDark);
  plate.position.y = (H.coverY0 + H.coverY1) / 2;
  cover.add(plate);
  // Skirt so the cover reads as a lid.
  const skirtGeoX = new THREE.BoxGeometry(H.outerX * 2, 12, 3);
  const skirtGeoZ = new THREE.BoxGeometry(3, 12, H.outerZ * 2);
  for (const s of [-1, 1]) {
    const a = new THREE.Mesh(skirtGeoX, mats.aluDark); a.position.set(0, H.coverY0 - 6, s * (H.outerZ - 1.5)); cover.add(a);
    const b = new THREE.Mesh(skirtGeoZ, mats.aluDark); b.position.set(s * (H.outerX - 1.5), H.coverY0 - 6, 0); cover.add(b);
  }
  const finH = H.finTop - H.coverY1;
  const finGeo = lowDetail
    ? new THREE.BoxGeometry(H.outerX * 2 - 8, finH, H.finT)
    : new RoundedBoxGeometry(H.outerX * 2 - 8, finH, H.finT, 1, 0.6);
  const zs = fins();
  const finMesh = new THREE.InstancedMesh(finGeo, mats.fin, zs.length);
  const m = new THREE.Matrix4();
  zs.forEach((z, i) => { m.makeTranslation(0, H.coverY1 + finH / 2, z); finMesh.setMatrixAt(i, m); });
  finMesh.instanceMatrix.needsUpdate = true;
  cover.add(finMesh);
  // Pedestal under the cover that meets the SoC lid (thermal path).
  const ped = new THREE.Mesh(new THREE.BoxGeometry(44, H.coverY0 - 4.3, 44), mats.aluDark);
  ped.position.set(0, (H.coverY0 + 4.3) / 2, 0);
  cover.add(ped);
  root.add(cover);

  root.userData.base = base;
  root.userData.cover = cover;
  root.userData.conn = conn;
  return root;
}

export function housingMaterials(env) {
  return {
    alu: new THREE.MeshStandardMaterial({ color: 0x8a8d92, metalness: 0.9, roughness: 0.42, envMap: env, envMapIntensity: 1 }),
    aluDark: new THREE.MeshStandardMaterial({ color: 0x3a3c40, metalness: 0.85, roughness: 0.38, envMap: env, envMapIntensity: 1 }),
    fin: new THREE.MeshStandardMaterial({ color: 0x4a4d52, metalness: 0.92, roughness: 0.3, envMap: env, envMapIntensity: 1.2 }),
    plasticDark: new THREE.MeshStandardMaterial({ color: 0x151618, metalness: 0.0, roughness: 0.55, envMap: env, envMapIntensity: 0.6 }),
  };
}
