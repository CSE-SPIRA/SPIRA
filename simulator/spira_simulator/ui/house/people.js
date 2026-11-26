import * as THREE from "./vendor/three.module.min.js";
import { guestPlaces, guestTracks } from "./scene.js";
import { applyMotionFrame, disposeSlot, guestLooks, motionPresets, slotBuilders } from "./slots.js";

const actionPlaces = {
  light_01: [-1.70, .075, -1.55, .4],
  display_01: [-.68, .075, -2.56, Math.PI],
  cleaner_01: [.44, .075, -1.80, 2.6],
  purifier_01: [-4.14, .075, -1.62, 2.7],
  speaker_01: [-2.55, .075, -2.44, Math.PI],
  aircon_01: [.65, .075, -2.85, Math.PI],
  styler_01: [-5.41, .075, 1.39, -1.4],
  cooktop_01: [2.27, .075, -2.11, Math.PI],
  oven_01: [3.73, .075, -1.93, Math.PI],
  fridge_01: [6.02, .075, -1.96, Math.PI],
  plug_kettle: [5.25, .075, -2.10, Math.PI],
};
const livingDevices = new Set(["light_01", "display_01", "cleaner_01", "purifier_01", "speaker_01", "aircon_01"]);

export const PERSON_ACTION_MS = 6000;

export function createHousePeople(invalidate) {
  const layer = new THREE.Group();
  layer.name = "house_people";
  const guests = new THREE.Group();
  guests.name = "house_guests";
  layer.add(guests);
  const actions = new Map();
  let looks = [], currentArrival, tracks = [], arrivalAt = 0;

  function dress(stand, slot, options, sceneLook) {
    if (stand.children.length) disposeSlot(stand.children[0]);
    stand.add(slotBuilders[slot]({ ...options, ...sceneLook?.params }));
  }

  function dressGuests(entering) {
    const guestStyles = looks.filter(({ slot, anchor }) =>
      slot === "guest_child" && (anchor === "living_room" || (entering && anchor === "entrance")));
    guests.children.forEach((stand, index) => {
      const look = guestStyles.length ? guestStyles[index % guestStyles.length] : undefined;
      dress(stand, "guest_child", guestLooks[index % guestLooks.length], look);
    });
  }

  function dressAction(stand, kind, device) {
    dress(stand, kind, {}, livingDevices.has(device) &&
      looks.find(({ slot, anchor }) => slot === kind && anchor === "living_room"));
  }

  function setLooks(next) {
    if (JSON.stringify(looks) === JSON.stringify(next)) return;
    looks = next;
    dressGuests(tracks.length > 0);
    for (const [device, { stand, kind }] of actions) dressAction(stand, kind, device);
    invalidate();
  }

  function setGuests(arrival, count, now) {
    if (!arrival) count = 0;
    if (arrival === currentArrival && count === guests.children.length) return;
    currentArrival = arrival;
    for (const stand of [...guests.children]) {
      disposeSlot(stand.children[0]);
      stand.removeFromParent();
    }
    tracks = [];
    if (arrival) {
      for (let index = 0; index < count; index++) {
        const stand = new THREE.Group();
        const [x, y, z] = guestPlaces[index % guestPlaces.length];
        const row = Math.floor(index / guestPlaces.length);
        stand.position.set(x + row % 3 * .40, y, z + row * .32);
        stand.rotation.y = [.37, .10, .65][index % guestPlaces.length];
        guests.add(stand);
      }
      tracks = guestTracks(guests.children);
      arrivalAt = now;
      dressGuests(true);
    }
    invalidate();
  }

  function setActions(observed) {
    for (const [id, action] of actions) {
      const change = observed.get(id);
      if (change?.at === action.at && (change.kind === "child") === (action.kind === "child")) continue;
      clearTimeout(action.timer);
      disposeSlot(action.stand.children[0]);
      action.stand.removeFromParent();
      actions.delete(id);
      invalidate();
    }
    for (const [id, { at, kind: figure }] of observed) {
      if (actions.has(id) || !Object.hasOwn(actionPlaces, id)) continue;
      const kind = figure === "child" ? "child" : "adult";
      const stand = new THREE.Group();
      stand.name = `house_person_${id}`;
      const [x, y, z, yaw] = actionPlaces[id];
      stand.position.set(x, y, z);
      stand.rotation.y = yaw;
      dressAction(stand, kind, id);
      layer.add(stand);
      const timer = setTimeout(() => {
        stand.visible = false;
        invalidate();
      }, PERSON_ACTION_MS);
      actions.set(id, { stand, kind, at, timer });
      invalidate();
    }
  }

  function draw(now, reducedMotion) {
    const preset = motionPresets.guests_enter;
    if (tracks.length) {
      const elapsed = reducedMotion ? preset.duration : (now - arrivalAt) / 1000;
      applyMotionFrame(preset.sample(elapsed, { tracks }));
      if (elapsed >= preset.duration) {
        tracks = [];
        if (looks.some(({ slot, anchor }) => slot === "guest_child" && anchor === "entrance")) dressGuests(false);
      }
      return true;
    }
    return false;
  }

  return { layer, setGuests, setActions, setLooks, draw };
}
