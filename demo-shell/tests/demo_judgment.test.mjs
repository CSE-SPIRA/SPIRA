import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { buildJudgment } from "../ui/judgment.js";
import {
  calendarMarkup, calendarTimes, comparisonText, contextMarkup, extractionMarkup, intentMarkup, itemComparison, judgmentBeatLine, similarMarkup, slotsMarkup,
} from "../ui/judgment-view.js";

function recorded(id) {
  const load = (name) => JSON.parse(readFileSync(new URL(`../../contracts/fixtures/${id}/${name}.json`, import.meta.url)));
  const episode = load("episode");
  const items = episode.items.map(({ type: id, name, qty, item_id: sourceId }) => ({ id, name, qty, sourceId }));
  return { items, rationale: load("rationale"), itemTaskCount: episode.item_tasks.length };
}

test("birthday assembles the recorded item comparisons, calendar, cases, slot basis and verdict", () => {
  const { items, rationale, itemTaskCount } = recorded("ep_9031");
  const { unusual_items, calendar, kb_counts, kb_examples } = rationale.evidence;
  const [intent] = rationale.intents;
  const [extract, context, slots, verdict, tasks] =
    buildJudgment(items, rationale, { extract: true, tasks: true, itemTaskCount });

  assert.equal(extract.items.length, 9);
  assert.equal(extract.maskedCount, rationale.masked_count);
  assert.deepEqual(context.comparison, unusual_items);
  assert.deepEqual(itemComparison(context.comparison, "딸기"), { kind: "unusual", label: "평소보다 많음" });
  assert.deepEqual(itemComparison(context.comparison, "세탁 세제"), { kind: "usual", label: "평소 사던 것" });
  assert.deepEqual(context.candidates, calendar);
  assert.equal(calendarTimes(calendar[0]), "토 14:00–17:00 · 2일 뒤");
  assert.doesNotMatch(calendarMarkup(calendar), /판단에 사용/);
  assert.deepEqual(slots.calendarUse, [{ event: calendar[0], items: ["케이크 토퍼"] }]);
  assert.match(calendarMarkup(calendar, slots.calendarUse), /판단에 사용[\s\S]*케이크 토퍼/);

  assert.deepEqual(context.counts, kb_counts);
  assert.deepEqual(context.examples, kb_examples);
  const similarText = similarMarkup(context);
  assert.match(similarText, /아이 생일 파티 <b>9건[\s\S]*홈베이킹 <b>2건[\s\S]*의도 없음 <b>1건/);
  assert.match(similarText, /6개 중 4개 같음/);
  assert.match(similarText, /<mark>고깔모자<\/mark>/);
  assert.match(similarText, /<span>답례품 봉투<\/span>/);

  assert.deepEqual(slots.groups[0].map(({ key, value, basis }) => [key, value, basis]),
    Object.keys(intent.situation).map((key) => [key, intent.situation[key], intent.basis[key]]));
  const slotText = slotsMarkup(slots.groups, items, calendar);
  assert.match(slotText, /토 생일[\s\S]*케이크 토퍼[\s\S]*행사/);
  assert.match(slotText, /가구 유형[\s\S]*손님 여러 명/);
  assert.equal((slotText.match(/class="thread"/g) ?? []).length, 8);
  assert.deepEqual(verdict.intents, rationale.intents);
  assert.deepEqual(verdict.unbundled, rationale.unbundled);
  assert.deepEqual(tasks, { id: "tasks", count: 4, itemTaskCount: 2 });
});

test("groceries show the recorded no-intent reason, unbundled items and fridge notices without slots", () => {
  const { items, rationale, itemTaskCount } = recorded("ep_9150");
  const beats = buildJudgment(items, rationale, { extract: true, tasks: true, itemTaskCount });
  assert.deepEqual(beats.map(({ id }) => id), ["items", "context", "intent", "tasks"]);
  const verdict = beats.find(({ id }) => id === "intent");
  assert.equal(verdict.reason, rationale.none_reason);
  assert.deepEqual(verdict.unbundled, rationale.unbundled);
  assert.match(intentMarkup(verdict, items, []), /의도 없음[\s\S]*평소 사는 장보기 물건뿐이고[\s\S]*준비와 따로 본 물건/);
  assert.deepEqual(beats.slice(-2).map(judgmentBeatLine), ["의도 없음", "할 일 0개 · 냉장고 안내 2개"]);
});

test("partial responses do not reveal absent beats, and simultaneous arrival retains the same order", () => {
  const { items, rationale } = recorded("ep_9031");
  assert.deepEqual(buildJudgment(items, rationale, { extract: false, tasks: true }), []);
  assert.deepEqual(buildJudgment(items, null, { extract: true, maskedCount: 2 }), [
    { id: "items", items, maskedCount: 2 },
  ]);
  const full = buildJudgment(items, rationale, { extract: true, tasks: true });
  assert.deepEqual(full.map(({ id }) => id), ["items", "context", "slots", "intent", "tasks"]);
  const partial = buildJudgment(items, { ...rationale, intents: [], unbundled: [], tasks: [], item_tasks: [] },
    { extract: true, tasks: false });
  assert.deepEqual(partial, full.slice(0, 2));
  assert.deepEqual(partial.map(judgmentBeatLine), ["물건 9종 읽음", "가까운 일정 후보 2건 · 비슷한 다른 집 주문 12건"]);
  assert.deepEqual(buildJudgment(items, rationale, { extract: true, tasks: false }), full.slice(0, 4));
});

for (const [comparison, explanation, kind] of [
  [null, "이 집의 평소 주문 비교가 꺼져 있어요.", ""],
  [{ status: "insufficient" }, "평소 주문이 적어 비교할 수 없어요.", ""],
  [{ status: "all_usual" }, "모두 평소에 사는 물건이에요.", "usual"],
]) {
  test(`the home comparison distinguishes ${comparison?.status ?? "null"}`, () => {
    const { items, rationale } = recorded("ep_9150");
    rationale.evidence.unusual_items = comparison;
    const beat = buildJudgment(items, rationale, { extract: true }).find(({ id }) => id === "context");
    assert.deepEqual(beat.comparison, comparison);
    assert.equal(comparisonText(beat.comparison), explanation);
    assert.equal(itemComparison(beat.comparison, items[0].id).kind, kind);
  });
}

test("an empty calendar and a sparse-case note remain visible evidence", () => {
  const { items, rationale } = recorded("ep_9150");
  const note = "비슷한 사례가 거의 없음";
  Object.assign(rationale.evidence, { kb_counts: null, kb_examples: [], kb_note: note });
  const beats = buildJudgment(items, rationale, { extract: true });
  const context = beats.find(({ id }) => id === "context");
  assert.deepEqual(context.candidates, []);
  assert.match(contextMarkup(context, "목 21:00"), /가까운 일정 후보가 없어요/);
  assert.equal(context.counts, null);
  assert.deepEqual(context.examples, []);
  assert.match(similarMarkup(context), new RegExp(note));
  assert.equal(judgmentBeatLine(context), "가까운 일정 후보 0건");
});

test("comparison reasons use fixed Server patterns and preserve unknown text", () => {
  const reasons = [
    ["이 집이 산 적 없는 종류", "평소 안 사던 품목"],
    ["90일에 1번 산 드문 물건", "드물게 사던 품목"],
    ["평소 1.5개 → 이번 3개", "평소보다 많음"],
    ["평소 3개 → 이번 1개", "평소 3개 → 이번 1개"],
    ["다른 사유", "다른 사유"],
  ];
  for (const [why, label] of reasons) {
    assert.deepEqual(itemComparison({ items: [{ item: "딸기", why }] }, "딸기"), { kind: "unusual", label });
  }
});


test("extraction uses supplied columns and leaves absent values empty", () => {
  const table = extractionMarkup([
    { name: "딸기 <사진>", qty: 2, group: "food", label: "care", attributes: { pack: "cold" } },
    { name: "케이크", qty: null },
  ], 0);
  assert.match(table, /딸기 &lt;사진&gt;<\/td><td>2<\/td><td>food<\/td><td>care<\/td><td>\{&quot;pack&quot;:&quot;cold&quot;\}/);
  assert.match(table, /케이크<\/td>(<td><\/td>){4}/);
  assert.match(table, /가린 품목 0개/);
  assert.match(extractionMarkup(undefined, undefined), /extraction-table[\s\S]*skeleton-bar/);
});

test("context puts order time, household fields, calendar and KB evidence on one card", () => {
  const { items, rationale } = recorded("ep_9031");
  rationale.evidence.household_types = ["3~4인", "부부·커플"];
  const context = buildJudgment(items, rationale, { extract: true }).find(({ id }) => id === "context");
  const markup = contextMarkup(context, "목 21:00");
  assert.equal((markup.match(/class="context-card"/g) ?? []).length, 1);
  assert.match(markup, /주문 시각[\s\S]*목 21:00[\s\S]*가구 유형[\s\S]*3~4인 · 부부·커플/);
  assert.match(markup, /평소와 다른 물건[\s\S]*가까운 일정[\s\S]*토 14:00–17:00[\s\S]*비슷한 다른 집 주문[\s\S]*6개 중 4개 같음/);
});
