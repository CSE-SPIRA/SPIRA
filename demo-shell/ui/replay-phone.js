// The phone during a Server replay of a kept run (README: Replay). The App does not run in a replay, so the phone
// shows what that order's phone would have shown, from the stored trace only: the items S1 read, then the card S5
// made. Nothing is generated; the screenshots themselves are never stored, so the first screen says so.
import { esc } from "./markup.js";
import { stageFinished, traceStage } from "./serverlog.js";

const EVENTS = { guest_arrived: "손님 도착", event_end: "행사 끝", "package.brought_in": "택배 들임" };

function when(value) {
  if (value?.time) return value.time.slice(11, 16);
  return EVENTS[value?.event] ?? value?.event ?? "";
}

function itemList(items) {
  const shown = items.filter(({ masked }) => !masked);
  const masked = items.length - shown.length;
  return `<ul class="rp-items">${shown.map(({ name, qty }) =>
    `<li><span>${esc(name ?? "")}</span><span>${esc(String(qty ?? 1))}개</span></li>`).join("")}</ul>` +
    (masked ? `<p class="rp-note">가린 물건 ${masked}개</p>` : "");
}

function cardBlock({ text, lines = [] }) {
  return `<section class="rp-card"><h3>${esc(text ?? "")}</h3><ul>${lines.map((line) =>
    `<li><span class="rp-when${line.when?.time ? "" : " rp-event"}">${esc(when(line.when))}</span><span>${esc(line.text ?? "")}</span></li>`).join("")}</ul></section>`;
}

// shown: how far the log has shown this order (0 = S1 … 4 = S5, -1 = nothing yet).
export function replayPhone(trace, shown) {
  const items = traceStage(trace, "s1")?.result?.items ?? [];
  const cards = traceStage(trace, "s5")?.result?.cards ?? [];
  let body;
  if (shown >= 4 && stageFinished(trace, "s5")) {
    body = cards.length
      ? `<h2>준비 카드</h2>${cards.map(cardBlock).join("")}`
      : `<h2>준비 카드 없음</h2><p class="rp-note">이번 주문에는 집을 준비할 일이 없었어요.</p>`;
    body += `<details class="rp-order"><summary>주문 품목 ${items.filter(({ masked }) => !masked).length}개</summary>${itemList(items)}</details>`;
  } else if (shown >= 0 && stageFinished(trace, "s1")) {
    body = `<h2>품목 ${items.filter(({ masked }) => !masked).length}개를 읽었어요</h2>${itemList(items)}`;
  } else {
    body = `<h2>주문을 보냈어요</h2><p class="rp-note">주문 화면 캡처를 공유했어요. 캡처는 저장하지 않아요.</p>`;
  }
  return `<p class="rp-tag">재현 · 저장된 주문</p>${body}`;
}
