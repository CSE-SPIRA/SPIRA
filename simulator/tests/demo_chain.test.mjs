import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { buildChain } from "../spira_simulator/ui/demo/chain.js";
import { houseDevicePresentation, layoutHouseLabels } from "../spira_simulator/ui/demo/house.js";

const { house: scenes } = JSON.parse(readFileSync(
  new URL("../spira_simulator/ui/demo/scenes.json", import.meta.url)));

function fixture(episode, name) {
  return JSON.parse(readFileSync(new URL(`../../contracts/fixtures/${episode}/${name}.json`, import.meta.url)));
}

function birthday() {
  const episode = fixture("ep_9031", "episode");
  const rationale = fixture("ep_9031", "rationale");
  const card = fixture("ep_9031", "card.v1");
  const hubPlan = fixture("ep_9031", "plan.v1");
  return { episode, rationale, card, hubPlan };
}

test("birthday evidence can be followed from a topper to the light and back", () => {
  const input = birthday();
  const executions = fixture("ep_9031", "executions");
  const events = fixture("ep_9031", "events").filter(({ source }) => source === "hub");
  const hubLedger = [
    { kind: "plan", plan_id: input.hubPlan.plan_id, at: input.hubPlan.sent_at },
    ...executions,
    ...events.map(({ at, type }) => ({ kind: "event", at, event_type: type })),
  ];
  const observed = { power: true, color: { kelvin: 3000 } };
  const snapshot = { devices: [{ logical_id: "light_01", values: observed, available: true }] };
  const chain = buildChain({ ...input, hubLedger, snapshot });

  assert.equal(chain.devices.length, 9);
  for (const [id, room] of [["purifier_01", "living_room"], ["styler_01", "entrance"]]) {
    const device = chain.devices.find(({ logicalId }) => logicalId === id);
    assert.equal(device.room, room);
    assert.equal(device.chosen, false);
    assert.deepEqual(device.traces, []);
  }
  assert.deepEqual(chain.funnel, { items: 9, similar: 12, bundled: 7, unbundled: 2, intents: 1, tasks: 4, cardLines: 4, devices: 7 });
  assert.deepEqual(chain.items.filter(({ unbundled }) => unbundled).map(({ id }) => id), input.rationale.unbundled);
  assert.deepEqual(chain.evidence.kbCounts, input.rationale.evidence.kb_counts);
  assert.deepEqual(chain.evidence.kbExamples, input.rationale.evidence.kb_examples);
  assert.deepEqual(chain.evidence.unusual, input.rationale.evidence.unusual_items);
  assert.equal(chain.evidence.calendar.find(({ id }) => id === chain.intent.calendarEvent).start, "14:00");
  assert.deepEqual(chain.slots.find(({ key }) => key === "event").basis, ["c1", "케이크 토퍼"]);
  assert.deepEqual(chain.slots.find(({ key }) => key === "guests").basis, ["고깔모자", "가구 유형"]);

  const topper = chain.items.find(({ id }) => id === "케이크 토퍼");
  const theme = chain.slots.find(({ key, basis }) => key === "theme" && basis.includes(topper.id));
  assert.equal(theme.value, "디즈니 공주");
  const intent = chain.intents.find(({ slotIds }) => slotIds.includes(theme.id));
  assert.equal(intent.id, "kid_birthday_party");
  const mood = chain.tasks.find(({ intentId, devices }) => intentId === intent.id && devices.includes("light_01"));
  assert.ok(chain.needs.some(({ text, taskIds }) => text === mood.need && taskIds.includes(mood.id)));
  assert.equal(mood.time.story, "손님이 오면");
  assert.equal(mood.values.find(({ device }) => device === "light_01").value.hue, 330);

  const light = chain.devices.find(({ logicalId }) => logicalId === "light_01");
  assert.equal(light.chosen, true);
  assert.deepEqual(light.state, observed);
  assert.deepEqual(light.traces, [mood.id]);
  assert.equal(chain.tasks.find(({ id }) => id === light.traces[0]).intentId, intent.id);
  assert.equal(chain.items.find(({ id }) => id === theme.basis[0]), topper);
  assert.equal(chain.devices.find(({ logicalId }) => logicalId === "fridge_01").chosen, false);
  assert.ok(chain.reports.some(({ taskId, deviceId, kind }) => taskId === mood.id && deviceId === light.logicalId && kind === "run"));
  assert.deepEqual(chain.reports.find(({ taskId, kind }) => taskId === mood.id && kind === "restore").deviceIds, ["light_01", "display_01"]);
  assert.equal(chain.timeline.before.story, "토 13:30");
  assert.equal(chain.timeline.party.story, "토 14:00");
  assert.equal(chain.timeline.events.guest_arrived.story, "토 13:52");
});

test("groceries retain the item notices with an empty preparation chain", () => {
  const episode = fixture("ep_9150", "episode");
  const rationale = fixture("ep_9150", "rationale");
  const plan = fixture("ep_9150", "plan.v1");
  const hubPlan = Object.fromEntries(plan.tasks.map(({ task_id, actions }) => [task_id, actions]));
  const chain = buildChain({ episode, rationale, hubPlan });

  assert.equal(chain.intent, null);
  assert.deepEqual(chain.none, { reason: rationale.none_reason });
  assert.deepEqual(chain.slots, []);
  assert.deepEqual(chain.needs, []);
  assert.deepEqual(chain.tasks, []);
  assert.deepEqual(chain.item_tasks, episode.item_tasks);
  assert.ok(chain.items.every(({ unbundled }) => unbundled));
  assert.equal(chain.devices.length, 9);
  assert.ok(chain.devices.every(({ chosen, traces }) => !chosen && traces.length === 0));
  assert.deepEqual(chain.funnel, { items: 6, similar: 12, bundled: 0, unbundled: 6, intents: 0, tasks: 0, cardLines: 0, devices: 1 });
  assert.equal(chain.cardReady, true);
});

test("birthday house traces follow the current timeline step", () => {
  const input = birthday();
  const beforePlan = houseDevicePresentation(buildChain({ ...input, hubPlan: undefined }),
    scenes.find(({ id }) => id === "guests").focusDevices);
  assert.ok([...beforePlan.values()].every(({ resting, evidence }) => !resting && !evidence));

  const notice = input.rationale.item_tasks[0];
  const snapshot = { devices: [{ logical_id: "fridge_01", values: { show_notice: notice.text } }] };
  const chain = buildChain({ ...input, snapshot });
  const mood = "손님 오시면 공주 분위기 화면·조명 ← 테마: 디즈니 공주 ← 케이크 토퍼";
  const safety = "아이 안전 모드 (인덕션 잠금·전기포트 차단)";
  const expected = {
    plan: {},
    delivery: { fridge_01: `${notice.text} ← 딸기` },
    clean: { cleaner_01: "손님 오기 전 거실 청소 ← 손님: 손님 여러 명 ← 고깔모자" },
    before: { cooktop_01: safety, plug_kettle: safety },
    guests: { light_01: mood, display_01: mood },
    party: { oven_01: "오븐 컵케이크 설정 대기 ← 활동: 컵케이크 굽고 꾸미기 ← 컵케이크 믹스" },
    end: {},
  };
  assert.deepEqual(scenes.map(({ id }) => id), Object.keys(expected));
  for (const { id, focusDevices } of scenes) {
    const house = houseDevicePresentation(chain, focusDevices);
    assert.deepEqual([...house].filter(([, label]) => label.resting).map(([device]) => device),
      ["fridge_01", "purifier_01", "styler_01"]);
    const traces = Object.fromEntries([...house].filter(([, label]) => label.evidence)
      .map(([device, label]) => [device, label.evidence]));
    assert.deepEqual(traces, expected[id], id);
  }
  assert.equal(houseDevicePresentation(buildChain(input), ["fridge_01"]).get("fridge_01").evidence, "");
  snapshot.devices[0].values.show_notice = "다른 주문 안내";
  assert.equal(houseDevicePresentation(buildChain({ ...input, snapshot }), ["fridge_01"]).get("fridge_01").evidence, "");
});

test("a named basis item supports a house trace only when it identifies a slot", () => {
  const input = birthday();
  const safety = input.rationale.tasks.find(({ task_id }) => task_id === "t_safe#2");
  const trace = () => houseDevicePresentation(buildChain(input), ["cooktop_01"]).get("cooktop_01").evidence;

  safety.need = "휘핑크림을 쓰기 전에 주방을 안전하게 준비";
  assert.equal(trace(), `${safety.line} ← 활동: 컵케이크 굽고 꾸미기 ← 휘핑크림`);
  safety.need = "케이크 토퍼를 준비하는 동안 주방을 안전하게";
  assert.equal(trace(), safety.line);
  safety.need = "행사 동안 주방을 안전하게";
  assert.equal(trace(), safety.line);
  input.rationale.tasks.push({ ...safety, task_id: "t_other#8" });
  assert.equal(trace(), "");
});

test("the grocery house rests all nine devices even with an observed item notice", () => {
  const episode = fixture("ep_9150", "episode");
  const rationale = fixture("ep_9150", "rationale");
  const hubPlan = fixture("ep_9150", "plan.v1");
  const snapshot = { devices: [{ logical_id: "fridge_01", values: { show_notice: rationale.item_tasks[0].text } }] };
  const house = houseDevicePresentation(buildChain({ episode, rationale, hubPlan, snapshot }));
  assert.equal(house.size, 9);
  for (const presentation of house.values()) {
    assert.deepEqual(presentation, { focused: false, resting: true, evidence: "" });
  }
});

test("focused house labels reserve space and overlapping value tags drop at both demo screen sizes", () => {
  // The house keeps these stage dimensions while the outer frame scales to fit.
  const width = 1256, height = 653;
  const markers = [
    { id: "display_01", focused: true, x: 410, y: 300, width: 570, height: 58 },
    { id: "light_01", focused: true, x: 530, y: 300, width: 570, height: 58 },
    { id: "cleaner_01", x: 290, y: 302, width: 146, height: 32 },
    { id: "fridge_01", x: 1100, y: 600, width: 164, height: 32 },
    { id: "cooktop_01", x: 880, y: 580, width: 124, height: 32 },
    { id: "plug_kettle", x: 887, y: 585, width: 152, height: 32 },
    { id: "oven_01", x: 1000, y: 374, width: 152, height: 32 },
  ];
  const labels = layoutHouseLabels(markers, width, height);
  assert.deepEqual(labels.map(({ id }) => id), ["display_01", "light_01", "oven_01", "cooktop_01", "fridge_01"]);
  for (const [screenWidth, screenHeight] of [[1920, 1080], [1440, 900]]) {
    const scale = Math.min(screenWidth / 1920, screenHeight / 1080);
    const pixels = (position) => Math.round(position * scale);
    for (const [index, label] of labels.entries()) {
      assert.ok(label.left >= 8 && label.right <= width - 8);
      assert.ok(label.top >= 46 && label.top + label.height <= height - 44);
      for (const other of labels.slice(index + 1)) {
        assert.ok(pixels(label.right) <= pixels(other.left) || pixels(other.right) <= pixels(label.left) ||
          pixels(label.top + label.height) <= pixels(other.top) || pixels(other.top + other.height) <= pixels(label.top));
      }
    }
  }
});

test("rebased card, timeline and Hub records share story-time labels", () => {
  const input = birthday();
  const card = structuredClone(input.card);
  card.starts_at = "2026-11-20T11:42:11+09:00";
  card.lines[0].when.time = "2026-11-20T11:39:11+09:00";
  card.lines[1].when.time = "2026-11-20T11:41:11+09:00";
  const scheduled = card.lines[0].when.time;
  const dispatched = "2026-11-20T11:40:45+09:00";
  const storyTime = {
    timing: {
      before_start_default_min: { normal: 90, demo: 3 },
      guest_window_before_min: { normal: 30, demo: 1 },
      end_fallback_min: { normal: 180, demo: 10 },
    },
    guestWindows: { "t_mood#3": { to: "2026-11-20T11:42:41+09:00" } },
  };
  const completion = { kind: "event", id: "ev_clean_completed", delivered: true };
  const hubLedger = [
    { kind: "run", status: "completed", device: "cleaner_01", at: dispatched, reports: [completion],
      timing: { plan_id: input.episode.episode_id, task_id: "t_clean#1", scheduled_at: scheduled, observed_at: dispatched, anchor: "start" } },
    { kind: "event", event_type: "cleaner.completed", device: "cleaner_01", at: dispatched, reports: [completion] },
    { kind: "event", event_type: "guest_arrived", at: "2026-11-20T11:41:41+09:00" },
  ];
  const chain = buildChain({ ...input, card: [card], hubLedger, storyTime });

  assert.equal(chain.cards[0].lines[0].time.story, "토 12:30");
  assert.equal(chain.tasks[0].time.derivation, "토 14:00 일정 → 90분 전 → 토 12:30");
  assert.deepEqual(chain.timeline.clean, { at: scheduled, story: "토 12:30" });
  assert.equal(chain.timeline.before.story, "토 13:30");
  assert.equal(chain.reports[0].taskId, "t_clean#1");
  assert.equal(chain.reports[0].story, "토 12:30");
  assert.equal(chain.reports.length, 2);
  assert.equal(chain.reports[1].story, chain.timeline.events.guest_arrived.story);
  assert.equal(chain.reports[1].story, "토 13:59");
  assert.equal(chain.reports[1].taskId, null);
  assert.equal(chain.reports[1].deviceId, null);
});

test("pending judgment, cardless intents and missing Hub plans preserve distinct evidence", () => {
  const { episode, rationale } = birthday();
  const pending = buildChain({ episode });
  assert.equal(pending.none, undefined);
  assert.equal(pending.hasRationale, false);
  assert.deepEqual(pending.item_tasks, episode.item_tasks);

  const first = rationale.intents[0];
  const judgment = { ...rationale, intents: [first, { ...first, card_id: null }] };
  const chain = buildChain({ episode, rationale: judgment });
  assert.equal(chain.intents.length, 2);
  assert.equal(new Set(chain.slots.map(({ id }) => id)).size, 8);
  assert.ok(chain.tasks.every(({ intentId, values }) => intentId === chain.intent.id && values.length === 0));
  assert.equal(chain.funnel.devices, 0);
  assert.equal(chain.cardReady, false);
});
