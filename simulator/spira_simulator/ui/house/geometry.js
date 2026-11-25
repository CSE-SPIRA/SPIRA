import * as THREE from "./vendor/three.module.min.js";

const roundGeometry = new Map();

export function roundedGeometry(w, h, d, r) {
  const key = [w, h, d, r].join(",");
  if (!roundGeometry.has(key)) {
    const bevel = Math.min(r, w * .22, h * .22, d * .22);
    const x = w / 2 - bevel, y = h / 2 - bevel;
    const shape = new THREE.Shape();
    shape.moveTo(-x, -y); shape.lineTo(x, -y); shape.lineTo(x, y); shape.lineTo(-x, y); shape.closePath();
    const geometry = new THREE.ExtrudeGeometry(shape, {
      depth: d - 2 * bevel, bevelEnabled: true, bevelSize: bevel, bevelThickness: bevel, bevelSegments: 3, steps: 1,
    });
    geometry.translate(0, 0, -d / 2 + bevel);
    roundGeometry.set(key, geometry);
  }
  return roundGeometry.get(key);
}

export function createCleanerBody(dark, ivory, steel, led) {
  const body = new THREE.Group();
  for (const [radius, height, material, x, y, z] of [
    [.275, .098, dark, 0, .062, 0], [.264, .064, ivory, 0, .125, 0],
    [.082, .052, steel, -.07, .171, -.053], [.058, .014, dark, -.07, .200, -.053],
    [.020, .007, led, .088, .159, .03],
  ]) {
    const part = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, height, 48), material);
    part.position.set(x, y, z);
    part.castShadow = part.receiveShadow = true;
    body.add(part);
  }
  return body;
}
