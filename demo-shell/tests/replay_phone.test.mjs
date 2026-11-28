import test from "node:test";
import assert from "node:assert/strict";
import { replayPhone } from "../ui/replay-phone.js";

const trace = {
  episode_id: "ep_40",
  stages: [
    { name: "s1", state: "done", done_s: 14.8, result: { items: [
      { type: "케이크", name: "파미유 미니 딸기 생크림 케익", qty: 1 },
      { type: "풍선", name: "숫자풍선 4", qty: 2 },
      { type: "약", name: null, qty: 1, masked: true }] } },
    { name: "s5", state: "done", done_s: 58.7, result: { plan_version: 1, cards: [
      { card_id: "nc_20", text: "토요일 생일에 맞춰 집을 준비해 둘게요", lines: [
        { text: "거실을 청소해요", when: { time: "2026-11-28T13:57:00+09:00" } },
        { text: "TV와 조명을 핑크빛으로", when: { event: "guest_arrived" } }] }] } },
  ],
};

test("before the log shows S1 the phone says the order was sent and screenshots are not kept", () => {
  const html = replayPhone(trace, -1);
  assert.match(html, /주문을 보냈어요/);
  assert.match(html, /캡처는 저장하지 않아요/);
  assert.doesNotMatch(html, /케익/);
});

test("after S1 the phone lists the stored items, masked ones only as a count", () => {
  const html = replayPhone(trace, 0);
  assert.match(html, /품목 2개를 읽었어요/);
  assert.match(html, /파미유 미니 딸기 생크림 케익/);
  assert.match(html, /2개/);
  assert.match(html, /가린 물건 1개/);
  assert.doesNotMatch(html, /준비 카드/);
});

test("after S5 the phone shows the stored card with times and events", () => {
  const html = replayPhone(trace, 4);
  assert.match(html, /토요일 생일에 맞춰/);
  assert.match(html, /13:57/);
  assert.match(html, /손님 도착/);
  assert.match(html, /재현 · 저장된 주문/);
  assert.match(html, /<details class="rp-order"><summary>주문 품목 2개<\/summary>/);
  assert.doesNotMatch(html, /<details[^>]* open/);
});

test("a stage not finished in the trace is not shown even when the log index is ahead", () => {
  const running = { ...trace, stages: [{ ...trace.stages[0], state: "running" }] };
  assert.match(replayPhone(running, 4), /주문을 보냈어요/);
});
