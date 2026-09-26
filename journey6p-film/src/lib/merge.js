import * as THREE from 'three';

// Collapse every plain Mesh under `root` into one mesh per material (baking
// transforms relative to root). Cuts draw calls for static sub-assemblies.
// InstancedMesh / Points / Lines and objects marked userData.keep are left alone.
export function collapseByMaterial(root) {
  root.updateMatrixWorld(true);
  const inv = new THREE.Matrix4().copy(root.matrixWorld).invert();
  const buckets = new Map();
  const remove = [];
  root.traverse((o) => {
    if (o === root || !o.isMesh || o.isInstancedMesh || o.userData.keep || Array.isArray(o.material)) return;
    const m = new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld);
    let g = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry.clone();
    g.applyMatrix4(m);
    if (!g.attributes.normal) g.computeVertexNormals();
    if (!g.attributes.uv) g.setAttribute('uv', new THREE.Float32BufferAttribute(new Float32Array(g.attributes.position.count * 2), 2));
    for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'uv'].includes(k)) g.deleteAttribute(k);
    if (!buckets.has(o.material)) buckets.set(o.material, { geos: [], cast: false, recv: false });
    const b = buckets.get(o.material);
    b.geos.push(g);
    b.cast ||= o.castShadow; b.recv ||= o.receiveShadow;
    remove.push(o);
  });
  for (const o of remove) o.parent.remove(o);
  // Drop now-empty groups.
  const empties = [];
  root.traverse((o) => { if (o !== root && o.type === 'Group' && o.children.length === 0) empties.push(o); });
  for (const e of empties) e.parent?.remove(e);
  for (const [mat, b] of buckets) {
    let n = 0;
    for (const g of b.geos) n += g.attributes.position.count;
    const pos = new Float32Array(n * 3), nrm = new Float32Array(n * 3), uv = new Float32Array(n * 2);
    let o = 0;
    for (const g of b.geos) {
      pos.set(g.attributes.position.array, o * 3);
      nrm.set(g.attributes.normal.array, o * 3);
      uv.set(g.attributes.uv.array, o * 2);
      o += g.attributes.position.count;
      g.dispose();
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('normal', new THREE.BufferAttribute(nrm, 3));
    geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    geo.computeBoundingSphere();
    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = b.cast; mesh.receiveShadow = b.recv;
    root.add(mesh);
  }
  return root;
}

// Put a subtree on render layer 1 (seen by the main camera, skipped by mirrors).
export function detailLayer(root) {
  root.traverse((o) => o.layers.set(1));
  return root;
}
