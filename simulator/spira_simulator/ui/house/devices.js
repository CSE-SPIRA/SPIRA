import { DEVICE_NAMES } from "./vocabulary.js";

// The fixed 3D scene can show its model before the live inventory arrives.
export const HOUSE_DEVICES = {
  cleaner_01: { label: DEVICE_NAMES.cleaner, room: "living_room" },
  light_01: { label: "거실 조명", room: "living_room" },
  display_01: { label: DEVICE_NAMES.display, room: "living_room" },
  cooktop_01: { label: DEVICE_NAMES.cooktop, room: "kitchen" },
  oven_01: { label: DEVICE_NAMES.oven, room: "kitchen" },
  fridge_01: { label: DEVICE_NAMES.fridge, room: "kitchen" },
  plug_kettle: { label: "전기포트 플러그", room: "kitchen" },
  purifier_01: { label: DEVICE_NAMES.purifier, room: "living_room" },
  styler_01: { label: DEVICE_NAMES.styler, room: "entrance" },
};
