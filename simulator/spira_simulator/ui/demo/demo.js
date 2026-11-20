// Reasoning uses the Server's app contract. House surfaces use World observations.
import { createFlow } from "./flow.js";
import { createHouse, hsvColor, replaceHouseMarkers, TV_SCENES } from "../house/house.js";
import { buildChain, houseDevicePresentation } from "./chain.js";

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[character]);
const rows = (items, render) => items.map(render).join("");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const WAYS = { run: "실행", standby: "설정 대기", notice: "안내" };
const OWNERS = { share: "앱 · 공유", card: "앱 · 카드", reasoning: "앱 · 판단 근거", home: "앱 · 우리 집", hub: "Hub 기록", server: "서버 창" };
const ownerTag = (owner) => `<span class="owner-tag">${OWNERS[owner]}</span>`;
const ICONS = {
  딸기: "❋", "컵케이크 믹스": "▤", 휘핑크림: "▣", "세탁 세제": "▥", 로션: "◒",
  풍선: "◯", "케이크 토퍼": "✧", 고깔모자: "△", "아이싱 펜": "╱",
  우유: "▤", 계란: "◕", 바지락: "◫", 휴지: "⊙", "주방 세제": "▥",
};
// These are sample inputs for the share action. Judgment always comes back from the Server.
const SAMPLE_ORDERS = {
  birthday: ["설향 딸기 500g (냉장) × 2", "OO 컵케이크 믹스", "동물성 휘핑크림 500ml × 1",
    "OO 액체 세탁세제 3L × 1", "OO 베이비 로션 300ml × 1", "파티 풍선 세트 × 1",
    "디즈니 공주 케이크 토퍼 × 1", "파티 고깔모자 × 6", "아이싱 펜 × 1"],
  groceries: ["우유 1L × 1", "계란 10구 × 1", "바지락 400g × 1", "딸기 500g × 1", "두루마리 휴지 × 1", "주방 세제 × 1"],
};

const state = {
  config: null, scenes: null, flow: null, house: null, scale: 1, page: "reason",
  order: "birthday", step: 0, mapOpen: false, sharing: false, transitioning: false,
  episodeId: null, episode: null, rationale: null, cards: [], capture: null, reader: null,
  homeStep: 0, homeBusy: false, applied: new Set(), hub: null, snapshot: null, houseMarkup: "", chain: buildChain(),
};

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(response.status);
  return response.json();
}

function notice(text = "") {
  $("notice").textContent = text;
}

function refreshChain() {
  const { episodeId, episode, rationale, cards, hub, snapshot, config } = state;
  state.chain = buildChain({
    episode: episode ?? (episodeId ? { episode_id: episodeId } : null), rationale, card: cards,
    hubPlan: hub?.plan_actions?.[episodeId], hubLedger: hub?.ledger, snapshot,
    storyTime: {
      timing: config.story_timing, guestWindows: hub?.guest_windows?.[episodeId], fixtureShares: config.fixture_shares,
    },
  });
  if (state.house) updateHousePresentation(timeline()[state.homeStep]);
}

function paintTheme(text, theme) {
  const index = theme ? text.indexOf(theme) : -1;
  if (index < 0) return esc(text);
  return esc(text.slice(0, index)) + `<span class="theme-text">${esc(theme)}</span>` + esc(text.slice(index + theme.length));
}

function plannedLight() {
  return state.chain.tasks.flatMap(({ values }) => values)
    .find(({ device, cmd }) => device === "light_01" && cmd === "color")?.value;
}

function flowCounts({ evidence, funnel, hasEpisode, hasRationale, hasHubPlan, cardReady }) {
  return [
    hasEpisode && "주문 1건",
    hasEpisode && `물건 ${funnel.items}`,
    hasRationale && (evidence.kbCounts ? `비슷한 주문 ${funnel.similar}` : `일정 ${evidence.calendar.length}`),
    hasRationale && [
      hasEpisode && `묶음 ${funnel.bundled} · 제외 ${funnel.unbundled}`,
      `의도 ${funnel.intents}`,
    ].filter(Boolean).join("\n"),
    hasRationale && `할 일 ${funnel.tasks}`,
    cardReady && `카드 ${funnel.cardLines}줄`,
    hasHubPlan && `기기 ${funnel.devices}`,
  ].map((count) => count || "");
}

function sampleOrder() {
  const canvas = document.createElement("canvas");
  canvas.width = 650;
  canvas.height = 880;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fffefa";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#192e28";
  ctx.font = '700 46px "Apple SD Gothic Neo", sans-serif';
  ctx.fillText("주문 상세", 32, 65);
  ctx.fillStyle = "#51665c";
  ctx.font = '500 26px "Apple SD Gothic Neo", sans-serif';
  ctx.fillText("예시 주문", 33, 111);
  ctx.font = '600 29px "Apple SD Gothic Neo", sans-serif';
  SAMPLE_ORDERS[state.order].forEach((item, index) => {
    const y = 150 + index * 75;
    ctx.fillStyle = "#e4ede3";
    ctx.fillRect(32, y, 46, 46);
    ctx.fillStyle = "#192e28";
    ctx.fillText(item, 97, y + 32);
    ctx.fillStyle = "#edeee5";
    ctx.fillRect(32, y + 59, 586, 2);
  });
  return canvas;
}

function receipt(items) {
  return `<ul class="receipt-list">${rows(items, (item) => `<li class="receipt-row" data-item="${esc(item.sourceId)}">
    <span class="item-icon" aria-hidden="true">${ICONS[item.id] || "·"}</span>
    <span>${esc(item.name)}</span><span class="receipt-qty">${item.qty == null ? "" : esc(item.qty) + "개"}</span>
  </li>`)}</ul>`;
}

function phoneMap() {
  const { devices: inventory, hasHubPlan } = state.chain;
  const devices = inventory.filter((device) => device.modeled);
  return `<div class="phone-head"><h2>우리 집</h2><p>연결된 기기 ${devices.length}대</p></div>
    <div class="app-map" aria-label="우리 집 평면 지도">
      ${rows([["entrance", "현관"], ["living_room", "거실"], ["kitchen", "주방"]], ([room, name]) => `<div class="app-room">
        <strong>${name}</strong>${room === "entrance" ? '<span class="app-door">출입문</span>' : ""}
        ${rows(devices.filter((device) => device.room === room), ({ logicalId, label, chosen }) => {
          const resting = hasHubPlan && !chosen;
          return `<div class="app-device${resting ? " resting" : ""}" data-device="${esc(logicalId)}">
            <span class="app-device-icon" role="img"${resting ? ` aria-label="${esc(label)} · 쉬는 중"` : ' aria-hidden="true"'}></span>
            ${resting ? "" : `<span>${esc(label)}</span>`}
          </div>`;
        })}
      </div>`)}
    </div>`;
}

function intentSlots(intent) {
  return intent?.slotIds.map((id) => state.chain.slots.find((slot) => slot.id === id)) ?? [];
}

function themeFor(intent) {
  return intentSlots(intent).find(({ key }) => key === "theme")?.value;
}

function phoneCard(card) {
  const theme = themeFor(state.chain.intents.find((intent) => intent.cardId === card.card_id));
  return `<div class="app-card"><h3>${paintTheme(card.text, theme)}</h3><ul>${rows(card.lines, (line) =>
    `<li><span class="app-check" aria-label="${line.checked ? "선택됨" : "꺼짐"}">${line.checked ? "✓" : "○"}</span>
      <span>${esc(line.text)}<small>${esc(line.time.story || "시간을 기다리는 중")}</small></span></li>`)}</ul></div>`;
}

function noticeCards() {
  return rows(state.chain.item_tasks, ({ item, text }) => `<div class="app-card"><h3>${esc(item)}</h3><p>${esc(text)}</p></div>`);
}

function renderPhone(scene) {
  const plan = ["plan", "hub"].includes(scene.id);
  const order = scene.id === "share";
  const { hasEpisode, items, cards, orderClock, cardClock, cardReady, item_tasks } = state.chain;
  $("phone-time").textContent = plan ? cardClock : orderClock;
  $("phone-owner").textContent = OWNERS[state.mapOpen ? "home" : plan ? "card" : "share"];
  $("phone-order").textContent = plan ? "준비" : "주문";
  $("phone-order").setAttribute("aria-pressed", String(!state.mapOpen));
  $("phone-map").setAttribute("aria-pressed", String(state.mapOpen));
  let screen;
  if (state.mapOpen) {
    screen = phoneMap();
  } else if (order) {
    const capture = !state.capture && !hasEpisode ? sampleOrder().toDataURL() : state.capture;
    screen = `<div class="phone-head"><h2>주문 상세</h2></div>
      ${capture ? `<div class="scan-picture"><img src="${esc(capture)}" alt="공유할 주문 화면"></div>` : receipt(items)}
      <div class="phone-share order-actions">
        <button type="button" id="sample"${state.sharing ? " disabled" : ""}>예시 주문으로 공유 <span aria-hidden="true">↗</span></button>
        <label>스크린샷 공유<input type="file" id="files" accept="image/png,image/jpeg" multiple${state.sharing ? " disabled" : ""}></label>
      </div>`;
  } else if (plan && cards.length) {
    screen = `<div class="phone-head"><h2>준비 카드</h2><p>${esc(cards[0].updatedStory)}</p></div>
      ${rows(cards, phoneCard)}`;
  } else if (plan && cardReady) {
    screen = `<div class="phone-head"><h2>${item_tasks.length ? "냉장고 안내" : "준비 카드 없음"}</h2></div>${noticeCards()}`;
  } else {
    const title = plan ? "준비 카드를 기다려요" : hasEpisode ? "주문을 읽었어요" : "주문을 읽고 있어요";
    screen = `<div class="phone-reading"><h2>${title}</h2>
      <div class="scan-picture">${hasEpisode ? receipt(items) : state.capture
        ? `<img src="${esc(state.capture)}" alt="공유한 주문 화면">` : ""}</div></div>`;
  }
  const content = $("phone-content");
  if (content.dataset.content === screen) return;
  content.dataset.content = screen;
  const scroll = content.scrollTop;
  content.innerHTML = screen;
  content.scrollTop = scroll;
  if ($("sample")) $("sample").onclick = () => shareSample(1);
  if ($("files")) $("files").onchange = (event) => {
    const files = [...event.target.files].slice(0, 3);
    if (files.length) share(files, 1);
  };
}

function quantityCards(items) {
  return `<div class="item-grid">${rows(items, (item) => `<div class="item-tile" data-item="${esc(item.sourceId)}">
    <span class="item-icon" aria-hidden="true">${ICONS[item.id] || "·"}</span>
    <div><strong>${esc(item.id)}</strong><small>${esc(item.name)}</small></div>
    <span class="count">${item.qty == null ? "수량 미확인" : esc(item.qty) + "개"}</span>
  </div>`)}</div>`;
}

function calendarLabel(event) {
  return `${event.day}요일 ${event.tags.join(" · ")} 일정`;
}

function contextStage({ evidence, funnel }) {
  const { calendar, unusual, kbCounts, kbExamples, kbNote } = evidence;
  const counts = kbCounts ?? [];
  const unusualItems = unusual?.items ?? [];
  return `<div class="context-grid">
    <div class="context-left">
      <section class="panel"><h2>가까운 일정</h2>${calendar.length
        ? rows(calendar, (event) => `<div class="calendar-row"><b>${esc(calendarLabel(event))}</b>
          <time>${esc(event.start)}–${esc(event.end)}</time></div>`)
        : '<p class="subtext">이 주문과 연결할 일정이 없어요.</p>'}</section>
      <section class="panel"><h2>평소와 달랐던 물건</h2>${unusualItems.length
        ? `<ul class="unusual-list">${rows(unusualItems, ({ item, why }) =>
          `<li><strong>${esc(item)}</strong><small>${esc(why)}</small></li>`)}</ul>`
        : `<p class="subtext">${unusual?.status === "all_usual" ? "모두 평소에 사는 물건이에요." : "표시할 평소 주문 근거가 없어요."}</p>`}
      </section>
    </div>
    <section class="panel kb-panel">${ownerTag("server")}<h2>비슷한 다른 집 주문 ${funnel.similar}건</h2>
      ${counts.length ? `<div class="retrieval-bar" aria-hidden="true">${rows(counts, ({ n }) => `<i style="flex:${Number(n)}"></i>`)}</div>
        <div class="retrieval-key">${rows(counts, ({ name, n }) => `<span>${esc(name)} <b>${esc(n)}건</b></span>`)}</div>` : ""}
      ${rows(kbExamples, ({ intent_text, intent_id, overlap }) => `<div class="example">
        <strong>${esc(intent_text || counts.find((count) => count.intent_id === intent_id)?.name || "비슷한 주문")}</strong>
        <span class="pill">${esc(overlap.k)} / ${esc(overlap.n)} 겹침</span>
        <p>${esc(overlap.items.join(" · "))}</p>
      </div>`)}
      ${kbNote ? `<p class="subtext">${esc(kbNote)}</p>` : ""}
    </section>
  </div>`;
}

function basisChip(value, theme = false) {
  const event = state.chain.evidence.calendar.find((entry) => entry.id === value);
  const item = state.chain.items.find((entry) => entry.id === value);
  const label = event ? calendarLabel(event) : (theme ? item?.name : item?.id) || value;
  return `<span class="clue">${esc(label)}${item?.qty > 1 ? ` <small>${esc(item.qty)}개</small>` : ""}</span>`;
}

function intentStage({ intents, unbundled, none, evidence, items }) {
  const cards = intents.length ? rows(intents, (intent) => {
    const slots = intentSlots(intent);
    const theme = slots.find(({ key }) => key === "theme")?.value;
    const event = evidence.calendar.find((entry) => entry.id === intent.calendarEvent);
    return `<div class="intent-grid">
      <section><div class="proof-head"><span>주문과 일정에서 찾은 근거</span><span>짐작한 상황</span></div>
        <div class="proof-rows">${rows(slots, ({ key, label, value, basis }, index) => `<div
          class="proof-row${value ? "" : " empty"}" style="--wait:${index * 250}ms">
          <div class="proof-source">${rows(basis, (id) => basisChip(id, key === "theme"))}</div>
          <i class="thread${basis.length && value ? "" : " missing"}" aria-hidden="true"></i>
          <div class="situation ${key === "theme" && value ? "theme" : ""}"><small>${label}</small>${esc(value || "—")}</div>
        </div>`)}</div>
      </section>
      <div class="verdict"><small>주문의 의도</small><h2>${paintTheme(intent.text, theme)}</h2>
        ${event ? `<p>${esc(calendarLabel(event))} · <time>${esc(event.start)}–${esc(event.end)}</time></p>` : ""}
      </div>
      ${intent.basis.length ? `<p class="basis-note"><b>함께 본 근거</b><span>${rows(intent.basis, (value) => basisChip(value))}</span></p>` : ""}
    </div>`;
  }) : `<div class="intent-grid plain">
    <section class="panel"><h2>이번에 읽은 물건</h2>${quantityCards(items)}</section>
    <div class="verdict"><small>주문의 의도</small><h2>의도 없음</h2>${none?.reason ? `<p>${esc(none.reason)}</p>` : ""}</div>
  </div>`;
  return cards + (unbundled.length ? `<p class="basis-note"><b>준비와 따로 본 물건</b><span>${esc(unbundled.join(" · "))}</span></p>` : "");
}

function itemNotices() {
  const notices = state.chain.item_tasks;
  return notices.length ? `<div class="notices"><h2>냉장고 안내</h2>${rows(notices, ({ item, text }) =>
    `<article><b>${esc(item)}</b>${esc(text)}</article>`)}</div>` : "";
}

function translation(tasks, intents) {
  const actions = tasks.flatMap(({ values }) => values);
  const light = actions.find(({ cmd }) => cmd === "color")?.value;
  const scene = actions.find(({ cmd }) => cmd === "play_mood")?.value?.scene;
  const oven = actions.find(({ cmd }) => cmd === "set_cook_standby")?.value;
  const color = hsvColor(light ?? undefined);
  const values = [
    color && `<li><strong>조명</strong><span class="swatch" style="--concept:${color}" aria-hidden="true"></span>
      색조 ${light.hue}° · 채도 ${light.saturation} · 밝기 ${light.brightness}</li>`,
    scene && `<li><strong>TV</strong>${esc(TV_SCENES[scene] || scene)} 화면</li>`,
    Number.isFinite(oven?.temp_c) && Number.isFinite(oven?.minutes) &&
      `<li><strong>오븐</strong>${oven.temp_c}℃ · ${oven.minutes}분</li>`,
  ].filter(Boolean);
  if (!values.length) return "";
  const moodTask = tasks.find(({ values }) => values.some(({ cmd }) => cmd === "color" || cmd === "play_mood"));
  const theme = themeFor(intents.find(({ id }) => id === moodTask?.intentId));
  return `<aside class="palette">${theme ? `<small>고른 분위기</small><h2>${esc(theme)}</h2>
    <span class="palette-arrow" aria-hidden="true">↓</span>` : ""}<ul>${values.join("")}</ul></aside>`;
}

function tasksStage({ tasks, intents, devices, funnel, item_tasks }) {
  if (!funnel.tasks) return `<div class="panel"><h2>집 준비 ${funnel.tasks}개 · 냉장고 안내 ${item_tasks.length}개</h2></div>${itemNotices()}`;
  const palette = translation(tasks, intents);
  return `<div class="task-layout${palette ? "" : " without-palette"}"><div class="task-table" role="table" aria-label="준비할 일">
    <div class="task-row" role="row"><span role="columnheader">필요한 준비</span><span aria-hidden="true"></span>
      <span role="columnheader">할 일</span><span role="columnheader">기기</span><span role="columnheader">방식</span></div>
    ${rows(tasks, (task) => {
      const timing = task.time.derivation || task.time.story;
      return `<div class="task-row" role="row">
        <span class="task-need" role="cell">${esc(task.need)}</span><span class="task-arrow" aria-hidden="true">→</span>
        <span class="task-line" role="cell">${esc(task.line)}${timing ? `<small>${esc(timing)}</small>` : ""}</span>
        <span class="task-device" role="cell">${esc(task.devices.map((id) =>
          devices.find(({ logicalId }) => logicalId === id)?.label).join(" · "))}</span>
        <span class="task-way" role="cell">${esc(WAYS[task.way] || task.way)}</span>
      </div>`;
    })}
  </div>${palette}</div>${itemNotices()}`;
}

function planStage({ cards, cardReady }) {
  if (cards.length) return rows(cards, (card) => `<section class="plan-card">
    <ul class="plan-list">${rows(card.lines, (line) => `<li><time>${esc(line.time.story || "시간을 기다리는 중")}</time>
      <span>${esc(line.text)}${line.note ? `<small>${esc(line.note)}</small>` : ""}</span></li>`)}</ul>
  </section>`);
  return cardReady ? (itemNotices() || '<p class="lead">이번 주문에는 준비 카드가 없어요.</p>')
    : '<p class="lead">준비 카드를 기다리고 있어요.</p>';
}

function stageBody(scene) {
  const { chain } = state;
  const { hasEpisode, hasRationale, items, intents, item_tasks } = chain;
  if (scene.id === "share") return hasEpisode ? `<div class="hero-foot"><span class="pill">공유한 주문</span> ${items.length}종</div>` : "";
  if (scene.id === "extract") {
    if (items.length) return quantityCards(items);
    return `<p class="lead">${hasRationale ? "표시할 품목이 없어요." : "주문을 읽는 중이에요."}</p>`;
  }
  if (!hasRationale) return '<p class="lead">판단을 기다리고 있어요.</p>';
  if (scene.id === "context") return contextStage(chain);
  if (scene.id === "intent") return intentStage(chain);
  if (scene.id === "tasks") return tasksStage(chain);
  if (scene.id === "plan") return planStage(chain);
  const label = intents.map(themeFor).find(Boolean);
  const color = hsvColor(plannedLight() ?? undefined);
  return `<div class="handoff-card">${color ? `<span class="palette-dot" id="source-dot"
    style="--concept:${color}" aria-hidden="true"></span>` : ""}
    <div>${esc(label || (item_tasks.length ? "냉장고 안내" : "집 허브"))}</div></div>`;
}

let flightVersion = 0;

async function flyItems(version) {
  if (motion.matches || !Element.prototype.animate || state.mapOpen) return;
  const sources = new Map([...$("phone-content").querySelectorAll(".receipt-row")]
    .map((item) => [item.dataset.item, item]));
  const targets = [...$("stage-copy").querySelectorAll(".item-tile")]
    .filter((target) => sources.has(target.dataset.item));
  if (!targets.length || !sources.size) return;
  const slide = Number.parseFloat(getComputedStyle($("frame")).getPropertyValue("--phone-motion"));
  const waits = targets.map((target) =>
    target.animate([{ opacity: 0 }, { opacity: 0 }], { duration: slide, fill: "both" }));
  await sleep(slide);
  waits.forEach((animation) => animation.cancel());
  if (version !== flightVersion || state.mapOpen || state.page !== "reason") return;
  const frame = $("frame").getBoundingClientRect();
  targets.forEach((target, index) => {
    const source = sources.get(target.dataset.item)?.getBoundingClientRect();
    const end = target.getBoundingClientRect();
    if (!source?.width || !end.width) return;
    const clone = target.cloneNode(true);
    clone.classList.add("flight");
    clone.setAttribute("aria-hidden", "true");
    const scale = state.scale;
    Object.assign(clone.style, {
      left: `${(end.left - frame.left) / scale}px`, top: `${(end.top - frame.top) / scale}px`,
      width: `${end.width / scale}px`, height: `${end.height / scale}px`, transformOrigin: "top left",
    });
    $("frame").append(clone);
    const timing = { delay: index * 53, duration: 460, easing: "ease-out", fill: "both" };
    const incoming = clone.animate([
      { transform: `translate(${(source.left - end.left) / scale}px,${(source.top - end.top) / scale}px) scale(.5)`, opacity: 0 },
      { opacity: 1, offset: .2 }, { transform: "none", opacity: 1 },
    ], timing);
    const uncover = target.animate([{ opacity: 0 }, { opacity: 0, offset: .88 }, { opacity: 1 }], timing);
    incoming.onfinish = () => { clone.remove(); uncover.cancel(); };
  });
}

function renderReason() {
  const scene = state.scenes.reason[state.step];
  const { chain } = state;
  const layout = $("reason-layout");
  const copy = $("stage-copy");
  const stepChanged = layout.dataset.stage !== scene.id;
  layout.dataset.stage = scene.id;
  state.flow.setCounts(flowCounts(chain));
  state.flow.setStage(scene.node);
  renderPhone(scene);
  const headline = ["share", "plan", "hub"].includes(scene.id);
  let title = scene.title;
  if (scene.id === "extract" && chain.items.length) {
    title = scene.readyTitle.replace("{count}", chain.items.length);
  }
  if (scene.id === "plan" && chain.cardReady) title = chain.cards.length ? scene.readyTitle : scene.noCardTitle;
  const owner = { share: "share", plan: "card", hub: "hub" }[scene.id] ?? "reasoning";
  const markup = `<div class="copy-enter"><header class="stage-head">${ownerTag(owner)}
    <h1${headline ? ' class="headline"' : ""}>${esc(title)}</h1><p class="lead">${esc(scene.lead)}</p>
    </header>${stageBody(scene)}</div>`;
  if (copy.dataset.content !== markup) {
    copy.dataset.content = markup;
    copy.innerHTML = markup;
    if (stepChanged) copy.scrollTop = 0;
    document.querySelectorAll(".flight").forEach((clone) => clone.remove());
    const version = ++flightVersion;
    if (scene.id === "extract") flyItems(version);
  }
  renderControls();
}

function setStep(step) {
  const next = Math.max(0, Math.min(step, state.scenes.reason.length - 1));
  if (next !== state.step) state.mapOpen = false;
  state.step = next;
  renderReason();
}

function applyCapture(url) {
  if (state.capture) URL.revokeObjectURL(state.capture);
  state.capture = url;
}

async function shareSample(step) {
  if (state.sharing) return false;
  state.sharing = true;
  renderControls();
  try {
    const blob = await new Promise((resolve) => sampleOrder().toBlob(resolve, "image/png"));
    if (!blob) throw new Error("No sample image");
    return await share([new File([blob], "sample-order.png", { type: "image/png" })], step, state.order);
  } catch {
    notice("예시 주문 화면을 만들지 못했어요.");
    return false;
  } finally {
    state.sharing = false;
    renderReason();
  }
}

async function share(files, step, sample = null) {
  state.sharing = true;
  notice("주문을 보내는 중이에요.");
  renderControls();
  const form = new FormData();
  for (const file of files) form.append("images", file, file.name || "order.png");
  if (sample && state.config.fixture) form.append("sample", sample);
  let accepted;
  try {
    accepted = await api("/demo/api/order", { method: "POST", body: form, signal: AbortSignal.timeout(35000) });
    applyCapture(URL.createObjectURL(files[0]));
    state.applied.clear();
    state.homeStep = 0;
    state.mapOpen = false;
    readEpisode(accepted.episode_id);
    setStep(step);
    notice();
    return true;
  } catch (error) {
    notice(`주문을 보내지 못했어요. (${error.message})`);
    return false;
  } finally {
    state.sharing = false;
    renderReason();
    if (accepted) $("next").focus({ preventScroll: true });
  }
}

async function readEpisode(id) {
  state.reader?.abort();
  const controller = new AbortController();
  state.reader = controller;
  state.episodeId = id;
  state.episode = state.rationale = null;
  state.cards = [];
  refreshChain();
  const server = "/demo/api/server/v1";
  const episodePath = `${server}/episodes/${encodeURIComponent(id)}`;
  const cardPath = `${server}/households/${encodeURIComponent(state.config.household_id)}/cards`;
  let previous = "";
  for (let attempt = 0; attempt < 600 && !controller.signal.aborted; attempt++) {
    const options = { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]) };
    const [episode, rationale, cards] = await Promise.allSettled([
      api(episodePath, options), api(`${episodePath}/rationale`, options), api(cardPath, options),
    ]);
    if (controller.signal.aborted) return;
    if (episode.status === "fulfilled") {
      state.episode = episode.value;
    } else if (!state.episode && !state.sharing && state.page === "reason" && episode.reason.message === "404") {
      notice("아직 이 주문 기록을 열 수 없어요. 예시 주문을 공유해 주세요.");
    }
    if (rationale.status === "fulfilled") state.rationale = rationale.value;
    if (cards.status === "fulfilled") {
      const current = cards.value.cards.filter((card) => card.episode_id === id);
      if (current.length) state.cards = current;
    }
    refreshChain();
    if (state.episode?.status === "closed" && state.chain.hasRationale && !state.chain.cardReady) {
      const archive = await api(`${cardPath}?since=1970-01-01T00%3A00%3A00Z`, options).catch(() => null);
      if (controller.signal.aborted) return;
      if (archive) {
        state.cards = archive.cards.filter((card) => card.episode_id === id);
        refreshChain();
      }
    }
    const fingerprint = JSON.stringify([state.episode, state.rationale, state.cards]);
    if (fingerprint !== previous) {
      previous = fingerprint;
      if (state.page === "reason" && !state.transitioning) renderReason();
      if (state.page === "house") {
        renderLedger();
        renderTimeline();
      }
    }
    if (state.chain.cardReady) return;
    await sleep(1000);
  }
}

async function chooseOrder(order) {
  if (order === state.order || state.sharing || state.transitioning) return;
  const previous = state.order;
  state.order = order;
  if (!state.episodeId && state.step === 0) {
    applyCapture(null);
    state.mapOpen = false;
    renderReason();
    return;
  }
  if (!await shareSample(Math.max(1, state.step))) {
    state.order = previous;
    renderReason();
  }
}

function timeline() {
  const scene = state.scenes.house;
  return state.chain.hasRationale && !state.chain.funnel.tasks ? scene.slice(0, 2) : scene;
}

function houseMoment(scene) {
  const times = state.chain.timeline;
  return (scene.event ? times.events[scene.event] : times[scene.id]) ?? { story: "" };
}

function updateHousePresentation(scene) {
  state.house?.setPresentation(houseDevicePresentation(state.chain, scene?.focusDevices));
}

function decorateHouseLabel(label, { evidence }) {
  let trace = label.querySelector(".marker-trace");
  if (!trace && evidence) {
    trace = document.createElement("span");
    trace.className = "marker-trace";
    label.append(trace);
  }
  if (trace) {
    trace.textContent = evidence ?? "";
    trace.hidden = !evidence;
  }
}

function renderTimeline() {
  const scenes = timeline();
  state.homeStep = Math.min(state.homeStep, scenes.length - 1);
  const current = scenes[state.homeStep];
  updateHousePresentation(current);
  const { at, story } = houseMoment(current);
  const arrived = current.id !== "plan" || at;
  $("home-time").textContent = story;
  $("home-title").textContent = arrived ? current.heading : "집에서 이어지는 준비";
  $("home-caption").textContent = current.lead;
  $("home").setAttribute("aria-busy", String(state.homeBusy));
  const steps = $("timeline");
  const markup = rows(scenes, (scene, index) => `<li><button type="button" data-step="${index}"
    ${index === state.homeStep ? 'aria-current="step"' : ""}
    ${index < state.homeStep ? 'class="past"' : ""}
    ${state.homeBusy || index > state.homeStep + 1 ? "disabled" : ""}>
    ${["plan", "delivery"].includes(scene.id)
      ? `<span>${esc(houseMoment(scene).story || scene.title)}</span>`
      : `<time>${esc(houseMoment(scene).story)}</time><span>${esc(scene.title)}</span>`}
    </button></li>`);
  if (steps.dataset.content !== markup) {
    const focused = steps.contains(document.activeElement);
    steps.dataset.content = markup;
    steps.innerHTML = markup;
    if (focused) (steps.querySelector('[aria-current="step"]:enabled') || $("next")).focus({ preventScroll: true });
  }
  renderControls();
}

function showEntrance(entry) {
  state.house?.setEntrance({ signal: entry, packagePresent: entry === "package" });
}

function directHouse(instant = false) {
  const scene = timeline()[state.homeStep];
  state.house?.focus(state.scenes.cameras[scene.camera], { instant });
  showEntrance(scene.entry && (state.applied.has(scene.action) || houseMoment(scene).at) ? scene.entry : "");
}

async function goHouse(index) {
  const scene = timeline()[index];
  if (!scene || state.homeBusy || state.transitioning || index === state.homeStep || index > state.homeStep + 1) return;
  notice();
  if (scene.action && !state.applied.has(scene.action) && !houseMoment(scene).at) {
    state.homeBusy = true;
    renderTimeline();
    try {
      await api(`/demo/api/home/${scene.action}`, { method: "POST", signal: AbortSignal.timeout(8000) });
      state.applied.add(scene.action);
    } catch (error) {
      notice(`집에 사건을 보내지 못했어요. (${error.message})`);
      return;
    } finally {
      state.homeBusy = false;
      renderTimeline();
    }
  }
  state.homeStep = index;
  directHouse();
  renderTimeline();
}

const BY = { spira: "SPIRA", user: "사람", hub: "허브", unknown: "주체 미확인" };

function renderLedger() {
  $("ledger-label").textContent = state.config.hub ? "이 집이 본 일" : "허브 연결 없음";
  const ledger = $("ledger");
  const markup = rows([...state.chain.reports].reverse(), (row) => {
    const reports = row.reports || [];
    const sent = reports.length ? (reports.every(({ delivered }) => delivered) ? "서버에 보냄" : "보내는 중") : "";
    const source = row.kind === "event" && row.deviceId && row.by === "unknown" ? "기기 보고" : BY[row.by] || row.by;
    return `<li class="ledger-row"><div><time datetime="${esc(row.at)}">${esc(row.story)}</time>
      <strong>${row.label === "—" ? "" : esc(row.label) + " · "}${esc(row.what)}</strong>
      <span class="pill actor">${esc(source)}</span></div>
      ${sent ? `<p><span class="sent">${sent}</span></p>` : ""}</li>`;
  }) || '<li class="subtext">기록을 기다리고 있어요.</li>';
  if (ledger.dataset.content !== markup) {
    ledger.dataset.content = markup;
    ledger.innerHTML = markup;
  }
}

function acceptHub(hub) {
  state.hub = hub;
  refreshChain();
  if (state.page === "reason") {
    if (!state.transitioning) renderReason();
    return;
  }
  renderLedger();
  renderTimeline();
  const scene = timeline()[state.homeStep];
  if (scene.entry && houseMoment(scene).at) showEntrance(scene.entry);
}

async function refreshSnapshot() {
  state.snapshot = await api("/sim/snapshot", { signal: AbortSignal.timeout(2500) });
  refreshChain();
}

async function refreshHouseMarkers() {
  const response = await fetch("/sim/viewer?fragment=true", { signal: AbortSignal.timeout(2500) });
  if (!response.ok) throw new Error(response.status);
  const fragment = new DOMParser().parseFromString(await response.text(), "text/html");
  const markers = fragment.getElementById("viewer-markers");
  if (markers.outerHTML !== state.houseMarkup) {
    state.houseMarkup = markers.outerHTML;
    replaceHouseMarkers($("viewer-markers"), markers);
    state.house?.setMarkers(markers);
  }
  $("device-legend").textContent = fragment.getElementById("device-legend")?.textContent ?? "";
}

async function refreshHub() {
  acceptHub(await api("/demo/api/hub", { signal: AbortSignal.timeout(2500) }));
}

async function pollHouse() {
  for (;;) {
    if (!state.transitioning) {
      const inHouse = state.page === "house";
      const stage = state.scenes.reason[state.step].id;
      const reads = inHouse ? [refreshSnapshot(), refreshHouseMarkers()] : [];
      if (state.config.hub && (inHouse || (state.episodeId && ["tasks", "plan", "hub"].includes(stage)))) {
        reads.push(refreshHub());
      }
      await Promise.allSettled(reads);
    }
    await sleep(800);
  }
}

function openHouseView() {
  $("home").hidden = false;
  if (!state.house && !$("world").hasChildNodes()) {
    try {
      state.house = createHouse($("world"), $("view"), { decorateLabel: decorateHouseLabel });
      state.house.setMarkers($("viewer-markers"));
    } catch (error) {
      const message = document.createElement("p");
      message.className = "error";
      message.textContent = "이 화면에서 입체 집을 열 수 없어요.";
      $("world").append(message);
      console.error(error);
    }
  }
  renderTimeline();
  state.house?.resize();
  directHouse(true);
  renderLedger();
}

function showPage(page) {
  const focusedPanel = (page === "reason" ? $("home") : $("reason")).contains(document.activeElement);
  state.page = page;
  $("reason").hidden = page !== "reason";
  $("home").hidden = page !== "house";
  $("orders").hidden = page !== "reason";
  $("compare").hidden = page !== "house";
  document.querySelectorAll("[data-page]").forEach((button) =>
    button.setAttribute("aria-pressed", String(button.dataset.page === page)));
  if (page === "house") openHouseView();
  else renderReason();
  if (focusedPanel) (document.querySelector(`[data-page="${page}"]`)).focus({ preventScroll: true });
}

async function waitForHandoff() {
  if (!state.config.hub || !state.episodeId) return;
  const deadline = performance.now() + 16000;
  do {
    await refreshHub();
    const { hasRationale, funnel, item_tasks, timeline } = state.chain;
    if (timeline.plan.at) return;
    if (hasRationale && !funnel.tasks && !item_tasks.length) return;
    await sleep(800);
  } while (performance.now() < deadline);
}

async function enterHouse() {
  if (state.transitioning) return;
  state.transitioning = true;
  notice("집 허브가 받은 계획을 확인하고 있어요.");
  renderControls();
  try {
    await waitForHandoff().catch(() => {});
    renderReason();
    $("home").classList.add("introducing");
    $("home").inert = true;
    openHouseView();
    await Promise.allSettled([refreshSnapshot(), refreshHouseMarkers()]);
    const source = $("source-dot");
    const anchor = state.house?.anchor("light_01");
    const color = hsvColor(plannedLight() ?? undefined);
    if (color && source && anchor && !motion.matches && Element.prototype.animate) {
      const frame = $("frame").getBoundingClientRect();
      const center = (box, x, y) => [
        (box.left - frame.left + box.width * x) / state.scale,
        (box.top - frame.top + box.height * y) / state.scale,
      ];
      const [x0, y0] = center(source.getBoundingClientRect(), .5, .5);
      const [x1, y1] = center($("view").getBoundingClientRect(), anchor.x, anchor.y);
      const transform = (x, y, scale) => `translate(${x - 30}px,${y - 30}px) scale(${scale})`;
      const orb = $("match-orb");
      orb.style.setProperty("--concept", color);
      orb.hidden = false;
      const duration = Number.parseFloat(getComputedStyle($("frame")).getPropertyValue("--handoff-motion"));
      const animation = orb.animate([
        { transform: transform(x0, y0, 1), opacity: 1 },
        { transform: transform(x0 - 115, y0 - 20, 13), opacity: .92, offset: .39 },
        { transform: transform(x1, y1, 2.6), opacity: .94, offset: .73 },
        { transform: transform(x1, y1, .58), opacity: 0 },
      ], { duration, easing: "cubic-bezier(.47,.02,.28,1)", fill: "both" });
      const fade = $("reason").animate([{ opacity: 1 }, { opacity: 1, offset: .30 }, { opacity: 0 }],
        { duration, fill: "both" });
      await animation.finished;
      $("reason").hidden = true;
      animation.cancel();
      fade.cancel();
    } else if (!motion.matches && Element.prototype.animate) {
      await $("reason").animate([{ opacity: 1 }, { opacity: 0 }], { duration: 400 }).finished;
    }
  } finally {
    $("match-orb").hidden = true;
    $("home").classList.remove("introducing");
    $("home").inert = false;
    state.transitioning = false;
    notice();
    showPage("house");
    $("next").focus({ preventScroll: true });
  }
}

function renderControls() {
  const inHouse = state.page === "house";
  const blocked = state.sharing || state.transitioning || state.homeBusy;
  $("previous").disabled = blocked || (inHouse ? state.homeStep === 0 : state.step === 0);
  $("next").disabled = blocked || (inHouse ? state.homeStep >= timeline().length - 1
    : !state.config.server && !state.episodeId);
  $("next").textContent = !inHouse && state.scenes.reason[state.step].id === "hub" ? "집으로 →" : "다음 →";
  document.querySelectorAll("[data-order]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.order === state.order));
    button.disabled = blocked || !state.config.server;
  });
  for (const id of ["compare", "sample", "files"]) {
    if ($(id)) $(id).disabled = blocked || (id !== "compare" && !state.config.server);
  }
  document.querySelectorAll("[data-page]").forEach((button) => { button.disabled = blocked; });
}

function move(delta) {
  if (state.sharing || state.transitioning || state.homeBusy) return;
  if (state.page === "house") {
    goHouse(state.homeStep + delta);
  } else if (!state.episodeId && delta > 0) {
    if (state.config.server) shareSample(Math.max(1, state.step));
  } else if (state.scenes.reason[state.step].id === "hub" && delta > 0) {
    enterHouse();
  } else {
    setStep(state.step + delta);
  }
}

function fit() {
  const frame = $("frame");
  state.scale = Math.min(innerWidth / frame.offsetWidth, innerHeight / frame.offsetHeight);
  frame.style.setProperty("--scale", state.scale);
  state.house?.resize();
}

async function boot() {
  [state.config, state.scenes] = await Promise.all([api("/demo/api/config"), api(new URL("./scenes.json", import.meta.url))]);
  state.flow = createFlow($("route-list"), state.scenes.flow);
  $("fixture").hidden = !state.config.fixture;
  $("compressed-time").hidden = !state.config.story_timing;
  $("orders").addEventListener("click", (event) => {
    const button = event.target.closest("[data-order]");
    if (button) chooseOrder(button.dataset.order);
  });
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.onclick = () => { notice(); showPage(button.dataset.page); };
  });
  $("timeline").addEventListener("click", (event) => {
    const button = event.target.closest("[data-step]");
    if (button) goHouse(Number(button.dataset.step));
  });
  $("phone-map").onclick = () => {
    state.mapOpen = true;
    document.querySelectorAll(".flight").forEach((clone) => clone.remove());
    renderPhone(state.scenes.reason[state.step]);
  };
  $("phone-order").onclick = () => {
    state.mapOpen = false;
    renderPhone(state.scenes.reason[state.step]);
  };
  $("compare").onclick = () => {
    notice();
    setStep(state.scenes.reason.findIndex(({ id }) => id === "intent"));
    showPage("reason");
    $("orders").querySelector('[aria-pressed="true"]').focus({ preventScroll: true });
  };
  $("previous").onclick = () => move(-1);
  $("next").onclick = () => move(1);
  document.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.repeat ||
      event.target.closest("input, textarea, select")) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      move(event.key === "ArrowRight" ? 1 : -1);
    }
  });
  window.addEventListener("resize", fit);
  fit();

  const query = new URLSearchParams(location.search);
  $("frame").toggleAttribute("data-owners", query.get("owners") === "1");
  const id = query.get("episode");
  if (id) {
    if (id === state.scenes.samples.groceries.episode) state.order = "groceries";
    readEpisode(id);
  }
  const step = Number(query.get("step") || 0);
  setStep(Number.isInteger(step) ? step : 0);
  if (query.get("page") === "house") showPage("house");
  else if (!state.config.server) notice("서버 연결 없음");
  pollHouse();
}

boot().catch(() => notice("시연 화면을 불러오지 못했어요."));
