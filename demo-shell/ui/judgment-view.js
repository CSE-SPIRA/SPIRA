import { esc, rows, skeletonBars } from "./markup.js";
import { findTag, highlightsMarkup } from "./tags.js";

const ITEM_COLUMNS = ["이름", "수량", "분류", "라벨", "속성"];

export function extractionMarkup(items, maskedCount) {
  const body = items
    ? rows(items, ({ name, qty, group, label, attributes }) => {
        const values = [name, qty, group, label, typeof attributes === "object" && attributes !== null
          ? JSON.stringify(attributes) : attributes];
        return `<tr>${rows(values, (value) => `<td>${esc(value)}</td>`)}</tr>`;
      })
    : `<tr>${ITEM_COLUMNS.map(() => `<td>${skeletonBars(1)}</td>`).join("")}</tr>`.repeat(3);
  return `<table class="extraction-table" aria-label="추출 품목">
    <thead><tr>${rows(ITEM_COLUMNS, (column) => `<th scope="col">${column}</th>`)}</tr></thead>
    <tbody>${body}</tbody>
  </table><p class="masked-count">가린 품목 ${maskedCount == null ? "" : esc(maskedCount) + "개"}</p>`;
}

const COMPARISON = {
  off: "이 집의 평소 주문 비교가 꺼져 있어요.",
  insufficient: "평소 주문이 적어 비교할 수 없어요.",
  all_usual: "모두 평소에 사는 물건이에요.",
};

export function comparisonText(comparison) {
  return COMPARISON[comparison?.status ?? "off"] ?? "평소와 다른 물건";
}

export function itemComparison(comparison, type) {
  const unusual = comparison?.items?.find(({ item }) => item === type);
  if (unusual) return { kind: "unusual", label: reasonLabel(unusual.why) };
  if (comparison?.status === "all_usual" || comparison?.usual?.includes(type)) {
    return { kind: "usual", label: "평소 사던 것" };
  }
  return { kind: "", label: "" };
}

function reasonLabel(reason) {
  if (reason === "이 집이 산 적 없는 종류") return "평소 안 사던 품목";
  if (/^\d+일에 \d+번 산 드문 물건$/.test(reason)) return "드물게 사던 품목";
  const quantities = /^(?:평소) (\d+(?:\.\d+)?)개 → 이번 (\d+)개$/.exec(reason);
  if (quantities && Number(quantities[2]) > Number(quantities[1])) return "평소보다 많음";
  return reason;
}

function eventLabel({ day, tags }) {
  return [day, ...tags].join(" ");
}

export function calendarTimes({ day, start, end, days_after }) {
  const relative = days_after === 0 ? "당일" : `${Math.abs(days_after)}일 ${days_after > 0 ? "뒤" : "전"}`;
  return `${day} ${start}–${end} · ${relative}`;
}

function chip(label, kind = "") {
  return `<span class="clue${kind ? ` ${kind}` : ""}">${esc(label)}</span>`;
}

export function calendarMarkup(candidates, calendarUse, items = []) {
  return `<h2>가까운 일정</h2>${candidates.length ? rows(candidates, (event) => {
    const used = calendarUse?.find((entry) => entry.event.id === event.id);
    return `<div class="calendar-row"${used ? ' data-used' : ""}>
      <div>${event.tags.length ? `<b>${esc(event.tags.join(" · "))}</b>` : ""}
        ${used ? '<small class="calendar-status">판단에 사용</small>' : ""}</div>
      <time>${esc(calendarTimes(event))}</time>
      ${used?.items.length ? `<div class="calendar-links">${rows(used.items, (item) => basisChip(item, items, candidates))}</div>` : ""}
    </div>`;
  }) : '<p class="subtext">가까운 일정 후보가 없어요.</p>'}`;
}

export function similarMarkup({ counts, examples, note }) {
  return `<h2>비슷한 다른 집 주문</h2>
    ${counts?.length ? `<p class="retrieval-key">${rows(counts, ({ name, n }) =>
      `<span>${esc(name)} <b>${esc(n)}건</b></span>`)}</p>` : ""}
    ${rows(examples, ({ intent_text, intent_id, items, overlap }) => `<div class="example">
      <strong>${esc(intent_text || counts?.find((count) => count.intent_id === intent_id)?.name || "비슷한 주문")}</strong>
      <span class="pill">${esc(overlap.n)}개 중 ${esc(overlap.k)}개 같음</span>
      <p>${rows(items, (item) => overlap.items.includes(item) ? `<mark>${esc(item)}</mark>` : `<span>${esc(item)}</span>`)}</p>
    </div>`)}
    ${note ? `<p class="subtext">${esc(note)}</p>` : ""}
    ${!counts?.length && !examples.length && !note ? '<p class="subtext">표시할 비슷한 사례가 없어요.</p>' : ""}`;
}

function basisChip(id, items, calendar, theme = false) {
  const event = calendar.find((entry) => entry.id === id);
  const item = items.find((entry) => [entry.id, entry.sourceId, entry.name].includes(id));
  const label = event ? eventLabel(event) : (theme ? item?.name : item?.id) ?? id;
  return chip(label, event ? "calendar-clue" : id === "가구 유형" ? "household-clue" : "");
}

export function slotsMarkup(groups, items, calendar, tags = []) {
  return `<h2>근거에서 읽은 상황</h2>${rows(groups, (slots) => `<div class="proof-rows">
    ${rows(slots, ({ key, label, value, basis }, index) => `<div class="proof-row" style="--wait:${index * 100}ms">
      <div class="proof-source">${rows(basis, (id) =>
        `<div class="proof-link">${basisChip(id, items, calendar, key === "theme")}<i class="thread" aria-hidden="true"></i></div>`)}</div>
      <div class="situation${key === "theme" && value ? " theme" : ""}"><small>${label}</small>${highlightsMarkup(value || "—", findTag(tags, "slot", key, value))}</div>
    </div>`)}
  </div>`)}`;
}

export function contextMarkup(context, orderClock) {
  const types = context?.householdTypes?.join(" · ") ?? "";
  const comparison = context?.comparison;
  const usual = comparison?.status === "list" ? comparison.usual ?? [] : [];
  return `<article class="context-card">
    <div class="context-order"><strong>주문 시각</strong><time>${esc(orderClock) || (context ? "" : skeletonBars(1))}</time></div>
    <div class="context-columns">
      <section><h2>이 집</h2><div class="context-types"><b>가구 유형</b> ${esc(types)}</div>
        ${context ? `<h3>${comparisonText(comparison)}</h3>
          <ul>${rows(comparison?.items ?? [], ({ item, why }) =>
            `<li>${esc(item)} <small title="${esc(why)}">${esc(itemComparison(comparison, item).label)}</small></li>`)}</ul>
          ${usual.length ? `<p class="context-usual">평소 품목 · ${esc(usual.join(" · "))}</p>` : ""}`
          + calendarMarkup(context.candidates) : `<h3>평소와 다른 물건</h3>${skeletonBars(3)}<h3>가까운 일정</h3>${skeletonBars(2)}`}
      </section>
      <section>${context ? similarMarkup(context) : `<h2>비슷한 다른 집 주문</h2>${skeletonBars(4)}`}</section>
    </div></article>`;
}

export function intentMarkup({ intents, reason, unbundled }, items, calendar, tags = []) {
  const verdicts = intents.length ? rows(intents, (intent) => `<div class="verdict">
    <small>주문의 의도</small><h2>${highlightsMarkup(intent.intent_text, findTag(tags, "intent", intent.intent_id, intent.intent_text))}</h2>
    ${intent.basis.intent.length ? `<div class="intent-basis">${rows(intent.basis.intent, (id) => basisChip(id, items, calendar))}</div>` : ""}
  </div>`) : `<div class="verdict"><h2>의도 없음</h2><p>${esc(reason)}</p></div>`;
  return verdicts + (unbundled.length ? `<div class="basis-note"><b>준비와 따로 본 물건</b>
    <span>${rows(unbundled, (item) => chip(item))}</span></div>` : "");
}

export function judgmentBeatLine(beat) {
  switch (beat?.id) {
    case "items": return `물건 ${beat.items.length}종 읽음`;
    case "context": return `가까운 일정 후보 ${beat.candidates.length}건` + (beat.counts?.length
      ? ` · 비슷한 다른 집 주문 ${beat.counts.reduce((total, { n }) => total + n, 0)}건` : "");
    case "slots": return `상황 단서 ${beat.groups.flat().filter(({ value }) => value).length}개`;
    case "intent": return beat.intents.length ? `의도 ${beat.intents.length}개` : "의도 없음";
    case "tasks": return [`할 일 ${beat.count}개`, beat.itemTaskCount && `냉장고 안내 ${beat.itemTaskCount}개`].filter(Boolean).join(" · ");
    default: return "";
  }
}
