export const birthdayCameraViews = {
  living_room: { eye: [2.40, 4.85, 10.9], aim: [-1.53, 1.33, -1.22], zoom: 2.15 },
  dining_table: { eye: [6.25, 5.16, 8.70], aim: [4.15, .90, .70], zoom: 2.65 },
};

export const pinkLightReading = { power: true, color: { hue: 330, saturation: 48, brightness: 66 } };

export const birthdayReadings = {
  light_01: { power: false },
  display_01: { play_mood: { scene: "kids_party" } },
};

export const birthdayScene = {
  moment: "birthday_library",
  slots: [
    { slot: "balloon", anchor: "living_room", params: { count: 6 } },
    { slot: "balloon", anchor: "living_room", params: { placement: "floor", count: 3 } },
    { slot: "banner", anchor: "living_room", params: {} },
    { slot: "party_hat", anchor: "kitchen", params: {} },
    { slot: "cake_topper", anchor: "kitchen", params: {} },
    { slot: "strawberry", anchor: "kitchen", params: { placement: "counter" } },
    { slot: "cream", anchor: "kitchen", params: { placement: "counter" } },
  ],
  artwork: { tv: "/sim/assets/house/castle.jpg" },
};
