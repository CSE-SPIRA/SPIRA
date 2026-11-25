import * as THREE from "./vendor/three.module.min.js";

export function createRoomWash(color, center, extent) {
  return {
    spreadTint: { value: new THREE.Color(color) },
    spreadCenter: { value: new THREE.Vector3(...center) },
    spreadExtent: { value: new THREE.Vector3(...extent) },
    spreadReach: { value: 0 },
    spreadLevel: { value: 0 },
  };
}

export function addRoomWash(shader, wash) {
  Object.assign(shader.uniforms, wash);
  shader.vertexShader = `varying vec3 washPosition;\n${shader.vertexShader}`.replace(
    "#include <worldpos_vertex>",
    "#include <worldpos_vertex>\nwashPosition = (modelMatrix * vec4(transformed, 1.0)).xyz;",
  );
  shader.fragmentShader = `
    varying vec3 washPosition;
    uniform vec3 spreadTint, spreadCenter, spreadExtent;
    uniform float spreadReach, spreadLevel;
    ${shader.fragmentShader}
  `.replace("#include <opaque_fragment>", `
    if (spreadLevel > 0.0) {
      vec3 offset = (washPosition - spreadCenter) / spreadExtent;
      float roomEdge = 1.0 - smoothstep(0.90, 1.0, max(abs(offset.x), abs(offset.z)));
      float wave = 1.0 - smoothstep(spreadReach - 0.32, spreadReach, length(offset));
      vec3 washed = outgoingLight * mix(vec3(1.0), spreadTint, 0.63);
      washed += (0.12 + diffuseColor.rgb * 0.46) * spreadTint;
      outgoingLight = mix(outgoingLight, washed, spreadLevel * roomEdge * wave);
    }
    #include <opaque_fragment>
  `);
}
