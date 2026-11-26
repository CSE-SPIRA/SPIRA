import assert from "node:assert/strict";
import test from "node:test";

import { serverLog, stageFinished } from "../ui/serverlog.js";
import { clearAppStore, newestNew } from "../ui/app-phone.js";
import { replayAt, replayFromQuery, replayHref, replayMenu } from "../ui/replays.js";

const trace = {
  episode_id: "ep_1", mode: "live", at: null, elapsed_s: 40, finished: false,
  stages: [
    { name: "s1", state: "done", done_s: 14.8, llm: { calls: 1, ms: 13900, input_tokens: 5000, output_tokens: 210 },
      result: { items: [{ item_id: "it_1", name: "설향 딸기 500g", type: "딸기", qty: 2, attributes: [], masked: false },
        { item_id: "it_2", name: null, type: null, qty: 1, attributes: [], masked: true }], error: null } },
    { name: "s2", state: "done", done_s: 16.1, llm: null, result: {
      household_types: ["3~4인"], calendar: [{ id: "c1", tags: ["생일"], day: "토", start: "14:00", end: "17:00", days_after: 2 }],
      unusual_items: { status: "list", items: [{ item: "딸기", why: "평소 1개 → 이번 2개" }] },
      kb: { similar_count: 50, base_total: 30000, note: null, intent_counts: [
        { intent_id: "kid_birthday_party", name: "아이 생일 파티", n: 38, share: 0.76, base_share: 0.02 },
        { intent_id: "x", name: "없는 의도", n: 0, share: 0, base_share: 0.1 }] },
      kb_search: { searched: 200, sim_floor: 0.7, above_floor: 126, used: 50, sims: [0.86],
        top: [{ case_id: "c", sim: 0.86, score: 0.9, intent_id: "kid_birthday_party", intent_text: "t", items: ["풍선"], used: true }] },
      error: null } },
    { name: "s3", state: "running", done_s: null, llm: null, result: null },
    { name: "s4", state: "pending", done_s: null, llm: null, result: null },
    { name: "s5", state: "pending", done_s: null, llm: null, result: null },
  ],
};

test("finished stages fold to one line, the shown stage expands, the next shows its real state", () => {
  const html = serverLog(trace, "s2", 40);
  assert.match(html, /S1 화면 읽기[\s\S]*물건 1종 · 가린 물건 1 · LLM 1회 13.9s · 5,210 tok/);
  assert.match(html, /class="log-current" data-trace="s2"/);
  assert.match(html, /유사도 0.7 초과 126/);
  assert.match(html, /아이 생일 파티<\/span><span class="log-mono">38건/);
  assert.doesNotMatch(html, /없는 의도/);                    // n = 0 rows are left out
  assert.match(html, /의도 추론 중 … 23s/);                  // 40 s now − 16.1 s S2 end
  assert.doesNotMatch(html, /S4 할 일/);
  assert.match(html, /LIVE/);
});

test("before S1 is shown the log waits on S1; a replay is labelled", () => {
  const html = serverLog({ ...trace, at: 5, stages: trace.stages.map((s) => s.name === "s1"
    ? { ...s, state: "running", done_s: null, result: null } : { ...s, state: "pending", done_s: null, result: null }) },
  null, 5, { replay: true });
  assert.match(html, /주문 화면 읽는 중 … 5s/);
  assert.match(html, /재현/);
  assert.equal(stageFinished(trace, "s2"), true);
  assert.equal(stageFinished(trace, "s3"), false);
});

test("a folded stage opens again in place when asked, and S5 says why tasks were left out", () => {
  const html = serverLog(trace, "s2", 40, { open: "s1" });
  assert.match(html, /class="log-current log-opened" data-trace="s1"[\s\S]*설향 딸기 500g/);
  assert.match(html, /data-log-stage="s2"[^>]*aria-expanded="false"[\s\S]*S2 맥락 · RAG[\s\S]*현재/);   // shown stage folds
  assert.equal((html.match(/class="log-current/g) ?? []).length, 1);                                       // one at a time
  const done = { ...trace, stages: trace.stages.map((s) => ({ ...s, state: "done", done_s: s.done_s ?? 50 }))
    .map((s) => s.name === "s5" ? { ...s, result: { cards: [], plan_version: 1, dropped: [
      { task_id: "t_clean#1", source: "situation", line: "손님 오기 전 거실 청소", item: null, reason: "late" }] } } : s) };
  const plan = serverLog(done, "s5", 60);
  assert.match(plan, /준비 카드 없음 · 상황 할 일이 아래 이유로 모두 빠짐/);
  assert.match(plan, /<s>손님 오기 전 거실 청소<\/s>[\s\S]*late · 시각이 이미 지남/);
});

test("the replay head names the run and speed and stops its clock at S5; a live head offers the keep", () => {
  const ended = { ...trace, started_at: "2026-11-26T15:40:00+09:00",
    stages: trace.stages.map((s) => ({ ...s, state: "done", done_s: s.done_s ?? 51, result: s.result ?? {} })) };
  const end = ended.stages.find((s) => s.name === "s5").done_s;
  const replay = serverLog({ ...ended, at: 80 }, "s5", 90, { replay: { speed: 2 } });
  assert.match(replay, /재현 · 11-26 \d\d:40 · 2×/);
  assert.match(replay, new RegExp(`경과 [^<]*`));
  assert.doesNotMatch(replay, /data-keep/);
  assert.equal(serverLog(ended, "s5", 90).match(/data-keep/g).length, 1);
  assert.match(serverLog(ended, "s5", 90, { kept: true }), /재현용 보관됨/);
  assert.doesNotMatch(serverLog(trace, "s1", 20), /data-keep|재현용/);
  assert.ok(end <= 90);
});

test("replay query, clock and menu", () => {
  assert.equal(replayFromQuery(new URLSearchParams("replay_episode=ep_1&speed=4")).speed, 4);
  assert.equal(replayFromQuery(new URLSearchParams("replay_episode=ep_1&speed=3")).speed, 1);
  assert.equal(replayFromQuery(new URLSearchParams("replay_episode=../x")), null);
  const replay = { speed: 2, startedAt: null };
  assert.equal(replayAt(replay, 1000), 0);
  assert.equal(replayAt(replay, 4000), 6);
  assert.equal(replayHref("ep_1", 2), "/demo?replay_episode=ep_1&speed=2");
  const menu = replayMenu([{ episode_id: "ep_1", started_at: "2026-11-26T15:40:00+09:00", duration_s: 51,
    intents: ["kid_birthday_party"], items: 9, parked: true }], 2, { live: true });
  assert.match(menu, /data-replay="ep_1"/);
  assert.match(menu, /data-speed="2" aria-pressed="true"/);
  assert.match(menu, /물건 9개 · 51.0s/);
  assert.match(menu, /라이브로 돌아가기/);
  assert.match(replayMenu([], 1), /보관한 실행이 없어요/);
});

test("S1 attributes show key and value, not an object", () => {
  const html = serverLog({ ...trace, stages: trace.stages.map((s) => s.name === "s1" ? { ...s, result: { ...s.result,
    items: [{ item_id: "it_1", name: "딸기 500g", type: "딸기", qty: 1, masked: false,
      attributes: [{ key: "보관", value: "냉장", source: "냉장" }] }] } } : s) }, "s1", 20);
  assert.match(html, /보관 냉장/);
  assert.doesNotMatch(html, /object Object/);
});

test("app phone: only orders after the first list are followed, and only the App's own keys are cleared", () => {
  const known = new Set(["ep_1"]);
  assert.equal(newestNew([{ episode_id: "ep_1" }], known, null), null);
  assert.equal(newestNew([{ episode_id: "ep_3" }, { episode_id: "ep_2" }, { episode_id: "ep_1" }], known, null), "ep_3");
  assert.equal(newestNew([{ episode_id: "ep_3" }], known, null), null);
  assert.equal(newestNew([{ episode_id: "ep_4" }], known, "ep_4"), null);
  const data = new Map([["flutter.spira.setup", "1"], ["flutter.spira.server-token.v1.x", "t"], ["demo.keep", "1"]]);
  const storage = { get length() { return data.size; }, key: (i) => [...data.keys()][i],
    removeItem: (key) => data.delete(key) };
  assert.equal(clearAppStore(storage), 2);
  assert.deepEqual([...data.keys()], ["demo.keep"]);
});
