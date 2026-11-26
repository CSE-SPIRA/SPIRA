import * as THREE from "./vendor/three.module.min.js";
import { applyMotionFrame, disposeSlot, motionPath, motionPresets, poseConfetti, slotBuilders } from "./slots.js";
import vocabulary from "./scene-vocabulary.js";

const own = Object.hasOwn;
const isRecord = value => value !== null && typeof value === "object" &&
  [Object.prototype, null].includes(Object.getPrototypeOf(value));

function imageSource(value) {
  if (typeof value !== "string" || !value || /[\u0000-\u001f\u007f]/.test(value)) return false;
  if (/^data:/i.test(value)) {
    const match = /^data:image\/(?:png|jpeg|svg\+xml)(?:;charset=[\w-]+)?(;base64)?,(.+)$/i.exec(value);
    return Boolean(match && (!match[1] || /^[A-Za-z0-9+/]+={0,2}$/.test(match[2])));
  }
  if (value !== value.trim() || /^(?:[\w+.-]+:|\/\/|[?#])/.test(value) || value.includes("\\")) return false;
  const base = "https://house.invalid/";
  return URL.canParse(value, base) && new URL(value, base).origin === new URL(base).origin;
}

function allowedParameter(value, rule) {
  if (rule.enum) return rule.enum.includes(value);
  if (rule.type === "integer") return Number.isInteger(value) && value >= rule.minimum && value <= rule.maximum;
  if (rule.format === "uri-reference") return value === null || imageSource(value);
  return false;
}

export function validateScene(scene, slots = vocabulary) {
  const reasons = [];
  function checkFields(object, path, allowed) {
    if (!isRecord(object)) {
      reasons.push(`${path} must be an object`);
      return false;
    }
    for (const key of Reflect.ownKeys(object)) {
      if (!allowed.includes(key)) reasons.push(`${path}.${String(key)} is not allowed`);
    }
    return true;
  }

  if (checkFields(scene, "scene", ["moment", "slots", "artwork"])) {
    if (own(scene, "moment") && typeof scene.moment !== "string") reasons.push("scene.moment must be a string");
    if (!Array.isArray(scene.slots)) {
      reasons.push("scene.slots must be an array");
    } else {
      for (const key of Reflect.ownKeys(scene.slots)) {
        if (key !== "length" && !(typeof key === "string" && /^(0|[1-9]\d*)$/.test(key) && Number(key) < scene.slots.length)) {
          reasons.push(`scene.slots.${String(key)} is not allowed`);
        }
      }
      for (const [index, entry] of scene.slots.entries()) {
        const path = `scene.slots[${index}]`;
        if (!checkFields(entry, path, ["slot", "params", "anchor"])) continue;
        const slot = slots.find(({ id }) => id === entry.slot);
        if (!slot) {
          reasons.push(`${path}.slot is not in the vocabulary`);
          continue;
        }
        if (!slot.anchors.includes(entry.anchor)) reasons.push(`${path}.anchor is not allowed for ${slot.id}`);
        if (checkFields(entry.params, `${path}.params`, Object.keys(slot.parameters))) {
          for (const key of Object.getOwnPropertyNames(entry.params)) {
            if (own(slot.parameters, key) && !allowedParameter(entry.params[key], slot.parameters[key])) {
              reasons.push(`${path}.params.${key} is outside the published values`);
            }
          }
        }
      }
    }
    if (own(scene, "artwork") && checkFields(scene.artwork, "scene.artwork", ["tv", "fridge_panel"])) {
      for (const key of ["tv", "fridge_panel"]) {
        if (own(scene.artwork, key) && !imageSource(scene.artwork[key])) {
          reasons.push(`scene.artwork.${key} must be an image data URL or same-origin path`);
        }
      }
    }
  }
  return { ok: reasons.length === 0, reasons };
}

const counterPositions = {
  strawberry: [4.47, 1.068, -2.92],
  cream: [5.01, 1.068, -2.80],
};
const scenePositions = {
  banner: [-1.08, 2.671, -3.36],
  party_hat: [3.66, .907, 1.53],
  cake_topper: [4.70, .907, 1.46],
  confetti: [-1.56, .075, -1.28],
  light_spread: [-1.42, .14, -.23],
  ceiling_cove: [-2.4, 1.9, -3.64],
};
const cleanerRoute = [
  [.82, .10, -2.47], [.51, .10, -2.27], [-2.97, .10, -2.27], [-3.27, .10, -1.94],
  [-2.94, .10, -1.67], [.39, .10, -1.67], [.63, .10, .53], [.69, .10, 2.79],
  [.33, .10, 3.26], [-3.1, .10, 3.30], [-3.71, .10, 3.13], [-3.91, .10, .38],
  [-3.89, .10, -.88], [-3.02, .10, -1.55], [.42, .10, -1.55], [.82, .10, -2.47],
];
const entryPoints = [
  [[-5.68, .075, -2.71], [-5.46, .075, -1.95], [-4.59, .075, -1.37]],
  [[-5.91, .075, -2.90], [-5.56, .075, -1.78], [-4.55, .075, -1.59]],
  [[-5.65, .075, -3.13], [-5.24, .075, -1.74], [-4.43, .075, -.99]],
];
export const guestPlaces = [
  [-2.56, .075, -1.10], [-.67, .126, -.57], [-3.14, .126, .19],
];

export function guestTracks(figures) {
  return figures.map((target, index) => ({
    target,
    facing: target.rotation.y,
    path: motionPath([...entryPoints[index % entryPoints.length], target.position.toArray()]),
  }));
}

function scenePosition(slot, params, anchor) {
  if (slot === "balloon") return params.placement === "floor" ? [-3.72, .075, -3.10] : [-3.05, .075, -2.78];
  if (slot in counterPositions) {
    if (anchor === "kitchen") return counterPositions[slot];
    return [slot === "strawberry" ? 5.96 : 6.31, 2.27, -3.18];
  }
  return scenePositions[slot];
}

export function createSceneLayer(entries, invalidate) {
  const layer = new THREE.Group();
  layer.name = "house_scene";
  const looks = [];
  const animations = [];
  function play(object, duration, sample) {
    animations.push({ object, duration, sample });
  }

  for (const { slot, params, anchor } of entries) {
    const definition = vocabulary.find(({ id }) => id === slot);
    const parameters = Object.fromEntries(Object.entries(definition.parameters).map(([key, rule]) =>
      [key, own(params, key) ? params[key] : rule.default]));
    if (definition.kind === "person") {
      looks.push({ slot, params: { ...params }, anchor });
      continue;
    }
    const object = slotBuilders[slot](parameters, { inHouse: true });
    object.name = slot;
    const position = scenePosition(slot, parameters, anchor);
    if (position) object.position.fromArray(position);
    if (slot === "cake_topper") object.rotation.y = .25;
    object.addEventListener("artworkchange", () => { if (layer.parent) invalidate(); });
    layer.add(object);

    const preset = motionPresets[slot];
    let targets;
    if (slot === "cleaner_sweep") targets = { target: object, path: motionPath(cleanerRoute) };
    if (slot === "guests_enter") {
      const tracks = object.children.map((target, index) => ({
        target,
        path: motionPath(anchor === "entrance" ? entryPoints[index] :
          [entryPoints[index].at(-1), [-3.9, .105, -1.25], guestPlaces[index]]),
      }));
      targets = { tracks };
    }
    if (slot === "light_spread") targets = { wash: object.userData.wash };
    if (preset) play(object, preset.duration, elapsed => {
      applyMotionFrame(preset.sample(elapsed, targets));
      if (slot === "light_spread") {
        object.scale.setScalar(targets.wash.spreadReach.value);
        object.material.opacity = targets.wash.spreadLevel.value;
      }
    });
    if (slot === "confetti") play(object, 2, elapsed => poseConfetti(object, elapsed / 2));
  }

  return {
    layer, looks,
    dispose() {
      for (const object of [...layer.children]) disposeSlot(object);
      layer.removeFromParent();
    },
    draw(elapsed, reducedMotion) {
      for (const { object, duration, sample } of animations) {
        object.visible = !reducedMotion && elapsed < duration;
        if (object.visible) sample(elapsed);
      }
      return animations.some(({ object }) => object.visible);
    },
  };
}
