import * as THREE from "./vendor/three.module.min.js";

export function createCeilingCove({ width = 1.5, height = .72, returnDepth = .55 } = {}) {
  const group = new THREE.Group();
  const trim = new THREE.MeshStandardMaterial({ color: "#e9dfca", roughness: .8 });
  const recess = new THREE.MeshStandardMaterial({ color: "#b9a997", roughness: .85 });
  const strip = new THREE.MeshBasicMaterial({ toneMapped: false, transparent: true, opacity: 0 });
  const halo = new THREE.ShaderMaterial({
    uniforms: { tint: { value: strip.color }, level: { value: 0 } },
    vertexShader: `
      varying vec2 bandUV;
      void main() {
        bandUV = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      varying vec2 bandUV;
      uniform vec3 tint;
      uniform float level;
      void main() {
        float glow = 1.0 - smoothstep(0.08, 0.5, abs(bandUV.y - 0.5));
        gl_FragColor = vec4(tint, 0.65 * level * glow * glow);
        #include <colorspace_fragment>
      }
    `,
    transparent: true,
    depthWrite: false,
  });
  const emitters = [];
  const profileScale = Math.min(1, height / 2);
  for (const [length, x, z, angle] of [
    [width, 0, 0, 0],
    [returnDepth, -width / 2, returnDepth / 2, Math.PI / 2],
    [returnDepth, width / 2, returnDepth / 2, -Math.PI / 2],
  ]) {
    const edge = new THREE.Group();
    edge.position.set(x, height, z);
    edge.rotation.y = angle;
    group.add(edge);

    for (const [material, h, d, y, offset] of [
      [recess, .095, .05, -.043, .027],
      [trim, .044, .108, .012, .043],
      [trim, .062, .137, -.086, .058],
    ]) {
      const molding = new THREE.Mesh(new THREE.BoxGeometry(length, h * profileScale, d * profileScale), material);
      molding.position.set(0, y * profileScale, offset * profileScale);
      molding.receiveShadow = true;
      edge.add(molding);
    }

    const diffusion = new THREE.Mesh(new THREE.PlaneGeometry(length, .032 * profileScale), strip);
    diffusion.name = "cove_strip";
    diffusion.position.set(0, -.038 * profileScale, .063 * profileScale);
    diffusion.visible = false;
    const glow = new THREE.Mesh(new THREE.PlaneGeometry(length, .145 * profileScale), halo);
    glow.position.set(0, -.033 * profileScale, .132 * profileScale);
    glow.visible = false;
    edge.add(diffusion, glow);
    emitters.push(diffusion, glow);
  }

  const lights = [-.34, 0, .34].map(fraction => {
    const light = new THREE.PointLight("#ffffff", 0, height * 1.75, 2);
    light.position.set(width * fraction, height * .87, height * .20);
    group.add(light);
    return light;
  });

  return {
    group,
    render(tint, level) {
      strip.color.copy(tint);
      strip.opacity = Math.min(1, 2 * level);
      halo.uniforms.level.value = Math.min(1, 1.6 * level);
      for (const emitter of emitters) emitter.visible = level > 0;
      for (const light of lights) {
        light.color.copy(tint);
        light.intensity = 2.8 * height ** 2 * level;
      }
    },
  };
}
