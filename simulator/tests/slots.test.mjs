import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createCeilingCove } from "../spira_simulator/ui/house/ceiling-cove.js";
import { createLivingLight, fitViewerCamera, orientHouseCamera, projectHouseLabels } from "../spira_simulator/ui/house/house.js";
import { birthdayCameraViews, birthdayScene, pinkLightReading } from "../spira_simulator/ui/house/library-scene.js";
import { createSceneLayer } from "../spira_simulator/ui/house/scene.js";
import { applyMotionFrame, createLightSpreadWash, motionPath, motionPresets, slotBuilders } from "../spira_simulator/ui/house/slots.js";
import { Box3, Group, MeshStandardMaterial, OrthographicCamera, PointLight, Scene, Texture, TextureLoader, Vector3 } from "../spira_simulator/ui/house/vendor/three.module.min.js";

const ui = new URL("../spira_simulator/ui/house/", import.meta.url);
const slots = JSON.parse(readFileSync(new URL("slots.json", ui), "utf8"));
const profile = JSON.parse(readFileSync(new URL("../spira_simulator/profiles/ep_9031.json", import.meta.url), "utf8"));

function values(rule) {
  if (rule.enum) return rule.enum;
  if (rule.type === "integer") {
    return Array.from({ length: rule.maximum - rule.minimum + 1 }, (_, index) => rule.minimum + index);
  }
  assert.deepEqual(rule.type, ["string", "null"]);
  return [null, "https://example.test/banner.png", "/sim/assets/house/castle.jpg"];
}

function combinations(entries) {
  return entries.reduce((rows, [key, allowed]) => rows.flatMap(row => values(allowed).map(value => ({
    ...row, [key]: value,
  }))), [{}]);
}

test("slot vocabulary matches the renderers and the h_042 profile", () => {
  assert.equal(profile.household_id, "h_042");
  assert.deepEqual(slots.map(({ id }) => id).sort(), Object.keys(slotBuilders).sort());
  assert.deepEqual(slots.filter(({ kind }) => kind === "motion").map(({ id }) => id).sort(),
    Object.keys(motionPresets).sort());
  const anchors = new Set(profile.devices.flatMap(device => [device.logical_id, device.room]));
  for (const slot of slots) {
    assert.ok(slot.anchors.length > 0);
    for (const anchor of slot.anchors) assert.ok(anchors.has(anchor), `${slot.id}: ${anchor}`);
  }
  for (const { slot: id, anchor } of birthdayScene.slots) {
    assert.ok(slots.find(slot => slot.id === id)?.anchors.includes(anchor), `${id}: ${anchor}`);
  }
});

for (const { id, parameters } of slots) {
  test(`${id} builds a finite Three.js scene graph with every allowed parameter combination`, () => {
    const scene = new Scene();
    for (const params of [undefined, ...combinations(Object.entries(parameters))]) {
      const group = slotBuilders[id](params);
      scene.add(group);
      let meshes = 0;
      group.traverse(object => {
        if (object.isMesh) meshes++;
        assert.ok([...object.position, ...object.scale, ...object.quaternion].every(Number.isFinite));
      });
      assert.ok(meshes > 0);
      const bounds = new Box3().setFromObject(group);
      assert.ok(!bounds.isEmpty());
      assert.ok([...bounds.min, ...bounds.max].every(Number.isFinite));
      scene.remove(group);
    }
  });
}

test("balloons mix three distinct finishes by default and can rest on the floor", () => {
  function bodies(model) {
    const materials = [];
    model.traverse(object => {
      if (object.geometry?.type === "SphereGeometry") materials.push(object.material);
    });
    return materials;
  }

  const defaults = slots.find(({ id }) => id === "balloon").parameters;
  assert.equal(defaults.palette.default, "pink_white_gold");
  assert.equal(defaults.placement.default, "bunch");
  const mixed = bodies(slotBuilders.balloon({ count: 6 }));
  assert.equal(new Set(mixed).size, 3);
  assert.equal(mixed.filter(material => material.metalness > 0).length, 2);
  assert.ok(bodies(slotBuilders.balloon({ palette: "ocean_blue" })).every(({ color }) => color.b > color.r));
  const floor = slotBuilders.balloon({ placement: "floor", count: 3 });
  const bounds = new Box3().setFromObject(floor, true);
  assert.equal(bodies(floor).length, 3);
  assert.ok(Math.abs(bounds.min.y) < .015 && bounds.max.y < .52);
});

test("counter strawberries are enlarged and cream packaging is a squat tub", () => {
  const size = (id, placement) => new Box3().setFromObject(slotBuilders[id]({ placement })).getSize(new Vector3());
  assert.ok(size("strawberry", "counter").x > size("strawberry", "fridge").x);
  const tub = size("cream", "counter");
  assert.ok(tub.y < tub.x && tub.y < tub.z);
});

test("the default banner prints HAPPY and BIRTHDAY on separate rows", t => {
  globalThis.document = { createElement() {
    const canvas = {};
    canvas.getContext = () => ({ strokeText() {}, fillText(letter) { canvas.letter = letter; } });
    return canvas;
  } };
  t.after(() => { delete globalThis.document; });
  const [garland] = slotBuilders.banner().children;
  const letters = garland.children.filter(child => child.isGroup).map(flag => {
    const glyph = flag.children.find(child => child.material?.map);
    return [glyph.material.map.image.letter, flag.position.y];
  });
  assert.equal(letters.filter(([, y]) => y > -.20).map(([letter]) => letter).join(""), "HAPPY");
  assert.equal(letters.filter(([, y]) => y < -.20).map(([letter]) => letter).join(""), "BIRTHDAY");
});

test("ceiling cove follows observed light color and power independently of scene values", () => {
  const slot = slots.find(({ id }) => id === "ceiling_cove");
  assert.equal(slot.kind, "effect");
  assert.deepEqual(slot.parameters, {});
  const sample = pinkLightReading;
  const sceneCove = slotBuilders.ceiling_cove(sample);
  assert.equal(sceneCove.getObjectByName("cove_strip").visible, false);

  const cove = createCeilingCove();
  const strip = cove.group.getObjectByName("cove_strip");
  const spill = cove.group.children.filter(child => child.isPointLight);
  const lamp = new PointLight();
  const light = createLivingLight(lamp, new MeshStandardMaterial(), { value: 0 }, cove);
  const observe = values => {
    light.update(values, 0);
    light.render(1000);
  };

  observe({ scene: "kids_party", ceiling_cove: sample });
  assert.equal(strip.visible, false);
  observe(sample);
  assert.equal(strip.visible, true);
  assert.equal(strip.material.color.getHexString(), "ff85c2");
  assert.ok(spill.length > 0 && spill.every(light => light.intensity > 0 && light.color.equals(strip.material.color)));

  observe({ power: true, color: { ...sample.color, hue: 120 }, ceiling_cove: sample });
  assert.equal(strip.material.color.getHexString(), "85ff85");
  observe({ ...sample, power: false, ceiling_cove: sample });
  const wash = createLightSpreadWash();
  applyMotionFrame(motionPresets.light_spread.sample(2.2, { wash }));
  assert.ok(wash.spreadLevel.value > 0);
  assert.equal(strip.visible, false);
  assert.ok(spill.every(light => light.intensity === 0));
});

test("banner keeps its garland until the supplied artwork is ready", t => {
  const url = "/sim/assets/house/castle.jpg";
  let loaded;
  t.mock.method(TextureLoader.prototype, "load", (artwork, onLoad) => {
    assert.equal(artwork, url);
    loaded = onLoad;
  });
  globalThis.document = {};
  t.after(() => { delete globalThis.document; });
  const banner = slotBuilders.banner({ artwork: url });
  const [garland] = banner.children;
  assert.equal(garland.visible, true);
  let changes = 0;
  banner.addEventListener("artworkchange", () => changes++);
  const texture = new Texture({ width: 1280, height: 720 });
  loaded(texture);
  assert.equal(garland.visible, false);
  assert.equal(changes, 1);
  const panel = banner.children.find(child => child.material?.map === texture);
  assert.ok(panel);
  assert.ok(Math.abs(panel.scale.x / panel.scale.y - 1280 / 720) < 1e-9);
});

test("motions sample deterministically without touching their targets or device values", () => {
  const deviceValues = Object.freeze({
    cleaner_01: Object.freeze({ job_status: "idle", in_use: false }),
    light_01: Object.freeze({ power: true, color: Object.freeze({ kelvin: 3000 }) }),
  });
  const cleaner = slotBuilders.cleaner_sweep();
  cleaner.userData.deviceValues = deviceValues.cleaner_01;
  const guests = slotBuilders.guests_enter().children;
  const wash = createLightSpreadWash();
  const path = motionPath([[0, 0, 0], [1, 0, 0], [1, 0, 2], [0, 0, 0]]);
  const tracks = guests.map((target, i) => ({
    target, facing: .4, path: motionPath([[-5, 0, -2], [-3, 0, -1], [i, 0, 0]]),
  }));
  const targets = {
    cleaner_sweep: { target: cleaner, path },
    guests_enter: { tracks },
    light_spread: { wash },
  };

  const meshState = () => ({
    objects: [cleaner, ...guests].map(object => [object.position.toArray(), object.quaternion.toArray()]),
    wash: [wash.spreadReach.value, wash.spreadLevel.value],
  });
  for (const [id, { sample, duration }] of Object.entries(motionPresets)) {
    const before = meshState();
    const middle = sample(duration / 2, targets[id]);
    const zero = sample(0, targets[id]);
    const end = sample(duration, targets[id]);
    assert.deepEqual(sample(duration / 2, targets[id]), middle);
    assert.deepEqual(sample(-1, targets[id]), zero);
    assert.deepEqual(sample(duration + 1, targets[id]), end);
    assert.notDeepEqual(middle, zero);
    assert.deepEqual(meshState(), before);
    applyMotionFrame(middle);
    assert.notDeepEqual(meshState(), before);
    applyMotionFrame(end);
    assert.deepEqual(deviceValues, {
      cleaner_01: { job_status: "idle", in_use: false },
      light_01: { power: true, color: { kelvin: 3000 } },
    });
  }
  assert.ok(cleaner.position.length() < 1e-9);
  guests.forEach((guest, index) => assert.ok(guest.position.distanceTo(new Vector3(index, 0, 0)) < 1e-9));
  assert.ok(wash.spreadReach.value > 1.5);
  assert.ok(wash.spreadLevel.value > 0 && wash.spreadLevel.value < .4);
});

for (const [viewport, width, height] of [["1920×1080", 1518, 721], ["1440×900", 1358, 601]]) {
  test(`the fixed arrangement fits the house canvas at ${viewport}`, () => {
    const camera = new OrthographicCamera();
    orientHouseCamera(camera, new Vector3(8.5, 10.6, 17.4), new Vector3(-.1, .76, 0), 1, width / height);
    fitViewerCamera(camera, width, height);
    const preview = createSceneLayer(birthdayScene.slots);
    const assembled = preview.layer.children;
    for (const [index, model] of assembled.entries()) {
      const { min, max } = new Box3().setFromObject(model);
      const projected = [min.x, max.x].flatMap(x => [min.y, max.y].flatMap(y => [min.z, max.z]
        .map(z => new Vector3(x, y, z).project(camera))));
      const screen = new Box3().setFromPoints(projected);
      const id = birthdayScene.slots[index].slot;
      assert.ok(projected.every(({ x, y }) => Math.abs(x) < 1 && Math.abs(y) < 1), id);
      assert.ok(screen.getSize(new Vector3()).y * height / 2 >= 16, id);
    }
  });
}

test("the close-ups frame the garland and tabletop goods on desktop and mobile", () => {
  const preview = createSceneLayer(birthdayScene.slots);
  const camera = new OrthographicCamera();
  for (const [width, height] of [[1358, 601], [358, 260]]) {
    for (const [view, ids] of [["living_room", ["banner"]], ["dining_table", ["party_hat", "cake_topper"]]]) {
      const { eye, aim, zoom } = birthdayCameraViews[view];
      orientHouseCamera(camera, new Vector3(...eye), new Vector3(...aim), zoom, width / height);
      if (view === "dining_table") {
        const { table } = projectHouseLabels(camera, width, height, null, true);
        assert.ok(table.left > 0 && table.right < width && table.top > 0 && table.bottom < height);
        const counterEdge = new Vector3(3.72, 1.067, -2.54).project(camera);
        assert.ok(Math.abs(counterEdge.x) < 1 && Math.abs(counterEdge.y) < .92);
      }
      for (const id of ids) {
        const model = preview.layer.children[birthdayScene.slots.findIndex(({ slot }) => slot === id)];
        const { min, max } = new Box3().setFromObject(model);
        for (const x of [min.x, max.x]) for (const y of [min.y, max.y]) for (const z of [min.z, max.z]) {
          const point = new Vector3(x, y, z).project(camera);
          assert.ok(Math.abs(point.x) < .92 && Math.abs(point.y) < .92, `${view}: ${id} at ${width}px`);
        }
      }
    }
  }
});
