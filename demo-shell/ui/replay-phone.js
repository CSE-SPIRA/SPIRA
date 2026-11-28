// The phone during a Server replay of a kept run (README: Replay). The App does not run in a replay, so the phone
// shows what that order's phone would have shown: the order photos (kept on the demo machine only when the run was
// kept, order_photos.py), the items S1 read, then the card S5 made. Nothing is generated.
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

function photoUrl(episode, number) {
  return `/demo/api/photos/${encodeURIComponent(episode)}/${number}`;
}

// The kept photos of the run (demo machine only): one large with its position, a row to switch between them.
function photoBlock(episode, count, selected) {
  const shown = selected >= 1 && selected <= count ? selected : 1;
  const row = count > 1 ? `<div class="rp-thumbs">${Array.from({ length: count }, (_, i) =>
    `<button type="button" data-photo="${i + 1}" aria-label="사진 ${i + 1} 보기" aria-pressed="${i + 1 === shown}">
      <img src="${photoUrl(episode, i + 1)}" alt=""></button>`).join("")}</div>` : "";
  return `<figure class="rp-photo"><img src="${photoUrl(episode, shown)}" alt="공유한 주문 화면 ${shown}">
    ${count > 1 ? `<span class="rp-count">${shown}/${count}</span>` : ""}</figure>${row}`;
}

function smallPhotos(episode, count) {
  return count ? `<div class="rp-thumbs small">${Array.from({ length: count }, (_, i) =>
    `<img src="${photoUrl(episode, i + 1)}" alt="공유한 주문 화면 ${i + 1}">`).join("")}</div>` : "";
}

// shown: how far the log has shown this order (0 = S1 … 4 = S5, -1 = nothing yet).
// photos: { count, selected } of the photos kept on this machine for the run (count 0 when none).
export function replayPhone(trace, shown, photos = { count: 0, selected: 1 }) {
  const episode = trace?.episode_id ?? "";
  const items = traceStage(trace, "s1")?.result?.items ?? [];
  const cards = traceStage(trace, "s5")?.result?.cards ?? [];
  const count = photos.count ?? 0;
  const itemCount = items.filter(({ masked }) => !masked).length;
  let body;
  if (shown >= 4 && stageFinished(trace, "s5")) {
    body = cards.length
      ? `<h2>준비 카드</h2>${cards.map(cardBlock).join("")}`
      : `<h2>준비 카드 없음</h2><p class="rp-note">이번 주문에는 집을 준비할 일이 없었어요.</p>`;
    const label = [count ? `주문 사진 ${count}장` : "", `주문 품목 ${itemCount}개`].filter(Boolean).join(" · ");
    body += `<details class="rp-order"><summary>${label}</summary>${smallPhotos(episode, count)}${itemList(items)}</details>`;
  } else {
    const picture = count ? photoBlock(episode, count, photos.selected)
      : `<p class="rp-note">주문 화면 캡처를 공유했어요. 이 실행의 사진은 보관하지 않았어요.</p>`;
    body = shown >= 0 && stageFinished(trace, "s1")
      ? `<h2>품목 ${itemCount}개를 읽었어요</h2>${picture}${itemList(items)}`
      : `<h2>주문을 보냈어요</h2>${picture}`;
  }
  return `<p class="rp-tag">재현 · 저장된 주문</p>${body}`;
}
