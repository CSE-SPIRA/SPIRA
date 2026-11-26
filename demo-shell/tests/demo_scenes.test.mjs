import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import test from "node:test";
import { houseHarness, projectedMeshes } from "../../simulator/tests/house-fixture.mjs";
import { sceneFixture } from "./scene-fixture.mjs";

const house = new URL("../../simulator/spira_simulator/ui/house/", import.meta.url);
registerHooks({
  resolve(specifier, context, nextResolve) {
    return nextResolve(specifier === "/demo/shared/vocabulary.js"
      ? new URL("vocabulary.js", house).href : specifier, context);
  },
});
const { validateScene } = await import(new URL("scene.js", house));
const { buildChain } = await import("../ui/chain.js");
const { Raycaster, Vector2, Vector3 } = await import(new URL("vendor/three.module.min.js", house));
const { buildMoments, closeView, momentScene, sendScene, worldFacts } = await import("../ui/scene-rules.js");
const { replayFrames } = await import("../ui/run.js");
const { withSceneArtwork } = await import("../ui/artwork/scene.js");
const { fridgeValues } = await import("../ui/artwork/fridge.js");
const { tvValues } = await import("../ui/artwork/tv.js");
const read = (path) => JSON.parse(readFileSync(new URL(path, import.meta.url)));
const vocabulary = read(new URL("slots.json", house));
const { house: wording } = read("../ui/scenes.json");
const itemTypes = read("../ui/item-types.json");
const input = sceneFixture();
const MOOD_MOMENT = "line:t_mood#3";
const image = "data:image/svg+xml;base64,PHN2Zy8+";
const goods = ["strawberry", "cream", "balloon", "balloon", "cake_topper", "party_hat"];
const mood = input.rationale.tasks.find(({ task_id }) => task_id === "t_mood#3");
const lineTag = { kind: "line", ref: mood.task_id, text: mood.line, tag: {
  devices: ["display_01", "light_01"], motion: "light_spread", palette: "ocean_blue",
} };

function run({ facts = input.facts, relations = input.relations, tags = [], episode = input.episode,
  rationale = input.rationale, at = Infinity, displayReadings } = {}) {
  const devices = structuredClone(input.devices);
  const observations = Object.values(relations).flatMap(({ observed }) => observed)
    .filter((row) => Date.parse(row.at) <= at).sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  for (const { device, values, revisions } of observations) {
    const report = devices.find(({ logical_id }) => logical_id === device);
    Object.assign(report.values, values);
    Object.assign(report.revisions, revisions);
  }
  const snapshot = { devices };
  const chain = buildChain({ episode, rationale, card: input.card, hubLedger: input.ledger, snapshot });
  const moments = buildMoments({ chain, actions: input.actions, relations, facts, tags, wording, since: episode.shared_at });
  const results = moments.map((moment) => momentScene(moment, { moments, items: chain.items,
    itemTasks: chain.item_tasks, itemTypes, vocabulary, snapshot, devices: chain.devices, displayReadings }));
  const scenes = results.map(result => result ? withSceneArtwork(result.scene, result.artwork) : null);
  for (const scene of scenes.filter(Boolean)) {
    assert.deepEqual(validateScene(scene), { ok: true, reasons: [] });
    assert.ok(scene.slots.every(({ slot }) => !["child", "adult", "guest_child", "guests_enter"].includes(slot)));
  }
  const index = (key) => moments.findIndex(({ kind, id, ready }) => ready && (kind === key || id === key));
  return { moments, scenes, devices: chain.devices,
    at: kind => scenes[index(kind)], valuesAt: kind => results[index(kind)]?.artwork };
}

test("ep_9031 orders the guest event and its observed device line separately", () => {
  const { moments } = run();
  assert.deepEqual(moments.map(({ kind, focusDevices, ready }) => [kind, focusDevices, ready]), [
    ["plan", [], true],
    ["delivery", ["fridge_01"], true],
    ["line", ["cleaner_01"], false],
    ["line", ["cooktop_01", "plug_kettle"], true],
    ["guests", [], true],
    ["line", ["display_01", "light_01"], true],
    ["line", ["oven_01"], true],
    ["person", ["light_01"], true],
    ["end", [], true],
  ]);
  const guest = moments.find(({ kind }) => kind === "guests");
  assert.equal(guest.at, input.facts.find(({ event }) => event === "guest_arrived").at);
  assert.equal(guest.room, "entrance");
  assert.deepEqual(guest.lines, []);
  const moodMoment = moments.find(({ id }) => id === MOOD_MOMENT);
  assert.equal(moodMoment.follows, guest.id);
  assert.equal(moodMoment.room, "living_room");
  assert.deepEqual(moodMoment.lines.map(({ id, when }) => [id, when]), [["t_mood#3", { event: "guest_arrived" }]]);
  assert.deepEqual(moments.find(({ kind }) => kind === "delivery").lines.map(({ id }) => id), ["t_fridge#5", "t_fridge#6"]);
  assert.deepEqual(moments.flatMap(({ lines }) => lines ?? []).map(({ id }) => id).sort(), Object.keys(input.actions).sort());
});

test("arrival and departure markers produce one guest moment and one event end", () => {
  const arrival = input.facts.find(({ event }) => event === "guest_arrived").at;
  const departure = input.facts.find(({ event }) => event === "event_end").at;
  // The viewer lists the newest marker first.
  const markers = [["empty", departure], ["presence", arrival]].map(([signal, at]) => ({
    dataset: { signal }, querySelector: () => ({ getAttribute: () => at }),
  }));
  const facts = worldFacts({ querySelectorAll: (selector) => selector === "[data-signal]" ? markers : [] });
  const { moments } = run({ facts });
  assert.deepEqual(moments.filter(({ kind }) => kind === "guests" || kind === "end")
    .map(({ event, at, ready }) => [event, at, ready]), [
    ["guest_arrived", arrival, true],
    ["event_end", departure, true],
  ]);
});

test("SH-AT-18 waits for a World fact or verified device effect before sending its scene", () => {
  const pending = run({ facts: [], relations: Object.fromEntries(Object.entries(input.relations)
    .map(([id, row]) => [id, { ...row, observed: [] }])) });
  assert.equal(pending.moments[0].kind, "plan");
  assert.ok(pending.moments.slice(1).every(({ ready }) => !ready));
  assert.ok(pending.scenes.every((scene) => scene === null));
  const delivered = run({ facts: input.facts.filter(({ event }) => event === "package.brought_in") });
  const guest = delivered.moments.find(({ kind }) => kind === "guests");
  assert.equal(guest.ready, false);
  assert.equal(guest.at, undefined);
  assert.equal(delivered.scenes[delivered.moments.indexOf(guest)], null);
  assert.deepEqual(delivered.at("delivery").slots.map(({ slot }) => slot), goods);

  const mismatch = structuredClone(input.relations);
  mismatch["t_mood#3"].match.at = "2026-10-17T13:52:45+09:00";
  const wrongEvent = run({ relations: mismatch });
  assert.deepEqual(wrongEvent.moments.find(({ kind, ready }) => kind === "guests" && ready).lines, []);
  assert.ok(!wrongEvent.moments.some(({ id }) => id === MOOD_MOMENT));

  const relations = structuredClone(input.relations);
  const guestLine = relations[mood.task_id];
  guestLine.observed = guestLine.observed.map(reading => ({ ...reading, at: input.episode.shared_at }));
  const pendingLine = run({ relations }).moments.find(({ id }) => id === MOOD_MOMENT);
  assert.equal(pendingLine.ready, false);
  assert.equal(closeView(pendingLine, run().devices), null);
});

test("only ordered goods appear after delivery, with counter and dining placement", () => {
  const before = run({ facts: input.facts.filter(({ event }) => event !== "package.brought_in") });
  assert.ok(before.scenes.filter(Boolean).flatMap(({ slots }) => slots).every(({ slot }) => !goods.includes(slot)));
  const { slots } = run().at("delivery");
  assert.deepEqual(slots, [
    { slot: "strawberry", anchor: "kitchen", params: { placement: "counter" } },
    { slot: "cream", anchor: "kitchen", params: { placement: "counter" } },
    { slot: "balloon", anchor: "living_room", params: { placement: "bunch", count: 7 } },
    { slot: "balloon", anchor: "living_room", params: { placement: "floor", count: 3 } },
    { slot: "cake_topper", anchor: "kitchen", params: {} },
    { slot: "party_hat", anchor: "kitchen", params: { count: 6 } },
  ]);
  const episode = { ...input.episode, items: input.episode.items.filter(({ type }) => !["풍선", "케이크 토퍼"].includes(type)) };
  assert.deepEqual(run({ episode, tags: [lineTag] }).at("delivery").slots.map(({ slot }) => slot),
    ["strawberry", "cream", "party_hat"]);
  assert.ok(run().scenes.filter(Boolean).flatMap(({ slots }) => slots)
    .every(({ slot }) => !["banner", "confetti"].includes(slot)));
});

test("prop counts multiply by the order quantity and cap each placement at the slot maximum", () => {
  const episode = structuredClone(input.episode);
  const balloon = episode.items.find(({ type }) => type === "풍선");
  assert.equal(balloon.name, "파티 풍선 세트");
  balloon.qty = 2;
  episode.items.find(({ type }) => type === "고깔모자").qty = 30;
  const { slots } = run({ episode }).at("delivery");
  const maximum = (slot) => vocabulary.find(({ id }) => id === slot).parameters.count.maximum;
  assert.deepEqual(slots.filter(({ slot }) => slot === "balloon").map(({ params }) => params), [
    { placement: "bunch", count: maximum("balloon") }, { placement: "floor", count: 6 },
  ]);
  assert.equal(slots.find(({ slot }) => slot === "party_hat").params.count, maximum("party_hat"));
});

test("the delivery close-up frames both fridge doors and leaves the notice and counter goods clear", (t) => {
  const { moments, devices, at } = run();
  const delivery = moments.find(({ kind }) => kind === "delivery");
  // The shell scales the same logical house canvas to 75% at 1440×900.
  const height = 550;
  const view = houseHarness(t, { width: 1038, height });
  const { house, draw } = view;
  assert.equal(house.setScene(at("delivery")).ok, true);
  house.focus(closeView(delivery, devices), { instant: true });
  draw(3000);
  const { scene, camera } = view;
  scene.updateMatrixWorld(true);
  const ray = new Raycaster();
  const meshes = [];
  scene.traverseVisible((mesh) => { if (mesh.isMesh && !mesh.material.transparent) meshes.push(mesh); });
  const position = new Vector3();
  for (const mesh of meshes) {
    mesh.getWorldPosition(position);
    // The dining table, chairs, and their props sit in front of the kitchen counter.
    if (position.x < 2.5 || position.z < .6 || position.y < .1) continue;
    const { min, max } = projectedMeshes(mesh, camera);
    if (max.x > -1 && min.x < 1) assert.ok(max.y <= -.94, mesh.parent.name || "dining furniture");
  }
  for (const name of ["fridge_door", "freezer_door", "fridge_notice", "strawberry", "cream"]) {
    const model = scene.getObjectByName(name);
    const { min, max } = projectedMeshes(model, camera);
    assert.ok(min.x > -1 && max.x < 1 && min.y > -1 && max.y < 1, name);
    if (name.endsWith("_door")) continue;
    for (const scale of [1, .75]) {
      const pixels = (max.y - min.y) * height * scale / 2;
      assert.ok(pixels >= (name === "fridge_notice" ? 120 : 40), name);
    }
    const samples = [.05, .15, .3, .5, .7, .85, .95];
    for (const x of samples) for (const y of samples) {
      ray.setFromCamera(new Vector2(min.x + x * (max.x - min.x), min.y + y * (max.y - min.y)), camera);
      const hit = ray.intersectObject(model)[0];
      if (hit) assert.ok(ray.intersectObjects(meshes, false)[0].distance >= hit.distance - 1e-4, name);
    }
  }
});

test("the mood line frames the TV and pendant at 1440×900 and 1920×1080 from its first read-back", (t) => {
  const relations = structuredClone(input.relations);
  const guestLine = relations[mood.task_id];
  guestLine.observed = guestLine.observed.filter(({ device }) => device === "light_01");
  const tag = { ...lineTag, tag: { ...lineTag.tag, devices: ["light_01"] } };
  const { moments, devices, at } = run({ relations, tags: [tag] });
  const guest = moments.find(({ kind }) => kind === "guests");
  const moment = moments.find(({ id }) => id === MOOD_MOMENT);
  assert.equal(closeView(guest, devices), null);
  assert.equal(moment.ready, true);
  assert.deepEqual(moment.focusDevices, ["display_01", "light_01"]);
  // The presenter stage keeps its logical canvas size and scales the whole view.
  const view = houseHarness(t, { width: 1038, height: 550, sampleReadings: {} });
  view.markers({
    display_01: { play_mood: { scene: "kids_party" } },
    light_01: { power: true, color: { hue: 330, saturation: 45, brightness: 70 } },
  });
  assert.equal(view.house.setScene(at(MOOD_MOMENT)).ok, true);
  view.house.focus(closeView(moment, devices), { instant: true });
  view.draw(3000);
  view.scene.updateMatrixWorld(true);
  for (const [screenWidth, screenHeight] of [[1440, 900], [1920, 1080]]) {
    const scale = Math.min(screenWidth / 1920, screenHeight / 1080);
    for (const name of ["tv_screen", "light_01"]) {
      const { min, max } = projectedMeshes(view.scene.getObjectByName(name), view.camera);
      assert.ok(min.x >= -.9 && max.x <= .9 && min.y >= -.9 && max.y <= .9, name);
      assert.ok((max.y - min.y) * 550 * scale / 2 >= 75, name);
    }
  }
  const ray = new Raycaster();
  const meshes = [];
  view.scene.traverseVisible(mesh => { if (mesh.isMesh) meshes.push(mesh); });
  const screen = view.scene.getObjectByName("tv_screen");
  const { min, max } = projectedMeshes(screen, view.camera);
  for (const x of [.1, .3, .5, .7, .9]) for (const y of [.1, .3, .5, .7, .9]) {
    ray.setFromCamera(new Vector2(min.x + x * (max.x - min.x), min.y + y * (max.y - min.y)), view.camera);
    if (ray.intersectObject(screen).length) assert.equal(ray.intersectObjects(meshes, false)[0].object, screen);
  }
});

test("judgment text has no effect on the house and an observed line palette themes the TV and balloons", () => {
  const rationale = structuredClone(input.rationale);
  rationale.intents[0].situation.theme = "정글";
  const tag = { kind: "slot", ref: "theme", text: "정글", tag: { palette: "ocean_blue" } };
  assert.deepEqual(run({ rationale, tags: [tag] }).scenes, run().scenes);
  const oldMotion = { ...lineTag, tag: { motion: "guests_enter" } };
  assert.deepEqual(run({ tags: [oldMotion] }).scenes, run().scenes);

  const palette = { ...lineTag, tag: { palette: lineTag.tag.palette } };
  const plain = run();
  const themed = run({ tags: [palette] });
  assert.deepEqual(themed.at("delivery"), plain.at("delivery"));
  assert.deepEqual(themed.at(MOOD_MOMENT).slots.map(({ slot, params }) => [slot, params.palette]),
    goods.map((slot) => [slot, slot === "balloon" ? "ocean_blue" : undefined]));
  const episode = { ...input.episode, items: input.episode.items.filter(({ type }) => type !== "풍선") };
  assert.deepEqual(run({ episode, tags: [palette] }).at(MOOD_MOMENT).slots, run({ episode }).at(MOOD_MOMENT).slots);
  assert.equal(themed.valuesAt(MOOD_MOMENT).tv.palette, "ocean_blue");
});

test("motion and artwork wait for the matching read-back, snapshot and viewer content", () => {
  const before = run({ at: Date.parse("2026-10-16T18:05:10+09:00"), tags: [lineTag] });
  assert.equal(before.at("delivery").artwork, undefined);
  assert.ok(!before.at(MOOD_MOMENT).slots.some(({ slot }) => slot === "light_spread"));
  const first = run({ at: Date.parse("2026-10-16T18:05:20+09:00") });
  assert.deepEqual(first.valuesAt("delivery"), { fridge_panel: fridgeValues("strawberry") });

  const runData = run({ tags: [lineTag] });
  assert.deepEqual(runData.valuesAt("delivery"), { fridge_panel: fridgeValues("cream") });
  assert.equal(runData.valuesAt("guests").tv, undefined);
  assert.deepEqual(runData.valuesAt(MOOD_MOMENT), {
    tv: tvValues("kids_party", lineTag.tag), fridge_panel: fridgeValues("cream"),
  });
  assert.equal(runData.at(MOOD_MOMENT).slots.at(-1).slot, "light_spread");
  const mismatchedViewer = run({ tags: [lineTag], displayReadings: new Map() });
  assert.equal(mismatchedViewer.at(MOOD_MOMENT).artwork, undefined);
});

test("the verified TV scene selects the template and only that line can fill its slots", () => {
  const relations = structuredClone(input.relations);
  const reports = relations[mood.task_id].observed;
  reports.find(({ cmd }) => cmd === "play_mood").values.play_mood.scene = "cinema";
  const wrongLine = { ...lineTag, ref: "t_fridge#6", tag: { palette: "sunny_yellow" } };
  const tag = { ...lineTag, tag: { palette: "unlisted", template: "party", motif: { center: "crown", side: "unlisted" } } };
  const values = run({ relations, tags: [wrongLine, tag] }).valuesAt(MOOD_MOMENT).tv;
  assert.deepEqual(values, { template: "cinema", palette: "calm_neutral", motifs: {
    center: "crown", side: "popcorn", ambient: "stars",
  } });
});

test("a fridge motif follows the Server's exact notice and item relation", () => {
  const { rationale, episode } = structuredClone({ rationale: input.rationale, episode: input.episode });
  const task = rationale.item_tasks.find(({ task_id }) => task_id === "t_fridge#6");
  const tag = { kind: "notice", ref: task.task_id, text: task.text, tag: { icon: "egg" } };
  assert.deepEqual(run({ tags: [tag] }).valuesAt("delivery").fridge_panel, fridgeValues("cream"));
  task.item = "우유";
  assert.deepEqual(run({ rationale }).valuesAt("delivery").fridge_panel, fridgeValues("milk"));
  task.task_id = "t_fridge#5";
  episode.item_tasks = [];
  assert.deepEqual(run({ rationale, episode }).valuesAt("delivery").fridge_panel, fridgeValues("generic"));
});

test("one send path validates every scene and replay uses the exact saved scene sequence", (t) => {
  const { moments, scenes, valuesAt } = run({ tags: [lineTag] });
  const moment = moments.find(({ id }) => id === MOOD_MOMENT);
  const scene = scenes[moments.indexOf(moment)];
  const next = { ...scene, slots: scene.slots.filter(({ slot }) => slot !== "light_spread"), artwork: { tv: image } };
  const calls = [];
  const house = { setScene(input) { calls.push(input); return validateScene(input); } };
  const warn = t.mock.method(console, "warn", () => {});
  assert.equal(sendScene(house, validateScene, { ...scene, actor: "guest" }), false);
  assert.equal(warn.mock.callCount(), 1);
  assert.deepEqual(calls, []);
  const recording = replayFrames([
    { kind: "house", data: { moment } },
    { kind: "scene", data: { moment, scene: { moment: scene.moment, slots: scene.slots }, artwork: valuesAt(MOOD_MOMENT) } },
    { kind: "scene", data: { moment, scene: next } },
  ]);
  for (const { scene } of recording.house[0].scenes) assert.ok(sendScene(house, validateScene, scene));
  assert.deepEqual(calls, [scene, next]);
});

test("a presenter action closes the TV visit before its artwork and state change", () => {
  const tv = { id: MOOD_MOMENT, title: "TV · 거실 조명" };
  const end = { id: "event:event_end", title: "일정 종료" };
  const tvScene = { moment: tv.id, slots: [] };
  const endScene = { moment: end.id, slots: [] };
  const tvOn = { devices: [{ logical_id: "display_01", values: { play_mood: { scene: "kids_party" } } }] };
  const tvOff = { devices: [{ logical_id: "display_01", values: { play_mood: null } }] };
  const { house: [before, after] } = replayFrames([
    { kind: "snapshot", data: tvOn },
    { kind: "house", data: { moment: tv } },
    { kind: "scene", data: { moment: tv, scene: tvScene, artwork: { tv: tvValues("kids_party") } } },
    { kind: "presenter", data: { action: "event_end" } },
    { kind: "snapshot", data: tvOff },
    { kind: "scene", data: { moment: tv, scene: tvScene, artwork: {} } },
    { kind: "house", data: { moment: end } },
    { kind: "scene", data: { moment: end, scene: endScene, artwork: {} } },
  ]);
  assert.equal(before.scenes.length, 1);
  assert.equal(before.scenes[0].scene.artwork.tv, withSceneArtwork(tvScene, { tv: tvValues("kids_party") }).artwork.tv);
  assert.deepEqual(before.frame.snapshot, tvOn);
  assert.deepEqual(after.frame.snapshot, tvOff);
  assert.deepEqual(after.scenes.map(({ frame, scene }) => [frame.snapshot, scene]), [[tvOff, endScene]]);
});
