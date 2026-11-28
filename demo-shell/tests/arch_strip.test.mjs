import assert from "node:assert/strict";
import test from "node:test";

import { ARCH_NODES, ARCH_STAGES, archLayout, archState, archStrip } from "../ui/arch-strip.js";
import { stepState } from "../ui/flow.js";

const trace = (states) => ({ episode_id: "ep_1", stages: ["s1", "s2", "s3", "s4", "s5"]
  .map((name, i) => ({ name, state: states[i] ?? "pending", done_s: null, llm: null, result: null })) });
const lit = (html) => [...html.matchAll(/class="arch-node on[^"]*" data-node="(\w+)"/g)].map(([, id]) => id);
const main = (html) => html.match(/class="arch-node on main" data-node="(\w+)"/)?.[1];
const labels = (html) => [...html.matchAll(/class="arch-label"[^>]*>([^<]*)</g)].map(([, text]) => text);

test("each judgment stage lights its own parts and links, and only those", () => {
  const t = trace(["done", "done", "done", "done", "done"]);
  const expect = {
    s1: [["app", "server", "llm"], "llm", ["주문 캡처", "주문 추출"]],
    s2: [["server", "db", "kb"], "db", ["이 집 기록 · 비슷한 사례 검색"]],
    s3: [["server", "llm"], "llm", ["주문 · 맥락 · 사례 → 의도"]],
    s4: [["server", "llm"], "llm", ["의도 · 이 집 기기 → 할 일"]],
    s5: [["app", "server", "hub"], "server", ["준비 카드", "기기 계획"]],
  };
  for (const [stage, [nodes, mainNode, words]] of Object.entries(expect)) {
    const html = archStrip(t, stage);
    assert.deepEqual(lit(html).sort(), [...nodes].sort(), stage);
    assert.equal(main(html), mainNode, stage);
    assert.deepEqual(labels(html), words, stage);
    assert.equal((html.match(/class="arch-link"/g) ?? []).length, ARCH_STAGES[stage].links.length, stage);   // no skeleton links
    assert.match(html, new RegExp(`data-arch="${stage}"`));
  }
});

test("the strip shows no values: they stay in the log", () => {
  const html = archStrip({ ...trace(["done"]), stages: [{ name: "s1", state: "done", done_s: 18.6,
    llm: { calls: 1, ms: 18000, input_tokens: 15000, output_tokens: 194 }, result: { items: [] } }] }, "s1");
  assert.doesNotMatch(html, /tok|18\.0s|LLM 1회/);
});

test("a failed stage turns its links red; a replay is marked; other stages and no stage draw nothing", () => {
  assert.match(archStrip(trace(["done", "failed"]), "s2"), /class="arch-strip arch-failed"/);
  assert.equal(archState(trace(["done", "running"]), "s2"), "running");
  assert.match(archStrip(trace(["done"]), "s1", { replay: true }), /is-replay/);
  assert.equal(archStrip(trace([]), "s6"), "");
  const idle = archStrip(null, null);                       // waiting for an order: the parts, nothing lit
  assert.match(idle, /data-arch="idle"/);
  assert.deepEqual([lit(idle), (idle.match(/class="arch-link"/g) ?? []).length, /arch-field/.test(idle)], [[], 0, false]);
  assert.match(archStrip(null, "s1"), /arch-pending/);
});

test("joined parts sit next to each other on one plate; the strip fits its width", () => {
  const at = archLayout(1280);
  const last = ARCH_NODES.at(-1);
  assert.ok(at[last.id].x + last.w <= 1280.5);
  assert.equal(at.kb.x - (at.db.x + at.db.w), 28);
  assert.equal(at.home.x - (at.hub.x + at.hub.w), 28);
  assert.ok(at.hub.x - (at.kb.x + at.kb.w) > 28);
  assert.equal((archStrip(trace([]), "s1").match(/class="arch-plate"/g) ?? []).length, 2);
  assert.match(archStrip(trace(["done", "done"]), "s2"), /M[\d.]+,90 H[\d.]+" marker-end/);   // Knowledge base → DB
});

test("the stepper: done = check, the stage on screen is lit, a reopened stage takes the light and the shown one a ring", () => {
  assert.deepEqual(stepState({ index: 0, current: 1, done: true, time: { done: true, text: "18.6초" }, focus: null, id: "extract" }),
    { done: true, running: false, failed: false, lit: false, shown: false });
  assert.deepEqual(stepState({ index: 2, current: 1, done: false, time: { text: "진행 중 4초" }, focus: null, id: "intent" }),
    { done: false, running: true, failed: false, lit: false, shown: false });
  assert.equal(stepState({ index: 1, current: 1, done: true, time: null, focus: null, id: "context" }).lit, true);
  // Finished at the Server but not shown yet: still being analysed on screen (spinner), not ticked.
  assert.deepEqual(stepState({ index: 2, current: 1, done: false, time: { done: false, text: "결과 도착" }, focus: null, id: "intent" }),
    { done: false, running: true, failed: false, lit: false, shown: false });
  const reopened = (index, id) => stepState({ index, current: 4, done: true, time: null, focus: "context", id });
  assert.equal(reopened(1, "context").lit, true);
  assert.deepEqual([reopened(4, "plan").lit, reopened(4, "plan").shown], [false, true]);
  assert.equal(stepState({ index: 1, current: 1, done: false, time: { text: "실패" }, focus: null, id: "context" }).failed, true);
});
