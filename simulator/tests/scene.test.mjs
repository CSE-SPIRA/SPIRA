import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { validateScene } from "../spira_simulator/ui/house/house.js";
import { birthdayReadings, birthdayScene, pinkLightReading } from "../spira_simulator/ui/house/library-scene.js";
import { PERSON_ACTION_MS } from "../spira_simulator/ui/house/people.js";
import sceneVocabulary from "../spira_simulator/ui/house/scene-vocabulary.js";
import { houseHarness } from "./house-fixture.mjs";

const slotsPath = new URL("../spira_simulator/ui/house/slots.json", import.meta.url);
const vocabulary = JSON.parse(readFileSync(slotsPath, "utf8"));
const balloon = birthdayScene.slots[0];

test("the renderer matches the published scene vocabulary and accepts the library scene", () => {
  assert.deepEqual(sceneVocabulary, vocabulary.map(({ id, kind, parameters, anchors }) =>
    ({ id, kind, parameters, anchors })));
  assert.deepEqual(validateScene(birthdayScene, vocabulary), { ok: true, reasons: [] });
  for (const image of ["/local/tv.jpg", "./fridge.png", "data:image/png;base64,AA==", "data:image/jpeg;base64,AA==",
    "data:image/svg+xml;charset=utf-8,%3Csvg%2F%3E"]) {
    assert.equal(validateScene({ slots: [], artwork: { tv: image, fridge_panel: image } }, vocabulary).ok, true, image);
  }
});

test("scene validation rejects unsupported slots, parameters, anchors, URLs, and fields at every level", () => {
  for (const [entry, field] of [
    [{ ...balloon, slot: "unknown" }, "slot"],
    [{ ...balloon, params: { palette: "purple" } }, "palette"],
    [{ ...balloon, params: { count: 0 } }, "count"],
    [{ ...balloon, params: { count: 2.5 } }, "count"],
    [{ ...balloon, anchor: "kitchen" }, "anchor"],
  ]) {
    assert.match(validateScene({ slots: [entry] }, vocabulary).reasons.join(" "), new RegExp(field));
  }
  for (const field of ["display_01", "value", "power", "event", "actor", "by", "time", "at"]) {
    for (const input of [
      { slots: [balloon], [field]: true },
      { slots: [{ ...balloon, [field]: true }] },
      { slots: [{ ...balloon, params: { [field]: true } }] },
      { slots: [balloon], artwork: { [field]: true } },
    ]) {
      const result = validateScene(input, vocabulary);
      assert.equal(result.ok, false);
      assert.match(result.reasons.join(" "), new RegExp(field));
    }
  }
  for (const tv of ["https://external.test/a.png", "//external.test/a.png", "/\\external.test/a.png",
    "javascript:alert(1)", "data:text/html,hi", "data:image/webp,abc", "data:image/png;base64,"]) {
    assert.equal(validateScene({ slots: [], artwork: { tv } }, vocabulary).ok, false, tv);
  }
  assert.equal(validateScene({ slots: [], moment: 10 }, vocabulary).ok, false);
  assert.equal(validateScene({ slots: [{ slot: "balloon", anchor: "living_room" }] }, vocabulary).ok, false);
});

const readings = {
  display_01: { play_mood: { scene: "kids_party" } },
  light_01: { power: true, color: { kelvin: 3800 } },
  cleaner_01: { job_status: "idle" },
  fridge_01: { show_notice: "씻지 않고 냉장 보관해 주세요." },
};

test("a scene adds renderer objects, retains them on rejection, and clears them without changing devices", t => {
  const view = houseHarness(t);
  view.markers(readings);
  view.draw(1200);
  const lamp = view.scene.children.find(object => object.isPointLight && object.position.x === -1.42);
  const cleaner = view.scene.children.flatMap(object => object.children).find(object =>
    object.isGroup && object.position.distanceTo({ x: .82, y: .064, z: -2.59 }) === 0);
  const tv = view.canvas(1024);
  const deviceState = () => ({
    light: lamp.color.getHexString(), intensity: lamp.intensity, cleaner: cleaner.position.toArray(),
    tv: tv.at(-1)[1].stops,
  });
  const before = deviceState();
  assert.deepEqual(before.tv, [[0, "#9669bd"], [1, "#e997ac"]]);
  assert.ok(!tv.some(([event]) => event === "image"));

  const scene = { slots: [...birthdayScene.slots, ...[
    ["cleaner_sweep", "cleaner_01"], ["guests_enter", "entrance"], ["light_spread", "light_01"], ["child", "living_room"],
  ].map(([slot, anchor]) => ({ slot, anchor, params: {} }))] };
  assert.equal(view.house.setScene(scene).ok, true);
  view.draw(3200);
  const layer = view.scene.getObjectByName("house_scene");
  assert.equal(layer.children.length, 10);
  const cue = layer.getObjectByName("cleaner_sweep");
  assert.equal(cue.geometry.type, "RingGeometry");
  assert.ok(cue.position.distanceTo(cleaner.position) > 1);
  assert.equal(view.scene.getObjectByName("house_guests").children.length, 0);
  assert.equal(view.scene.getObjectByName("house_people").children.length, 1);
  assert.deepEqual(deviceState(), before);
  assert.equal(view.house.setScene({ ...scene, power: false }).ok, false);
  view.draw(4000);
  assert.equal(view.scene.getObjectByName("house_scene"), layer);
  view.draw(11200);
  assert.equal(cue.visible, false);
  view.draw(13500);
  assert.equal(cue.visible, false);
  let disposed = false;
  cue.geometry.addEventListener("dispose", () => { disposed = true; });
  view.house.clearScene();
  assert.equal(disposed, true);
  view.draw(13800);
  assert.equal(view.scene.getObjectByName("house_scene"), undefined);
  assert.deepEqual(deviceState(), before);
});

test("scene images are drawn on active displays and removed on clear", t => {
  const view = houseHarness(t);
  view.markers(readings);
  const tv = view.canvas(1024), fridge = view.canvas(360);
  assert.equal(view.images.length, 0);
  assert.ok(!tv.some(([event]) => event === "image"));
  tv.length = fridge.length = 0;
  const artwork = { ...birthdayScene.artwork, fridge_panel: "data:image/png;base64,AA==" };
  assert.equal(view.house.setScene({ slots: [], artwork }).ok, true);
  const [tvImage, fridgeImage] = view.images;
  view.load(tvImage);
  fridge.length = 0;
  view.load(fridgeImage);
  assert.deepEqual(tv.at(-1), ["image", artwork.tv]);
  assert.deepEqual(fridge.filter(([kind]) => kind !== "fill"), [
    ["image", artwork.fridge_panel], ["text", "냉장고 안내"], ["text", readings.fridge_01.show_notice],
  ]);

  assert.equal(view.house.setScene({ slots: [], artwork: { tv: "/pending.jpg" } }).ok, true);
  const pending = view.images.at(-1);
  view.house.clearScene();
  tv.length = 0;
  view.load(pending);
  assert.equal(tv.length, 0);
  assert.deepEqual(fridge.at(-1), ["text", readings.fridge_01.show_notice]);
});

test("the standalone TV needs no generated artwork and falls back after clearing scene art", t => {
  const view = houseHarness(t);
  const tv = view.canvas(1024);
  view.markers(readings);
  assert.equal(view.images.length, 0);
  assert.ok(tv.some(([event]) => event === "fill"));
  view.house.setScene(birthdayScene);
  view.load(view.images.at(-1));
  assert.deepEqual(tv.at(-1), ["image", birthdayScene.artwork.tv]);
  tv.length = 0;
  view.house.clearScene();
  assert.ok(tv.some(([event]) => event === "fill"));
  assert.ok(!tv.some(([event]) => event === "image"));
});

test("guest figures and the person at a device follow observation markers", t => {
  const view = houseHarness(t);
  view.markers(readings, { planned: true });
  view.draw(100);
  const guests = view.scene.getObjectByName("house_guests");
  const person = () => view.scene.getObjectByName("house_person_light_01");
  assert.equal(guests.children.length, 0);
  assert.equal(person(), undefined);

  const arrival = { guestArrival: "arrival", guestCount: "4" };
  view.markers(readings, { guests: arrival });
  view.draw(101);
  assert.equal(guests.children.length, 4);
  assert.ok(guests.children[0].position.x < -5);
  assert.deepEqual(guests.children.map(stand => stand.children[0].scale.x), [1.1, 1.01, 1.16, 1.1]);
  const named = { light_01: { personAt: "changed", personFigure: "child" } };
  view.markers(readings, { guests: arrival, person: named });
  view.draw(4700);
  assert.ok(guests.children[0].position.x > -3);
  assert.deepEqual(person().position.toArray(), [-1.7, .075, -1.55]);
  assert.equal(person().children[0].scale.x, 1.23);
  const firstGuest = guests.children[0];
  const standing = firstGuest.position.clone();
  const styled = { slot: "guest_child", params: { variant: "crop" }, anchor: "living_room" };
  assert.equal(view.house.setScene({ slots: [styled] }).ok, true);
  assert.equal(firstGuest.children[0].scale.x, 1.16);
  view.house.clearScene();
  assert.equal(firstGuest.children[0].scale.x, 1.1);
  assert.deepEqual(firstGuest.position, standing);

  view.markers(readings, { person: named });
  view.draw(5100);
  assert.equal(guests.children.length, 0);
  assert.equal(person().visible, true);
  view.draw(101 + PERSON_ACTION_MS);
  assert.equal(person().visible, false);
  view.markers(readings, { person: named });
  view.draw(6400);
  assert.equal(person().visible, false);
  view.markers(readings);
  assert.equal(person(), undefined);
});

test("sample light controls use their separate readings while the preview scene leaves the light alone", t => {
  const view = houseHarness(t, { sampleReadings: birthdayReadings });
  view.house.setScene(birthdayScene);
  view.draw(1200);
  const lamp = view.scene.children.find(object => object.isPointLight && object.position.x === -1.42);
  assert.equal(lamp.intensity, 0);
  view.house.setSampleReading("light_01", pinkLightReading);
  view.draw(2300);
  assert.equal(lamp.color.getHexString(), "ff85c2");
  assert.ok(lamp.intensity > 0);
  view.house.clearScene();
  view.draw(3500);
  assert.ok(lamp.intensity > 0);
});
