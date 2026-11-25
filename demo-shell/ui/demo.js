// Reasoning uses the Server's app contract. House surfaces use World observations.
import { createFlow, STAGE_NAMES } from "./flow.js";
import { DEVICE_NAMES, END_WORDS, LINE_WORDS, ROOM_NAMES, STATE_WORDS, VERDICT_WORDS } from "/demo/shared/vocabulary.js";
import { buildChain, houseDevicePresentation } from "./chain.js";
import { expectedAction, lineReaction, readProblem, rehearsalControls, shareControls, stageNotice, startedLines } from "./wire.js";
import { buildJudgment, JUDGMENT_STAGES } from "./judgment.js";
import {
  calendarMarkup, comparisonText, intentMarkup, itemComparison, judgmentBeatLine, paintTheme, quantityCards, similarMarkup, slotsMarkup,
} from "./judgment-view.js";
import { esc, rows, setMarkup } from "./markup.js";
import { createRecorder, replayFrames } from "./run.js";
import { withSceneArtwork } from "./artwork/scene.js";
import { findTag, itemIcon, lineWithTag } from "./tags.js";
import { buildMoments, closeView, momentScene, sendScene, worldFacts } from "./scene-rules.js";

document.querySelector('meta[name="theme-color"]').content =
  getComputedStyle(document.documentElement).getPropertyValue("--paper").trim();

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const query = new URLSearchParams(location.search);
const RECORDING = query.get("recording");
const REPLAY = Boolean(RECORDING) || query.get("replay") === "1";
const QUIET_END = { event: "judgment.quiet_end" };
const OWNERS = { share: "앱 · 공유", card: "앱 · 카드", reasoning: "앱 · 판단 근거", home: "앱 · 우리 집", server: "서버 창" };
const ownerTag = (owner) => `<span class="owner-tag">${OWNERS[owner]}</span>`;
const SAMPLE_EPISODES = { birthday: "ep_9031", groceries: "ep_9150" };
const defaultPath = (episode) => episode === "ep_9031" ? "house" : "plan";
// These are sample inputs for the share action. Judgment always comes back from the Server.
const SAMPLE_ORDERS = {
  birthday: ["설향 딸기 500g (냉장) × 2", "OO 컵케이크 믹스", "동물성 휘핑크림 500ml × 1",
    "OO 액체 세탁세제 3L × 1", "OO 베이비 로션 300ml × 1", "파티 풍선 세트 × 1",
    "디즈니 공주 케이크 토퍼 × 1", "파티 고깔모자 × 6", "아이싱 펜 × 1"],
  groceries: ["우유 1L × 1", "계란 10구 × 1", "바지락 400g × 1", "딸기 500g × 1", "두루마리 휴지 × 1", "주방 세제 × 1"],
};

const state = {
  config: null, scenes: null, flow: null, house: null, scale: 1, page: "reason",
  order: "birthday", draft: false, step: 0, mapOpen: false, sharing: false,
  runPath: null, draftPath: null, tags: [],
  episodeId: null, episode: null, rationale: null, rationaleMissing: false, judgment: [], cards: [], capture: null, reader: null,
  cardOpen: false, notifications: new Set(), dismissed: new Set(), started: new Set(),
  reactionPending: null, controlError: "", sharedEpisode: null, recordOpen: false, recordRequested: false, recordVisible: false,
  quietEnd: null, quietRamped: new Set(), clockMissing: false, clockMoments: false,
  readProblems: {}, cardsRead: false,
  auto: null, shownAt: null, homeId: "plan", followGuest: false, homeBusy: false, hub: null, snapshot: null, houseMarkup: "", chain: buildChain(),
  facts: new Map(), pendingClockLines: new Set(), playedMotion: new Set(), appliedScene: null, replayStep: 0,
};

function stamp(story = clockNow() ?? (state.config?.fixture ? null : Date.now())) {
  return [new Date().toISOString(), Number.isFinite(story) ? new Date(story).toISOString() : null];
}

function log(kind, data, at = stamp()) {
  state.record?.(kind, data, ...at);
}

function retryNotice(error, reader) {
  if (state.reader !== reader || reader?.signal.aborted || !reader || readProblem(error.status)) return;
  state.retryUntil = performance.now() + 3500;
  renderStageIndicator();
}

async function observe(kind, path, options, { text = false, transform = (value) => value, read } = {}) {
  const { reader, record } = state;
  try {
    const response = await fetch(path, options);
    if (!response.ok) throw Object.assign(new Error(response.status), { status: response.status });
    const data = transform(await (text ? response.text() : response.json()));
    if (state.reader === reader) {
      const story = kind === "clock" ? Date.parse(data.now ?? data.story_at) : undefined;
      record?.(kind, data, ...stamp(story), read);
    }
    return data;
  } catch (error) {
    if (["episode", "rationale", "cards", "memory", "hub"].includes(kind)) retryNotice(error, reader);
    throw error;
  }
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw Object.assign(new Error(response.status), { status: response.status });
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
    houseDevices: state.houseDevices,
    allowReceiptWithoutShareTime: !config.fixture && state.readProblems.episode === "missing",
    storyTime: {
      timing: config.story_timing, guestWindows: hub?.guest_windows?.[episodeId],
    },
  });
  state.judgment = buildJudgment(state.chain.items, rationale, {
    extract: state.chain.ready.extract && (state.chain.items.length > 0 || !missingJudgment()),
    extractMissing: Boolean(state.readProblems.episode),
    tasks: state.chain.ready.tasks, maskedCount: episode?.masked_count,
    itemTaskCount: state.chain.item_tasks.length,
  });
  renderStageIndicator();
}

function renderStageIndicator() {
  const scene = state.scenes.reason[state.step];
  const stage = state.recordVisible ? "record" : state.page === "house" ? "hub" : scene.id === "share" ? "extract" : scene.id;
  const beat = state.page === "reason" && !stageNotice(stage, state.readProblems)
    ? state.judgment.find(({ id }) => id === scene.beat) : null;
  const waiting = waitingStage(scene);
  if (waiting !== state.waiting?.stage) {
    state.waiting = waiting ? { stage: waiting, since: performance.now() } : undefined;
  }
  const elapsed = state.waiting ? Math.floor((performance.now() - state.waiting.since) / 1000) : 0;
  const subject = { intent: "의도를", hub: "집의 계획 수신을", record: "관찰 결과를" };
  const help = waiting ? `${subject[waiting] ?? STAGE_NAMES[waiting] + "을"} 기다려요 · ${elapsed}초` : "";
  const retry = performance.now() < state.retryUntil ? "연결을 다시 확인해요." : "";
  if (!retry) state.retryUntil = 0;
  const line = [help, judgmentBeatLine(beat), retry].filter(Boolean).join(" · ");
  $("stage-beat").toggleAttribute("data-ending", stage === "record" || waiting === "record" || waiting === "hub");
  const ready = { ...state.chain.ready, record: recordReady() };
  let prior = true;
  for (const id of ["extract", "context", "intent", "tasks", "plan"]) {
    if (stageNotice(id, state.readProblems)) {
      ready[id] = false;
      continue;
    }
    if (id === "plan" && missingJudgment()) break;
    prior = ready[id] = prior && ready[id];
  }
  state.flow(stage, ready, line);

  if (!state.recordFinished && state.record && ((state.recordVisible && recordReady()) ||
      (state.page === "reason" && scene.id === "plan" && state.chain.cardReady && state.runPath === "plan"))) {
    state.recordFinished = true;
    log("finish", { stage: state.recordVisible ? "record" : "plan" });
  }
}

function waitingStage(scene) {
  if (state.page === "house") return state.recordRequested && !state.recordVisible ? "record" : null;
  if (!state.episodeId || state.draft) return null;
  if (scene.id === "plan") return stageNotice("plan", state.readProblems) ? null : !state.chain.cardReady ? "plan"
    : state.runPath === "house" && !state.chain.ready.hub ? "hub" : null;
  if (state.shownAt === null) return scene.id === "share" ? "extract" : scene.id;
  if (!MANUAL && performance.now() < state.shownAt + stageDwell()) return null;
  const next = nextReasonStep();
  return reasonReady(next) ? null : state.scenes.reason[next].id;
}

async function exchange(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => null);
  return { status: response.status, ok: response.ok, body };
}

function sampleOrder() {
  const canvas = document.createElement("canvas");
  canvas.width = 650;
  canvas.height = 880;
  const ctx = canvas.getContext("2d");
  const tokens = getComputedStyle(document.documentElement);
  ctx.fillStyle = tokens.getPropertyValue("--surface").trim();
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = tokens.getPropertyValue("--ink").trim();
  ctx.font = '700 46px "Apple SD Gothic Neo", sans-serif';
  ctx.fillText("주문 상세", 32, 65);
  ctx.fillStyle = tokens.getPropertyValue("--muted").trim();
  ctx.font = '500 26px "Apple SD Gothic Neo", sans-serif';
  ctx.fillText("예시 주문", 33, 111);
  ctx.font = '600 29px "Apple SD Gothic Neo", sans-serif';
  SAMPLE_ORDERS[state.order].forEach((item, index) => {
    const y = 150 + index * 75;
    ctx.fillStyle = tokens.getPropertyValue("--green-soft").trim();
    ctx.fillRect(32, y, 46, 46);
    ctx.fillStyle = tokens.getPropertyValue("--ink").trim();
    ctx.fillText(item, 97, y + 32);
    ctx.fillStyle = tokens.getPropertyValue("--soft").trim();
    ctx.fillRect(32, y + 59, 586, 2);
  });
  return canvas;
}

function receipt(items) {
  return `<ul class="receipt-list">${rows(items, (item) => `<li class="receipt-row" data-item="${esc(item.sourceId)}">
    ${itemIcon(state.itemTypes, item.id)}
    <span>${esc(item.name)}</span><span class="receipt-qty">${item.qty == null ? "" : esc(item.qty) + "개"}</span>
  </li>`)}</ul>`;
}

function phoneMap() {
  const { devices: inventory, hasHubPlan } = state.chain;
  if (!state.snapshot || !state.houseDevices) {
    return '<div class="phone-head"><h2>우리 집</h2><p>기기 상태를 기다려요.</p></div>';
  }
  const observed = new Set((state.snapshot.devices ?? []).map(({ logical_id }) => logical_id));
  const devices = inventory.filter((device) => device.modeled && observed.has(device.logicalId));
  return `<div class="phone-head"><h2>우리 집</h2><p>연결된 기기 ${devices.length}대</p></div>
    <div class="app-map" aria-label="우리 집 평면 지도">
      ${rows(["entrance", "living_room", "kitchen"], (room) => `<div class="app-room">
        <strong>${ROOM_NAMES[room]}</strong>${room === "entrance" ? '<span class="app-door">출입문</span>' : ""}
        ${rows(devices.filter((device) => device.room === room), ({ logicalId, label, chosen }) => {
          const resting = hasHubPlan && !chosen;
          return `<div class="app-device${resting ? " resting" : ""}" data-device="${esc(logicalId)}">
            <span class="app-device-icon" role="img"${resting ? ` aria-label="${esc(label)} · ${STATE_WORDS.resting}"` : ' aria-hidden="true"'}></span>
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

// Line states and the after-party review use the App's words (design/vocabulary.json) and
// show only what the Server's card and rationale say, matched by card_id as the App does.
function rawLines(card) {
  return state.cards.find(({ card_id }) => card_id === card.card_id)?.lines ?? [];
}

function lineStatus(raw) {
  if (!raw || raw.state === "scheduled") return "";
  return [LINE_WORDS[raw.state], END_WORDS[raw.end_state]].filter(Boolean).join(" · ");
}

function changeWords({ property, to }) {
  if (to?.kelvin) return `${to.kelvin}K로 바꾸셨어요`;
  if (property === "power") return to === false || to === "off" ? "전원을 끄셨어요" : "전원을 켜셨어요";
  return "설정을 바꾸셨어요";
}

function reviewNote(card, includeKept = false) {
  const review = state.rationale?.observations?.find(({ card_id, verdict }) => card_id === card.card_id && verdict);
  if (!review) return "";
  const lines = rawLines(card);
  const name = (taskId) => {
    const text = lines.find((line) => line.task_id === taskId)?.text;
    return text ? `‘${text}’ 항목` : "이 항목";
  };
  const feedback = review.task_feedback ?? [];
  const adjusted = feedback.some(({ user }) => user !== "kept");
  const verdict = VERDICT_WORDS[review.verdict === "match" && adjusted ? "match_adjusted" : review.verdict];
  const notes = [
    ...feedback.filter(({ user }) => includeKept && user === "kept").map(({ task_id }) => `${name(task_id)}을 그대로 쓰셨어요.`),
    ...feedback.filter(({ user }) => user === "changed").flatMap(({ task_id, changes }) =>
      changes?.length ? changes.map((change) => `${name(task_id)} · ${changeWords(change)}${includeKept && Number.isInteger(change.after_start_minutes) ? ` · 일정 시작 후 ${change.after_start_minutes}분` : ""}`) : [`${name(task_id)}의 설정을 바꾸셨어요.`]),
    ...feedback.filter(({ user }) => user === "off").map(({ task_id, when, at }) =>
      `${name(task_id)}을 ${when === "during_run" ? "실행 중에 " : when === "before_run" ? "실행 전에 " : ""}끄셨어요.${includeKept && at ? ` · ${at}` : ""}`),
  ];
  return `<div class="app-review"><b>${esc(verdict ?? "")}</b>${rows(notes, (note) => `<p>${esc(note)}</p>`)}</div>`;
}

function phoneCard(card, expected) {
  const theme = themeFor(state.chain.intents.find((intent) => intent.cardId === card.card_id));
  const pending = state.reactionPending?.cardId === card.card_id;
  const stop = !REPLAY && !card.stopped && state.episode?.status !== "closed" && card.buttons.includes("stop");
  return `<div class="app-card"><h3>${paintTheme(card.text, theme)}</h3><ul>${rows(card.lines, (line) => {
    const status = lineStatus(line);
    const reaction = allowedReaction(card, line);
    const switching = pending && state.reactionPending.taskId === line.task_id;
    const next = expected === "line_off" && focusedLine()?.line.task_id === line.task_id;
    const action = reaction === "line_on" ? "켜기" : "끄기";
    return `<li><span>${esc(line.text)}<small>${esc(line.time.story || LINE_WORDS[line.state])}
      ${status ? ` · <b class="line-state">${esc(status)}</b>` : ""}</small></span>
      ${reaction || switching ? `<button class="phone-action app-switch" type="button"
        data-reaction="${reaction ?? ""}" data-card="${esc(card.card_id)}" data-task="${esc(line.task_id)}"
        aria-label="${esc(line.text)} ${action}"${next ? " data-expected" : ""}
        ${state.reactionPending || state.homeBusy ? "disabled" : ""}>${switching ? "확인 중" : action}</button>` : ""}</li>`;
  })}</ul>${stop ? `<button class="phone-action app-stop" type="button" data-reaction="stop" data-card="${esc(card.card_id)}"
    ${state.reactionPending || state.homeBusy ? "disabled" : ""}>${pending && !state.reactionPending.taskId ? "중지 확인 중" : "준비 중지"}</button>` : ""}
    ${reviewNote(card)}</div>`;
}

function allowedReaction(card, line) {
  return REPLAY ? null : lineReaction(card, line, state.started, state.episode?.status);
}

function focusedLine() {
  const ids = new Set(currentMoment()?.lines?.map(({ id }) => id));
  for (const card of state.cards) {
    const line = card.lines.find((row) => ids.has(row.task_id) && state.started.has(row.task_id) &&
      allowedReaction(card, row) === "line_off");
    if (line) return { card, line };
  }
  return null;
}

function phoneExpected() {
  const line = state.page === "house" && Boolean(focusedLine());
  return expectedAction({
    episodeId: state.draft ? null : state.episodeId,
    notification: canPresentCard() && (state.notifications.size || (!state.cardOpen && state.cards.length)),
    cardOpen: canUsePhoneMap() && state.cardOpen,
    cardless: canUsePhoneMap() && state.chain.cardReady && !state.cards.length,
    page: state.page,
    mapOpen: state.mapOpen, line, busy: state.sharing || state.homeBusy || state.reactionPending,
    replay: REPLAY || !state.config.server,
  });
}

function noticeCards() {
  const tasks = state.episode?.item_tasks ?? state.chain.item_tasks;
  if (!tasks.length) return "";
  const closed = state.episode?.status === "closed";
  const waiting = ({ state }) => state === "held" || state === "scheduled";
  const hint = closed ? "품목 안내가 종료됐어요."
    : tasks.some(waiting) ? "택배를 집 안으로 들이면 안내를 볼 수 있어요." : "";
  return `<section class="app-card notice-card"><h3>냉장고 안내</h3>${hint ? `<p>${hint}</p>` : ""}
    <ul>${rows(tasks, (task) => {
      const inactive = closed || waiting(task);
      const kind = { storage: "보관 방법", prep: "준비 방법" }[task.kind];
      const detail = inactive ? kind : task.text;
      return `<li><span>${esc(task.item)}${detail ? `<small>${esc(detail)}</small>` : ""}
        ${inactive ? "" : `<small>${esc(LINE_WORDS[task.state])}</small>`}</span></li>`;
    })}</ul></section>`;
}

function renderPhone() {
  const { hasEpisode, items, cards, orderClock, cardClock, cardReady } = state.chain;
  const expected = phoneExpected();
  const plan = state.cardOpen || (canPresentCard() && cardReady && !cards.length);
  const storyNow = clockNow();
  $("phone-time").textContent = storyNow !== null ? PHONE_CLOCK.format(storyNow) : plan ? cardClock : orderClock;
  $("phone-owner").textContent = OWNERS[state.mapOpen ? "home" : plan ? "card" : "share"];
  $("phone-order").textContent = plan ? "준비" : "주문";
  $("phone-order").setAttribute("aria-pressed", String(!state.mapOpen));
  $("phone-map").setAttribute("aria-pressed", String(state.mapOpen));
  $("phone-map").toggleAttribute("data-expected", expected === "house");
  $("phone-order").toggleAttribute("data-expected", expected === "preparations");
  const notification = state.notifications.keys().next().value;
  const cardButton = !REPLAY && canPresentCard() && (notification || (!state.cardOpen && cards.length))
    ? `<button type="button" class="phone-action card-notification" id="card-notification"${expected === "card" ? " data-expected" : ""}>
      ${notification ? "준비 카드 알림" : "준비 카드 열기"}</button>` : "";
  let screen;
  if (state.mapOpen) {
    screen = phoneMap();
  } else if (state.recordOpen) {
    screen = phoneRecord(cards);
  } else if (!state.episodeId || state.draft) {
    const disabled = state.sharing ? " disabled" : "";
    screen = `<div class="phone-head"><h2>주문 상세</h2></div>` + shareControls(
      state.config.fixture, () => esc(sampleOrder().toDataURL()), (expected === "share" ? " data-expected" : "") + disabled, disabled);
  } else if (plan && cards.length) {
    screen = `<div class="phone-head"><h2>준비 카드</h2><p>${esc(cards[0].updatedStory)}</p></div>
      ${cardButton}${rows(cards, (card) => phoneCard(card, expected))}${noticeCards()}`;
  } else if (plan) {
    const title = stageNotice("plan", state.readProblems) ?? "준비 카드 없음";
    screen = noticeCards() || `<div class="phone-head"><h2>${title}</h2></div>`;
  } else {
    const title = items.length ? "주문을 읽었어요" : "주문을 보냈어요";
    screen = `${cardButton}<div class="phone-reading"><h2>${title}</h2>
      <div class="scan-picture">${hasEpisode && items.length ? receipt(items) : state.capture
        ? `<img src="${esc(state.capture)}" alt="공유한 주문 화면">` : ""}</div></div>`;
  }
  if (!state.mapOpen && state.controlError) screen = `<p class="phone-error" role="status">${esc(state.controlError)}</p>` + screen;
  const content = $("phone-content");
  if (content.dataset.content === screen) return;
  const focused = content.contains(document.activeElement) ? document.activeElement : null;
  const scroll = content.scrollTop;
  setMarkup(content, screen);
  content.scrollTop = scroll;
  if (focused?.id) $(focused.id)?.focus({ preventScroll: true });
  else if (focused?.dataset.card) {
    [...content.querySelectorAll("[data-card]")].find((button) =>
      button.dataset.card === focused.dataset.card && button.dataset.task === focused.dataset.task)
      ?.focus({ preventScroll: true });
  }
  if ($("sample")) $("sample").onclick = () => shareSample();
  if ($("card-notification")) $("card-notification").onclick = () => openCard(notification);
  if ($("files")) $("files").onchange = (event) => {
    const files = [...event.target.files].slice(0, 3);
    if (files.length) share(files);
  };
}

function openCard(notification) {
  if (!canPresentCard() || !state.cards.length || state.sharing || state.homeBusy) return;
  if (notification) {
    state.notifications.delete(notification);
    state.dismissed.add(notification);
  }
  const wasOpen = state.cardOpen;
  state.cardOpen = true;
  $("phone-content").scrollTop = 0;
  if (state.page === "reason" && !wasOpen) {
    if (state.step === reasonStep("tasks") && reasonReady(state.step) &&
        (MANUAL || performance.now() >= state.shownAt + stageDwell())) setStep(reasonStep("plan"));
    else {
      renderReason();
      autoAdvance();
    }
    $("phone-map").focus({ preventScroll: true });
  } else {
    renderPhone();
  }
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
  const color = state.houseModule?.hsvColor(light ?? undefined);
  const hasColor = [light?.hue, light?.saturation, light?.brightness].every(Number.isFinite);
  const values = [
    hasColor && `<li><strong>${DEVICE_NAMES.light}</strong>${color ? `<span class="swatch" style="--concept:${color}" aria-hidden="true"></span>` : ""}
      색조 ${light.hue}° · 채도 ${light.saturation} · 밝기 ${light.brightness}</li>`,
    scene && `<li><strong>${DEVICE_NAMES.display}</strong>${esc(STATE_WORDS["scene_" + scene] ?? scene)}</li>`,
    Number.isFinite(oven?.temp_c) && Number.isFinite(oven?.minutes) &&
      `<li><strong>${DEVICE_NAMES.oven}</strong>${oven.temp_c}℃ · ${oven.minutes}분</li>`,
  ].filter(Boolean);
  if (!values.length) return "";
  const moodTask = tasks.find(({ values }) => values.some(({ cmd }) => cmd === "color" || cmd === "play_mood"));
  const theme = themeFor(intents.find(({ id }) => id === moodTask?.intentId));
  return `<aside class="palette">${theme ? `<small>고른 분위기</small><h2>${esc(theme)}</h2>
    <span class="palette-arrow" aria-hidden="true">↓</span>` : ""}<ul>${values.join("")}</ul></aside>`;
}

function tasksStage({ tasks, intents, devices, item_tasks }) {
  if (!tasks.length) return `<div class="panel"><h2>집 준비 ${tasks.length}개 · 냉장고 안내 ${item_tasks.length}개</h2></div>${itemNotices()}`;
  const palette = translation(tasks, intents);
  return `<div class="task-layout${palette ? "" : " without-palette"}"><div class="task-table" role="table" aria-label="준비할 일">
    <div class="task-row" role="row"><span role="columnheader">필요한 준비</span><span aria-hidden="true"></span>
      <span role="columnheader">할 일</span><span role="columnheader">기기</span></div>
    ${rows(tasks, (task) => {
      const timing = task.time.derivation || task.time.story;
      const line = stageLine(task.id, task.line, task.devices, devices);
      return `<div class="task-row" role="row">
        <span class="task-need" role="cell">${esc(task.need)}</span><span class="task-arrow" aria-hidden="true">→</span>
        <span class="task-line" role="cell">${line.markup}${timing ? `<small>${esc(timing)}</small>` : ""}</span>
        <span class="task-device" role="cell">${esc(line.labels)}</span>
      </div>`;
    })}
  </div>${palette}</div>${itemNotices()}`;
}

function stageLine(id, text, serverDevices, inventory) {
  const line = lineWithTag(text, serverDevices, findTag(state.tags, "line", id, text));
  return { markup: line.markup, labels: line.devices.map((id) =>
    inventory.find(({ logicalId }) => logicalId === id)?.label ?? id).join(" · ") };
}

function planStage({ cards, cardReady, tasks, devices }) {
  if (cards.length) return rows(cards, (card) => `<section class="plan-card">
    <ul class="plan-list">${rows(card.lines, (line) => {
      const serverDevices = tasks.find(({ id }) => id === line.task_id)?.devices ?? [];
      const presentation = stageLine(line.task_id, line.text, serverDevices, devices);
      return `<li><time>${esc(line.time.story || "시간을 기다리는 중")}</time><span>${presentation.markup}
        ${presentation.labels ? `<small>${esc(presentation.labels)}</small>` : ""}
        ${line.note ? `<small>${esc(line.note)}</small>` : ""}</span></li>`;
    })}</ul>
  </section>`);
  return cardReady ? (itemNotices() || '<p class="lead">이번 주문에는 준비 카드가 없어요.</p>')
    : '<p class="lead">준비 카드를 기다리고 있어요.</p>';
}

function recordReviews(cards, heading) {
  const reviews = cards.map((card) => ({ card, note: reviewNote(card, true) })).filter(({ note }) => note);
  return rows(reviews, ({ card, note }) => `<div class="app-card"><${heading}>${esc(card.text)}</${heading}>${note}</div>`);
}

function memoryContent() {
  const memory = state.memory?.intents ?? [];
  const status = stageNotice("record", { memory: state.readProblems.memory }) ??
    (state.memory === undefined ? "기억을 불러오는 중이에요."
      : state.memory === null ? "기억을 불러오지 못했어요." : "저장된 기억이 없어요.");
  return memory.length ? rows(memory, (intent) => `<div class="memory-intent">
    <strong>${esc(intent.name)}</strong>
    ${rows(intent.off_lines ?? [], ({ line, until }) => `<p>다음에는 빼 둘 줄 · <b>${esc(line)}</b><small>${esc(until)}까지</small></p>`)}
    ${rows(intent.changed ?? [], ({ change }) => `<p>이 집이 바꾼 것 · <b>${esc(change)}</b></p>`)}
  </div>`) : `<p>${status}</p>`;
}

function phoneRecord(cards) {
  return `<div class="phone-head"><h2>판단 확인</h2></div>
    ${recordReviews(cards, "h3") || '<p class="phone-record-wait">파티가 끝나면 판단 확인이 와요.</p>'}
    <section class="app-card memory-panel"><h3>이 집의 기억</h3>${memoryContent()}</section>`;
}

function reviewsReady() {
  const ids = state.episode?.card_ids?.length ? state.episode.card_ids : state.cards.map(({ card_id }) => card_id);
  return ids.length > 0 && ids.every((id) => state.cards.some(({ card_id }) => card_id === id) &&
    state.rationale?.observations?.some(({ card_id, verdict }) => card_id === id && verdict));
}

function recordReady() {
  return Boolean(state.runPath === "house" && reviewsReady() && state.finalMemory);
}

function renderEnding() {
  const problem = stageNotice("record", state.readProblems);
  state.recordVisible = state.page === "house" && state.recordRequested && Boolean(recordReady() || problem);
  $("reason").hidden = state.page !== "reason" && !state.recordVisible;
  $("home").hidden = state.page !== "house" || state.recordVisible;
  renderStageIndicator();
  if (!state.recordVisible) return;
  $("reason-layout").dataset.stage = "record";
  const markup = `<div class="copy-enter"><header class="stage-head"><h1>${esc(state.scenes.record.title)}</h1></header>
    <div class="record-grid"><section>${recordReviews(state.chain.cards, "h2") ||
      (problem ? `<p>${problem}</p>` : "")}</section>
    <section class="memory-panel"><h2>이 집의 기억</h2>${memoryContent()}</section></div></div>`;
  const copy = $("stage-copy");
  if (copy.dataset.content !== markup) {
    copy.dataset.content = markup;
    copy.innerHTML = markup;
  }
}

function waitingForQuiet() {
  const now = clockNow();
  return !state.chain.ready.context && now !== null && state.quietEnd !== null && now < state.quietEnd;
}

function waitingForJudgment() {
  if (!waitingForQuiet()) return "판단하고 있어요.";
  const minutes = (state.quietEnd - Date.parse(state.episode.shared_at)) / 60000;
  return `같은 주문이 더 오는지 ${minutes}분 기다려요.`;
}

function stageBody(scene) {
  if (scene.id === "share") return "";
  const problem = stageNotice(scene.id, state.readProblems);
  if (problem) return `<p class="lead">${problem}</p>`;
  if (scene.id === "plan" && !state.chain.cardReady && state.cardsRead && !state.config.fixture) {
    return '<p class="lead">아직 도착한 준비 카드가 없어요.</p>';
  }
  if (!stageReady(scene.id)) return `<p class="lead">${waitingForJudgment()}</p>`;
  if (scene.id === "tasks") return tasksStage(state.chain);
  const receipt = state.runPath === "plan" && state.chain.receiptStory;
  return planStage(state.chain) + (receipt ? `<p class="lead">${esc(receipt)}</p>` : "");
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

function renderJudgment(copy, scene) {
  if (!copy.dataset.judgment) {
    copy.dataset.judgment = "shown";
    setMarkup(copy, `<div id="judgment-scene">
      <header class="judgment-head"><h1>주문의 판단 근거</h1>${ownerTag("reasoning")}</header>
      <section id="judgment-items"><h2 id="judgment-items-heading"></h2><div id="judgment-tiles"></div>
        <p id="judgment-masked" hidden></p><p id="judgment-comparison" hidden></p></section>
      <div class="judgment-evidence"><section class="panel" id="judgment-calendar" hidden></section>
        <section class="panel kb-panel" id="judgment-similar" hidden></section></div>
      <section id="judgment-slots" hidden></section><section id="judgment-intent" hidden></section>
    </div>`);
  }

  const beats = new Map(state.judgment.map((beat) => [beat.id, beat]));
  const items = beats.get("items");
  const showItems = ["items", "unusual"].includes(scene.beat);
  $("judgment-items").hidden = !showItems;
  if (showItems) {
    const tiles = $("judgment-tiles");
    const itemMarkup = items?.items.length ? quantityCards(items.items, state.itemTypes) : "";
    const newTiles = tiles.dataset.content !== itemMarkup;
    setMarkup(tiles, itemMarkup);
    $("judgment-items-heading").textContent = items
      ? `사진에서 물건 ${items.items.length}종을 읽었어요`
      : missingJudgment() ? "저장된 판단 근거가 없어요." : "주문을 읽는 중이에요.";
    $("judgment-masked").hidden = !items?.maskedCount;
    $("judgment-masked").textContent = items?.maskedCount ? `가린 물건 ${items.maskedCount}개` : "";

    const unusual = scene.beat === "unusual" ? beats.get("unusual") : null;
    $("judgment-comparison").hidden = !unusual;
    if (unusual) $("judgment-comparison").textContent = comparisonText(unusual.comparison);
    for (const tile of tiles.querySelectorAll(".item-tile")) {
      const { kind, label } = itemComparison(unusual?.comparison, tile.dataset.type);
      if (tile.dataset.comparison !== kind) tile.dataset.comparison = kind;
      const why = tile.querySelector(".item-why");
      why.hidden = !label;
      if (why.textContent !== label) why.textContent = label;
    }
    if (newTiles && itemMarkup && scene.beat === "items") flyItems(++flightVersion);
  }

  const calendar = beats.get("calendar");
  const similar = beats.get("similar");
  const slots = beats.get("slots");
  const intent = beats.get("intent");
  const candidates = calendar?.candidates ?? [];
  const atSlots = scene.beat === "slots";
  const linked = atSlots ? candidates.filter(({ id }) => slots?.calendarUse.some(({ event }) => event.id === id)) : candidates;
  // Later beats keep their own sources visible without stacking every earlier panel.
  for (const [id, show, markup] of [
    ["calendar", (scene.beat === "calendar" && calendar) || (atSlots && linked.length),
      () => calendarMarkup(linked, atSlots ? slots.calendarUse : null, items?.items ?? [])],
    ["similar", scene.beat === "similar" && similar, () => ownerTag("server") + similarMarkup(similar)],
    ["slots", (atSlots || scene.beat === "intent") && slots, () => slotsMarkup(slots.groups, items?.items ?? [], candidates, state.tags)],
    ["intent", scene.beat === "intent" && intent, () => intentMarkup(intent, items?.items ?? [], candidates, state.tags)],
  ]) {
    const node = $(`judgment-${id}`);
    node.hidden = !show;
    if (show) setMarkup(node, markup());
  }
}

function renderReason() {
  let scene = state.scenes.reason[state.step];
  if (scene.beat === "slots" && omittedSlots()) {
    scene = state.scenes.reason[++state.step];
    state.shownAt = null;
  }
  const { chain } = state;
  const layout = $("reason-layout");
  const copy = $("stage-copy");
  if (state.shownAt === null && reasonReady(state.step)) state.shownAt = performance.now();
  layout.dataset.stage = scene.id;
  $("phone-dock").dataset.stage = scene.id;
  renderStageIndicator();
  renderPhone();
  const problem = stageNotice(scene.id, state.readProblems);
  if (scene.beat && scene.beat !== "tasks" && !problem) {
    renderJudgment(copy, scene);
    renderControls();
    return;
  }
  delete copy.dataset.judgment;
  document.querySelectorAll(".flight").forEach((clone) => clone.remove());
  const headline = ["share", "plan"].includes(scene.id);
  let title = problem ? STAGE_NAMES[scene.id] : stageReady(scene.id) ? scene.title : "결과를 기다려요";
  if (scene.id === "plan" && chain.cardReady) title = chain.cards.length ? scene.readyTitle : scene.noCardTitle;
  const owner = { share: "share", plan: "card" }[scene.id] ?? "reasoning";
  const markup = `<div class="copy-enter"><header class="stage-head">${ownerTag(owner)}
    <h1${headline ? ' class="headline"' : ""}>${esc(title)}</h1><p class="lead">${esc(stageReady(scene.id) ? scene.lead : "")}</p>
    </header>${stageBody(scene)}</div>`;
  if (copy.dataset.content !== markup) {
    copy.dataset.content = markup;
    copy.innerHTML = markup;
    ++flightVersion;
  }
  renderControls();
}

// The scene clock measures audience dwell. It does not drive the Server.
const dwellParam = query.get("dwell");
const requestedDwell = dwellParam === null ? NaN : Number(dwellParam) * 1000;
const DWELL_MS = Number.isFinite(requestedDwell) ? Math.max(0, requestedDwell) : null;
const MANUAL = query.get("auto") === "0";

function reasonStep(id) {
  return state.scenes.reason.findIndex((scene) => scene.id === id);
}

function stageReady(id) {
  return state.chain.ready[id] ?? true;
}

function missingJudgment() {
  return state.episode && state.rationaleMissing && !state.rationale && state.cards.length > 0;
}

function reasonReady(step) {
  const { id, beat } = state.scenes.reason[step];
  if (stageNotice(id, state.readProblems)) return true;
  if (id === "plan" && state.cardsRead && !state.config.fixture) return true;
  if (!beat) return stageReady(id);
  if (beat === "items" && missingJudgment()) return true;
  return state.judgment.some((entry) => entry.id === beat);
}

function canOpenPlan() {
  return REPLAY || state.cardOpen || (state.chain.cardReady && !state.cards.length) ||
    stageNotice("plan", state.readProblems) || (!state.config.fixture && state.cardsRead && !state.cards.length);
}

function canPresentCard() {
  return state.page === "house" || state.cardOpen || state.step >= reasonStep("tasks") ||
    (missingJudgment() && state.step >= reasonStep("extract"));
}

function omittedSlots() {
  return state.judgment.some(({ id, intents }) => id === "intent" && !intents.length);
}

function nextReasonStep() {
  let next = state.step + 1;
  const { id } = state.scenes.reason[state.step];
  if (stageNotice(id, state.readProblems)) {
    while (state.scenes.reason[next]?.id === id) next += 1;
  }
  const { beat } = state.scenes.reason[next] ?? {};
  if (beat && beat !== "items" && missingJudgment()) return reasonStep("plan");
  if (beat === "slots" && omittedSlots()) return next + 1;
  return next;
}

function stageDwell() {
  const { id, beat } = state.scenes.reason[state.step];
  if (RECORDING) {
    const beats = state.scenes.reason.filter((scene) => scene.id === id && (scene.beat !== "slots" || !omittedSlots()));
    return (DWELL_MS ?? 3000) / beats.length;
  }
  if (beat === "items") return Math.max(1800, DWELL_MS ?? 2200);
  if (beat && beat !== "tasks") return Math.max(1200, DWELL_MS ?? 1600);
  return DWELL_MS ?? 3000;
}

async function autoAdvance() {
  if (MANUAL || state.auto || state.draft) return;
  const run = {};
  state.auto = run;
  while (state.auto === run && state.page === "reason" && (RECORDING || state.step < reasonStep("plan"))) {
    const remaining = state.shownAt === null ? 0 : Math.ceil(state.shownAt + stageDwell() - performance.now());
    if (remaining > 0) await sleep(remaining);
    else if (state.shownAt !== null && canMoveReasonForward()) {
      if (state.step === reasonStep("plan")) enterHouse();
      else setStep(nextReasonStep(), true);
    } else if (state.shownAt !== null && state.step === reasonStep("plan")) break;
    else {
      renderStageIndicator();
      await sleep(120);
    }
  }
  if (state.auto === run) state.auto = null;
}

function setStep(step, automatic = false) {
  if (!automatic) state.auto = null;
  const next = Math.max(0, Math.min(step, state.scenes.reason.length - 1));
  if (next !== state.step) state.shownAt = null;
  state.step = next;
  if (REPLAY && state.step >= reasonStep("plan")) state.cardOpen = true;
  renderReason();
}

function applyCapture(url) {
  if (state.capture) URL.revokeObjectURL(state.capture);
  state.capture = url;
}

async function shareSample() {
  if (state.sharing || !state.config.fixture) return false;
  state.sharing = true;
  renderControls();
  try {
    const blob = await new Promise((resolve) => sampleOrder().toBlob(resolve, "image/png"));
    if (!blob) throw new Error("No sample image");
    return await share([new File([blob], "sample-order.png", { type: "image/png" })], state.order);
  } catch {
    notice("예시 주문 화면을 만들지 못했어요.");
    return false;
  } finally {
    state.sharing = false;
    renderReason();
  }
}

async function share(files, sample = null) {
  const demoPath = draftPath();
  state.sharing = true;
  notice("주문을 보내는 중이에요.");
  renderControls();
  const sharedAt = stamp();
  const form = new FormData();
  for (const file of files) form.append("images", file, file.name || "order.png");
  if (sample && state.config.fixture) form.append("sample", sample);
  try {
    const result = await exchange("/demo/api/order", { method: "POST", body: form, signal: AbortSignal.timeout(35000) });
    if (!result.ok || !result.body?.episode_id) throw new Error(result.status);
    const accepted = result.body;
    state.sharedEpisode = accepted.episode_id;
    state.recordOpen = false;
    applyCapture(URL.createObjectURL(files[0]));
    state.draft = false;
    state.draftPath = null;
    state.cardOpen = false;
    state.mapOpen = false;
    readEpisode(accepted.episode_id, { data: { ...accepted, sample, images: files.length }, at: sharedAt, demoPath });
    setStep(0);
    autoAdvance();
    notice();
    return true;
  } catch (error) {
    notice(`주문을 보내지 못했어요. (${error.message})`);
    return false;
  } finally {
    state.sharing = false;
    renderReason();
  }
}

let episodeRead = 0;
let appliedEpisodeReads = {};

function acceptEpisodeRead(id, read, source, { episode, rationale, rationaleMissing, cards, cursor, problem = null }) {
  if (id !== state.episodeId || read < (appliedEpisodeReads[source] ?? 0)) return;
  appliedEpisodeReads[source] = read;
  acceptReadProblem(source, problem, read);
  if (episode) state.episode = episode;
  if (rationale) state.rationale = rationale;
  if (rationaleMissing != null) state.rationaleMissing = rationaleMissing;
  if (cursor) state.cardCursor = cursor;
  if (cards) {
    state.cardsRead = true;
    const current = new Map(state.cards.map((card) => [card.card_id, card]));
    for (const card of cards) {
      if (card.episode_id !== id || Date.parse(card.updated_at) < Date.parse(current.get(card.card_id)?.updated_at)) continue;
      current.set(card.card_id, card);
      const key = JSON.stringify([card.card_id, card.updated_at]);
      if (!REPLAY && card.notify && !state.dismissed.has(key)) state.notifications.add(key);
    }
    state.cards = [...current.values()];
    const pending = state.reactionPending;
    if (pending?.awaitingStop && current.get(pending.cardId)?.stopped) state.reactionPending = null;
  }
  state.started = startedLines(state.started, state.cards, state.rationale?.executions);
  refreshChain();
  resolveHouseLink();
}

function acceptReadProblem(source, problem, read) {
  if (state.readProblems[source] === problem) return;
  if (problem) state.record?.("read_problem", { source, problem }, ...stamp(), read);
  state.readProblems[source] = problem;
}

const ARCHIVE = "1970-01-01T00:00:00Z";
function cardsPath(since) {
  const path = `/demo/api/server/v1/households/${encodeURIComponent(state.config.household_id)}/cards`;
  return since ? `${path}?since=${encodeURIComponent(since)}` : path;
}

async function readEpisode(id, share) {
  state.reader?.abort();
  const controller = new AbortController();
  state.reader = controller;
  if (state.episodeId !== id || share) {
    state.episodeId = id;
    state.runPath = share?.demoPath ?? state.config.demo_path ?? (state.config.fixture || REPLAY ? defaultPath(id) : "house");
    state.tags = [];
    state.tagsReady = state.tagsRead = null;
    state.episode = state.rationale = state.hub = state.snapshot = null;
    state.houseMarkup = "";
    state.homeId = "plan";
    state.followGuest = false;
    state.facts.clear();
    state.pendingClockLines.clear();
    state.playedMotion.clear();
    state.appliedScene = state.cameraMoment = state.roomCameraMoment = state.displayReadings = null;
    state.homeBusy = false;
    state.house?.clearScene();
    revealHouseState();
    state.rationaleMissing = false;
    state.readProblems = {};
    state.cardsRead = false;
    state.shownAt = null;
    state.cards = [];
    state.cardCursor = null;
    state.notifications.clear();
    state.started = new Set();
    state.reactionPending = null;
    state.controlError = "";
    state.memory = undefined;
    state.finalMemory = state.recordRequested = state.recordVisible = state.recordFinished = false;
    state.quietEnd = null;
    state.waiting = undefined;
    state.retryUntil = 0;
    if (share && state.config.fixture) {
      state.clock = null;
    }
    if (!REPLAY) {
      const recorder = createRecorder(api, state.config, id, state.runPath, () => {
        if (state.reader === controller && !$("notice").textContent) notice("녹화를 다시 저장하고 있어요.");
      });
      state.record = recorder.record;
      state.runId = recorder.id;
      if (share) log("share", share.data, share.at);
    }
    if (share && state.config.fixture) void readClock();
  }
  refreshChain();
  for (;;) {
    await refreshCards(state.cardCursor ?? "", 12000);
    if (controller.signal.aborted) return;
    if (state.episode?.card_ids?.some((cardId) => !state.cards.some(({ card_id }) => card_id === cardId))) {
      await readCards(id, ++episodeRead, ARCHIVE, {
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]),
      }).catch(() => {});
      if (controller.signal.aborted) return;
    }
    if (state.config.fixture && state.clock && !REPLAY && state.episode?.status === "reading" &&
      state.chain.ready.extract && !state.quietRamped.has(id) && state.quietEnd === null) {
      moveClockTo(QUIET_END, { episodeId: id, signal: controller.signal }).catch(() => {});
    }
    if (state.chain.cardReady && state.chain.hasEpisode &&
      (state.judgment.some(({ id }) => id === "tasks") || missingJudgment())) return;
    if (!state.config.fixture && state.chain.cardReady && state.readProblems.rationale) return;
    await sleep(1000);
    if (controller.signal.aborted) return;
  }
}

function renderArrival() {
  if (state.page === "house") renderTimeline();
  else renderReason();
}

async function readCards(id, read, since, options) {
  const { reader } = state;
  let payload;
  try {
    const body = await observe("cards", cardsPath(since), options, {
      transform: (data) => ({ ...data, cards: data.cards.filter(({ episode_id }) => episode_id === id) }),
    });
    payload = { cards: body.cards, cursor: body.server_time };
  } catch (error) {
    const problem = readProblem(error.status);
    // The full read establishes whether the cards route is present. A cursor
    // or archive read must not override its result.
    if (state.config.fixture || !problem || (since && problem === "missing")) return;
    payload = { problem };
  }
  if (state.reader !== reader) return;
  acceptEpisodeRead(id, read, "cards", payload);
  renderArrival();
}

function chooseOrder(order) {
  if (state.sharing || state.reactionPending || REPLAY) return;
  state.order = order;
  state.draft = Boolean(state.episodeId);
  if (state.draft) state.auto = null;
  $("phone-content").scrollTop = 0;
  renderReason();
}

function draftPath() {
  return state.draftPath ?? (state.config.fixture ? defaultPath(SAMPLE_EPISODES[state.order]) : "house");
}

function canEnterHouse() {
  return Boolean(state.episodeId && state.runPath === "house" && state.chain.ready.hub &&
    (!RECORDING || state.replay?.house.length));
}

function timeline() {
  if (RECORDING) return state.replay?.house.map(({ moment }) => moment) ?? [];
  return buildMoments({
    chain: state.chain, actions: state.hub?.plan_actions?.[state.episodeId],
    relations: state.hub?.plan_lines?.[state.episodeId],
    facts: [...state.facts.values()], tags: state.tags,
    wording: state.scenes.house, since: state.episode?.shared_at,
  });
}

function currentMoment(scenes = timeline()) {
  return RECORDING ? scenes[state.replayStep] : scenes.find(({ id }) => id === state.homeId) ?? scenes[0];
}

function observedGuestLine(moment, moments) {
  return moments.find(({ follows, ready }) => ready && follows === moment.id);
}

function selectHouseMoment(moment) {
  state.homeId = moment.id;
  log("house", { moment: recordedMoment(moment) });
}

function updateHousePresentation(moment) {
  state.house?.setPresentation(houseDevicePresentation(state.chain, moment?.focusDevices, moment?.title));
}

function updateScene(moment, moments) {
  if (!state.house || RECORDING || state.recordVisible) return;
  const motionKey = (line) => JSON.stringify([moment.id, line]);
  const result = momentScene(moment, {
    moments, items: state.chain.items, itemTasks: state.chain.item_tasks,
    itemTypes: state.itemTypes, vocabulary: state.sceneVocabulary,
    snapshot: state.snapshot, displayReadings: state.displayReadings ?? null,
    devices: state.chain.devices, showArtwork: state.config.fixture,
    canPlay: (line) => !state.playedMotion.has(motionKey(line)),
  });
  if (!result) {
    state.house.clearScene();
    state.appliedScene = null;
    return;
  }
  const { scene, artwork, motions } = result;
  // A poll must not reset a scene or restart a motion that the audience already saw.
  const stable = JSON.stringify({ ...scene, artwork, slots: scene.slots.slice(0, scene.slots.length - motions.length) });
  if (state.appliedScene === stable && !motions.length) return;
  if (sendScene(state.house, state.validateScene, withSceneArtwork(scene, artwork), () =>
    log("scene", { moment: recordedMoment(moment), scene, artwork }))) {
    state.appliedScene = stable;
    for (const line of motions) state.playedMotion.add(motionKey(line));
  }
}

function decorateHouseLabel(marker, { focused, moment }) {
  const label = marker.firstElementChild;
  const resting = !focused && !marker.hasAttribute("data-changed");
  marker.toggleAttribute("data-resting", resting);
  const value = label.querySelector(".device-value");
  value?.classList.toggle("visually-hidden", resting);
  if (value && marker.dataset.device === "fridge_01") value.title = value.textContent;

  let annotation = label.querySelector(".marker-moment");
  if (!annotation && moment && value) {
    annotation = document.createElement("span");
    annotation.className = "marker-moment";
    label.append(annotation);
  }
  if (annotation) {
    annotation.textContent = moment;
    annotation.hidden = !moment;
  }
}

function renderTimeline({ instant = false, follow = true } = {}) {
  renderEnding();
  renderPhone();
  const moments = timeline();
  let current = currentMoment(moments);
  if (!current) return;
  if (follow && state.followGuest && !state.homeBusy) {
    const observed = observedGuestLine(current, moments);
    if (observed) {
      state.followGuest = false;
      selectHouseMoment(observed);
      current = observed;
    }
  }
  updateHousePresentation(current);
  updateScene(current, moments);
  directHouse(current, instant);
  $("home-time").textContent = current.story;
  $("home-title").textContent = current.title;
  $("home-caption").textContent = current.lead ?? "";
  $("home").setAttribute("aria-busy", String(state.homeBusy));
  const steps = $("timeline");
  const selected = RECORDING ? state.replayStep : moments.indexOf(current);
  const markup = rows(moments, (moment, index) => `<li><button type="button" data-step="${index}"
    ${index === selected ? 'aria-current="step"' : ""}
    ${index < selected && moment.ready ? 'class="past"' : ""}
    ${state.homeBusy || !moment.ready ? "disabled" : ""}>
    ${moment.story ? `<time>${esc(moment.story)}</time>` : ""}
    <span>${esc(moment.title)}</span>${moment.ready ? "" : `<small>${moment.state === "off" ? "꺼짐" : "대기"}</small>`}
    </button></li>`);
  if (steps.dataset.content !== markup) {
    const focused = steps.contains(document.activeElement);
    steps.dataset.content = markup;
    steps.innerHTML = markup;
    if (focused) (steps.querySelector('[aria-current="step"]:enabled') || $("next")).focus({ preventScroll: true });
  }
  renderControls();
  if (state.recordLink) {
    const end = moments.findLastIndex(({ kind, ready }) => kind === "end" && ready);
    if (end >= 0) {
      state.recordLink = false;
      goHouse(end);
      openRecord();
    }
  }
}

const CLOSEUP_MS = 6000;
let closeupTimer = 0;

function roomCamera(room) {
  // Older offline recordings may have cached a renderer without room presets.
  const cameras = state.houseModule?.HOUSE_ROOM_VIEWS ?? {};
  if (Object.hasOwn(cameras, room)) return cameras[room];
  if (Object.hasOwn(state.scenes.cameras, room)) return state.scenes.cameras[room];
}

function selectRoomCamera(room) {
  for (const button of document.querySelectorAll(".room-key [data-room]")) {
    button.setAttribute("aria-pressed", String(button.dataset.room === room));
  }
}

function directHouse(moment, instant = false) {
  if (!state.house) return;
  state.house.setEntrance({ signal: moment.signal ?? "", packagePresent: moment.signal === "package" });
  if (state.roomCameraMoment === moment.id) return;
  state.roomCameraMoment = null;
  const close = closeView(moment, state.chain.devices);
  const key = JSON.stringify([moment.id, moment.room, close]);
  if (!instant && key === state.cameraMoment) return;
  state.cameraMoment = key;
  clearTimeout(closeupTimer);
  const room = roomCamera(moment.room) ?? roomCamera("overview");
  const closeup = !instant && close;
  $("view").toggleAttribute("data-closeup", Boolean(closeup));
  selectRoomCamera(closeup ? null : moment.room);
  state.house.focus(closeup || room, { instant });
  if (closeup) {
    closeupTimer = setTimeout(() => {
      if (state.cameraMoment !== key || state.page !== "house") return;
      $("view").removeAttribute("data-closeup");
      selectRoomCamera(moment.room);
      state.house.focus(room);
    }, CLOSEUP_MS);
  }
}

// The Hub and Simulator follow the Server's story clock independently.
const FIXTURE_LEAD_MS = 5000;
const RAMP_SECONDS = 4;
let clockRead;

function markClockMissing(status) {
  if (![404, 405, 501].includes(status)) return;
  state.clockMissing = true;
  state.clock = null;
  renderControls();
}

// The rehearsal clock is optional. Stop polling it when the peer says it is unavailable.
function readClock() {
  if (!state.config.server || state.clockMissing) return null;
  const { reader } = state;
  if (clockRead && clockRead.reader === reader) return clockRead.pending;
  const pending = observe("clock", "/demo/api/server/v1/demo/clock", { signal: AbortSignal.timeout(2500) })
    .then(async (clock) => {
      if (!state.clockMoments) {
        const moments = await api("/demo/api/server/v1/demo/moments", { signal: AbortSignal.timeout(2500) });
        if (!Array.isArray(moments) || state.reader !== reader) return null;
        state.clockMoments = true;
      }
      if (state.reader === reader && !(clock.version < state.clock?.version)) {
        state.clock = clock;
        renderControls();
      }
      return state.clock;
    })
    .catch(({ status }) => {
      if (state.reader === reader) markClockMissing(status);
      return state.clock;
    })
    .finally(() => { if (clockRead?.pending === pending) clockRead = null; });
  clockRead = { reader, pending };
  return pending;
}

function clockNow() {
  if (RECORDING) return state.replayTime ?? null;
  const clock = state.clock;
  if (!clock) return null;
  const real = Date.now();
  const anchor = Date.parse(clock.real_at);
  const story = Date.parse(clock.story_at);
  const until = clock.ramp_until ? Date.parse(clock.ramp_until) : null;
  if (until !== null && real > until) return story + (until - anchor) * clock.rate + (real - until);
  return story + (real - anchor) * clock.rate;
}

async function moveClockTo(scene, { episodeId, signal } = {}) {
  if (!await readClock() || signal?.aborted) return;
  const reader = state.reader;
  const episode = new URLSearchParams({ episode_id: episodeId });
  const momentsPath = "/demo/api/server/v1/demo/moments" + (state.config.fixture ? "" : `?${episode}`);
  const moments = await observe("moments", momentsPath, { signal: AbortSignal.timeout(2500) },
    { transform: (data) => data.filter((entry) => !entry.episode_id || entry.episode_id === episodeId) }).catch((error) => {
    if (state.reader === reader) markClockMissing(error.status);
    if (state.clockMissing) return [];
    throw error;
  });
  if (state.clockMissing) return;
  if (state.reader !== reader) return;
  const forQuiet = scene === QUIET_END;
  const moment = forQuiet ? moments.find(({ event }) => event === scene.event)
    : moments.filter(({ at, event }) => event !== QUIET_END.event && Date.parse(at) > clockNow() + 1000)
      .sort((a, b) => Date.parse(a.at) - Date.parse(b.at))[0];
  if (!moment) {
    if (!forQuiet) notice("앞으로 남은 시연 시각이 없어요.");
    return;
  }
  const now = clockNow();
  if (now === null || signal?.aborted) return;
  const target = Date.parse(moment.at) -
    (state.config.fixture && !forQuiet && moment.kind === "time" ? FIXTURE_LEAD_MS : 0);
  if (forQuiet) {
    state.quietEnd = target;
    if (state.quietRamped.has(episodeId) || target <= now) return;
    state.quietRamped.add(episodeId);
    if (state.page === "reason") renderReason();
  } else if (target <= now + 1000) {
    return;
  }
  const clockLines = forQuiet ? [] : timeline().filter(({ ready, at, lines }) =>
    !ready && lines?.some(({ when }) => when.time) && Date.parse(at) <= Date.parse(moment.at));
  const message = forQuiet ? "주문을 기다리는 시간을 앞당겨요." : "다음 시연 시각으로 시간을 보내요.";
  notice(message);
  try {
    const timeout = AbortSignal.timeout(12000);
    const options = {
      method: "POST", headers: { "Content-Type": "application/json" },
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    };
    if (forQuiet || state.config.fixture) {
      const clock = await observe("clock", "/demo/api/clock", {
        ...options, body: JSON.stringify({ advance_to: new Date(target).toISOString(), over_seconds: RAMP_SECONDS }),
      });
      if (state.reader === reader && !state.clockMissing) state.clock = clock;
    } else {
      const result = await exchange(`/demo/api/clock/next?${episode}`, {
        ...options, body: JSON.stringify({ over_seconds: RAMP_SECONDS }),
      });
      if (state.reader !== reader) return;
      if (!result.ok) {
        if (result.status === 404 && result.body?.message === "No story moments remain") {
          notice("앞으로 남은 시연 시각이 없어요.");
          return;
        }
        markClockMissing(result.status);
        if (state.clockMissing) return;
        throw new Error(result.status);
      }
      log("presenter", { action: "clock", status: result.status, result: result.body });
      await readClock();
    }
    if (state.reader === reader) {
      for (const { id } of clockLines) state.pendingClockLines.add(id);
    }
    await sleep(RAMP_SECONDS * 1000 + 300);
  } finally {
    if ($("notice").textContent === message && !signal?.aborted) notice();
  }
}

async function refreshCards(since = state.cardCursor ?? ARCHIVE, timeout = 4000) {
  const { episodeId, reader } = state;
  if (!episodeId || RECORDING) return;
  const read = ++episodeRead;
  const episodePath = `/demo/api/server/v1/episodes/${encodeURIComponent(episodeId)}`;
  const deadline = AbortSignal.timeout(timeout);
  const options = { signal: reader ? AbortSignal.any([reader.signal, deadline]) : deadline, headers: {
    ...(state.runId ? { "X-SPIRA-Demo-Run": state.runId } : {}),
    ...(REPLAY ? { "X-SPIRA-Demo-Replay": "1" } : {}),
  } };
  const detail = async (kind, path) => {
    let payload;
    try {
      const value = await observe(kind, path, options, { read });
      if (value.episode_id !== episodeId || (kind === "episode" && value.household_id !== state.config.household_id)) return;
      payload = { [kind]: value, ...(kind === "rationale" ? { rationaleMissing: false } : {}) };
    } catch (error) {
      if (state.reader !== reader || options.signal.aborted) return;
      if (!state.config.fixture) {
        const problem = readProblem(error.status);
        if (problem) payload = { problem };
      } else if (error.status !== 404) return;
      else if (kind === "rationale") {
        payload = { rationaleMissing: true };
        state.record?.("rationale_missing", null, ...stamp(), read);
      }
      else if (!state.episode && !state.sharing && state.page === "reason" && state.sharedEpisode !== episodeId) {
        notice("아직 이 주문 기록을 열 수 없어요. 예시 주문을 공유해 주세요.");
      }
    }
    if (!payload || state.reader !== reader) return;
    acceptEpisodeRead(episodeId, read, kind, payload);
    renderArrival();
  };
  await Promise.allSettled([
    detail("episode", episodePath), detail("rationale", `${episodePath}/rationale`),
    readCards(episodeId, read, since, options),
  ]);
}

async function react(cardId, taskId, reaction) {
  if (state.reactionPending || state.sharing || state.homeBusy || REPLAY) return;
  const card = state.cards.find(({ card_id }) => card_id === cardId);
  const line = card?.lines.find(({ task_id }) => task_id === taskId);
  if (!card || card.stopped || state.episode?.status === "closed") return;
  if (reaction === "stop" ? !card.buttons.includes("stop") : !line || allowedReaction(card, line) !== reaction) return;
  log("reaction", { card_id: cardId, reaction, ...(taskId ? { task_id: taskId } : {}) });
  const pending = { cardId, taskId };
  state.reactionPending = pending;
  state.controlError = "";
  renderPhone();
  try {
    const result = await exchange("/demo/api/reaction", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: cardId, reaction, ...(taskId ? { task_id: taskId } : {}) }),
      signal: AbortSignal.timeout(12000),
    });
    if (result.body?.code === "line_started") {
      state.started.add(taskId);
      state.controlError = "이미 시작된 항목은 켤 수 없어요.";
    } else if (!result.ok || result.body?.card_id !== cardId) {
      state.controlError = "준비 변경을 확인하지 못했어요.";
    } else if (reaction === "stop" && result.body.stopped) {
      pending.awaitingStop = !state.cards.find(({ card_id }) => card_id === cardId)?.stopped;
    } else if (reaction !== "line_on" && !(reaction === "line_off" && !result.body.stopped &&
      result.body.lines?.some(({ task_id, state }) => task_id === taskId && state === "off"))) {
      state.controlError = reaction === "line_off" ? "꺼짐 상태를 확인하지 못했어요." : "중지를 확인하지 못했어요.";
    }
  } catch {
    state.controlError = "서버 응답을 확인하지 못했어요.";
  } finally {
    if (!pending.awaitingStop) state.reactionPending = null;
    renderPhone();
    await refreshCards().catch(() => {});
  }
}

async function refreshMemory() {
  const { reader } = state;
  const final = reviewsReady();
  let problem = null;
  const memory = await observe("memory", `/demo/api/server/v1/households/${encodeURIComponent(state.config.household_id)}/memory`,
    { signal: AbortSignal.timeout(4000) }).catch((error) => {
    if (!state.config.fixture) problem = readProblem(error.status);
    return null;
  });
  if (state.reader !== reader || (state.finalMemory && (!final || !memory))) return;
  if (memory || problem) acceptReadProblem("memory", problem);
  state.memory = memory;
  state.finalMemory = final && Boolean(memory);
  if (state.page === "house") renderTimeline();
}

function goHouse(index, { followGuest = false } = {}) {
  const moments = timeline();
  const moment = moments[index];
  const selected = RECORDING ? state.replayStep : moments.indexOf(currentMoment(moments));
  if (!moment?.ready || state.homeBusy || index === selected) return false;
  notice();
  state.recordOpen = state.recordRequested = false;
  if (RECORDING) {
    state.replayStep = index;
    playReplayVisit();
    return true;
  }
  state.pendingClockLines.clear();
  state.followGuest = !REPLAY && moment.kind === "guests" && (followGuest || !observedGuestLine(moment, moments));
  selectHouseMoment(moment);
  renderTimeline({ follow: false });
  return true;
}

function recordedMoment({ id, kind, at, story, title, lead, room, signal, focusDevices, lines }) {
  return { id, kind, at, story, title, lead, room, signal, focusDevices,
    lines: lines?.map(({ observed }) => ({ observed: observed.map(({ device }) => ({ device })) })) };
}

function rememberFacts(facts) {
  for (const fact of facts) {
    const key = JSON.stringify([fact.event, Date.parse(fact.at), fact.device]);
    if (!state.facts.has(key)) state.facts.set(key, fact);
  }
}

async function presenterAction({ name, event }) {
  if (REPLAY || state.homeBusy || !canEnterHouse()) return;
  state.homeBusy = true;
  renderControls();
  const { reader } = state;
  const before = new Set(state.facts.keys());
  let focus;
  try {
    if (name === "clock") {
      await moveClockTo(null, { episodeId: state.episodeId, signal: reader.signal });
    } else {
      state.pendingClockLines.clear();
      const path = event ? "/demo/api/home/" : "/demo/api/person/";
      const result = await exchange(path + name, { method: "POST", signal: AbortSignal.timeout(8000) });
      if (state.reader !== reader) return;
      log("presenter", { action: name, status: result.status, result: result.body });
      if (!result.ok) throw new Error(result.status);
      if (event && result.body?.occurred_at) rememberFacts([{ event, at: result.body.occurred_at }]);
      await Promise.allSettled([refreshSnapshot(), refreshHouseMarkers()]);
      focus = [...state.facts].find(([key, fact]) => !before.has(key) && fact.event === (event ?? "person"))?.[1];
    }
  } catch (error) {
    if (state.reader === reader) notice(`집에서 확인하지 못했어요. (${error.message})`);
  } finally {
    if (state.reader === reader) {
      state.homeBusy = false;
      const index = focus ? timeline().findIndex((moment) => moment.ready && moment.event === focus.event &&
        Date.parse(moment.at) === Date.parse(focus.at) && (!focus.device || moment.focusDevices.includes(focus.device)))
        : -1;
      if (!goHouse(index, { followGuest: event === "guest_arrived" })) renderTimeline();
    }
  }
}

function acceptHub(hub) {
  state.hub = hub;
  refreshChain();
  resolveHouseLink();
  if (state.page === "reason") renderReason();
  else renderTimeline();
}

async function refreshSnapshot() {
  const { reader } = state;
  const snapshot = await observe("snapshot", "/demo/api/sim/snapshot", { signal: AbortSignal.timeout(2500) });
  if (state.reader !== reader) return;
  state.snapshot = snapshot;
  refreshChain();
  if (state.page === "house") {
    renderTimeline();
    void loadHouse();
  } else renderPhone();
  revealHouseState();
}

async function refreshHouseMarkers() {
  const { reader } = state;
  const markup = await observe("viewer", "/demo/api/sim/viewer", { signal: AbortSignal.timeout(2500) }, { text: true });
  if (state.reader === reader) {
    applyHouseMarkers(markup);
    if (state.page === "house") {
      renderTimeline();
      void loadHouse();
    }
  }
}

const MARKER_TAGS = new Set(["SECTION", "DIV", "ARTICLE", "H2", "H3", "SPAN", "SMALL", "P", "BUTTON", "UL", "LI", "TIME"]);
const MARKER_ATTRIBUTE = /^(?:id|class|title|role|type|tabindex|datetime|popover|popovertarget|aria-[a-z-]+|data-[a-z-]+)$/;

function applyHouseMarkers(markup) {
  if (!markup || markup === state.houseMarkup) return;
  const fragment = new DOMParser().parseFromString(markup, "text/html");
  const markers = fragment.getElementById("viewer-markers");
  if (!markers || markers.tagName !== "DIV") return;
  for (const node of [markers, ...markers.querySelectorAll("*")]) {
    if (!MARKER_TAGS.has(node.tagName) || ["planned", "planned-clock", "planned-detail", "observed-outcome"].some((name) => node.classList.contains(name))) {
      node.remove();
      continue;
    }
    for (const attr of [...node.attributes]) {
      if (!MARKER_ATTRIBUTE.test(attr.name)) node.removeAttribute(attr.name);
    }
  }
  state.houseMarkup = markup;
  if (!RECORDING) rememberFacts(worldFacts(markers));
  state.displayReadings = new Map([...markers.querySelectorAll("[data-device][data-values]")].map(
    ({ dataset }) => [dataset.device, JSON.parse(dataset.values)]));
  if (state.houseModule) state.houseModule.replaceHouseMarkers($("viewer-markers"), markers);
  else $("viewer-markers").replaceWith(markers);
  state.house?.setMarkers(markers);
  revealHouseState();
}

function revealHouseState() {
  const ready = Boolean(state.snapshot && state.houseMarkup && $("world").hasChildNodes());
  $("house-waiting").hidden = ready;
  $("view").toggleAttribute("data-observed", ready);
}

async function refreshHub() {
  const { reader } = state;
  const hub = await observe("hub", "/demo/api/hub", { signal: AbortSignal.timeout(2500) });
  if (state.reader !== reader) return;
  acceptHub(hub);
}

async function readTags() {
  const { reader, runId, episodeId } = state;
  if (!runId || state.tagsReady || state.tagsRead === reader) return;
  state.tagsRead = reader;
  try {
    const result = await api(`/demo/tags?episode=${encodeURIComponent(episodeId)}`, {
      headers: { "X-SPIRA-Demo-Run": runId },
      signal: AbortSignal.any([reader.signal, AbortSignal.timeout(2500)]),
    });
    if (state.reader !== reader) return;
    state.tagsReady = result.ready;
    state.tags = result.tags;
    renderArrival();
  } catch {
    // The text is already on stage, and the next poll can retry.
  } finally {
    if (state.tagsRead === reader) state.tagsRead = null;
  }
}

async function pollHouse() {
  for (let tick = 0; ; tick += 1) {
    const inHouse = state.page === "house";
    if (!REPLAY && state.config.tagger && state.episodeId) void readTags();
    const reads = inHouse ? [refreshSnapshot(), refreshHouseMarkers()] : [];
    if ((inHouse || state.houseLink || state.chain.cardReady) && state.episodeId && tick % 4 === 0) {
      const reader = state.reader;
      reads.push(state.recordRequested ? refreshCards().finally(() => {
        if (state.reader === reader && !state.finalMemory) return refreshMemory();
      }) : refreshCards());
    }
    if (state.config.hub) {
      reads.push(refreshHub());
    }
    reads.push(readClock());
    await Promise.allSettled(reads);
    // A timed read-back can arrive after the clock ramp. Wait for the house poll before presenting it.
    if (inHouse && state.page === "house" && !state.recordRequested && state.pendingClockLines.size) {
      const moment = timeline().find(({ id, ready }) => ready && state.pendingClockLines.has(id));
      if (moment) {
        state.pendingClockLines.delete(moment.id);
        state.followGuest = false;
        selectHouseMoment(moment);
        renderTimeline();
      }
    }
    if (inHouse) void loadHouse();
    await sleep(800);
  }
}

async function loadHouse() {
  if (state.houseLoading || $("world").hasChildNodes() || !state.snapshot || !state.houseMarkup ||
      state.page !== "house") return;
  state.houseLoading = true;
  const base = RECORDING ? "/demo/replay-house/" : "/sim/assets/house/";
  try {
    const [module, devices, scenes, vocabulary] = await Promise.all([
      import(base + "house.js"), import(base + "devices.js"), import(base + "scene.js"), import(base + "scene-vocabulary.js"),
    ]);
    state.validateScene = scenes.validateScene;
    state.sceneVocabulary = vocabulary.default;
    state.houseModule = module;
    state.houseDevices = devices.HOUSE_DEVICES;
  } catch {
    return;
  } finally {
    state.houseLoading = false;
  }
  for (const name of ["house.css", "viewer.css"]) {
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = base + name;
    document.head.insertBefore(style, $("shell-style"));
  }
  try {
    // An empty sample map keeps the renderer's TV party atmosphere out of the shell.
    // All device readings still come from the Simulator's observed markers.
    state.house = state.houseModule.createHouse($("world"), { decorateLabel: decorateHouseLabel, sampleReadings: {} });
    state.house.setMarkers($("viewer-markers"));
  } catch (error) {
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = "이 화면에서 입체 집을 열 수 없어요.";
    $("world").append(message);
    console.error(error);
  }
  refreshChain();
  flushReplayScenes();
  renderTimeline({ instant: true });
  revealHouseState();
}

function openHouseView() {
  renderTimeline({ instant: true });
  state.house?.resize();
  void loadHouse();
}

function showPage(page) {
  if (page === "house" && !canEnterHouse()) return;
  const focusedPanel = (page === "reason" ? $("home") : $("reason")).contains(document.activeElement);
  state.page = page;
  $("reason").hidden = page !== "reason";
  $("home").hidden = page !== "house";
  $("orders").hidden = page !== "reason" || !state.config.fixture;
  if (page === "house") state.auto = null;
  else state.mapOpen = state.recordOpen = state.recordVisible = false;
  document.querySelectorAll("[data-page]").forEach((button) =>
    button.setAttribute("aria-pressed", String(button.dataset.page === page)));
  if (page === "house") {
    openHouseView();
    renderStageIndicator();
  } else {
    renderReason();
    if (state.episodeId) autoAdvance();
  }
  if (focusedPanel) (document.querySelector(`[data-page="${page}"]`)).focus({ preventScroll: true });
}

function enterHouse() {
  if (!canEnterHouse()) return;
  if (RECORDING) {
    playReplayVisit();
    showPage("house");
    if (!MANUAL) void playRecordedHouse();
    return;
  }
  log("house", { moment: recordedMoment(currentMoment()) });
  showPage("house");
  void Promise.allSettled([refreshSnapshot(), refreshHouseMarkers()]);
}

const PHONE_CLOCK = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const STORY_CLOCK = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

function tickClock() {
  const now = clockNow();
  $("story-clock").hidden = now === null;
  if (now !== null) {
    $("story-clock").textContent = STORY_CLOCK.format(now);
    $("phone-time").textContent = PHONE_CLOCK.format(now);
  }
  const second = Math.floor(performance.now() / 1000);
  if ((state.waiting || state.retryUntil > 0) && second !== state.indicatorSecond) {
    state.indicatorSecond = second;
    renderStageIndicator();
  }
  requestAnimationFrame(tickClock);
}

function canUsePhoneMap() {
  return canEnterHouse() && !state.draft && (state.page === "house" || state.step >= reasonStep("plan"));
}

function renderControls() {
  const inHouse = state.page === "house";
  const blocked = state.sharing || state.homeBusy;
  $("phone-map").disabled = blocked || !canUsePhoneMap();
  const moments = timeline();
  const index = RECORDING ? state.replayStep : moments.indexOf(currentMoment(moments));
  const previous = moments.slice(0, index).some(({ ready }) => ready);
  const next = moments.slice(index + 1).some(({ ready }) => ready);
  $("previous").disabled = blocked || (inHouse ? !previous && !state.recordRequested : state.step === 0);
  const needsShare = !inHouse && !state.episodeId;
  const waiting = !inHouse && state.episodeId && (!canMoveReasonForward() || state.draft);
  const atEnd = inHouse && (state.recordRequested || !next && !houseEnded(moments));
  $("presenter-controls").hidden = !inHouse || REPLAY || state.recordVisible;
  const clock = rehearsalControls(state.clock, state.clockMoments, state.clockMissing, REPLAY);
  $("presenter-clock").hidden = !clock.advance;
  $("clock-unavailable").hidden = !clock.unavailable;
  for (const button of $("presenter-controls").querySelectorAll("button")) button.disabled = blocked;
  $("next").disabled = blocked || atEnd || waiting || needsShare;
  $("next-share").hidden = !needsShare || state.sharing;
  $("path-control").hidden = inHouse || REPLAY || Boolean(state.episodeId && !state.draft);
  $("demo-path").value = draftPath();
  $("demo-path").disabled = blocked || !state.config.server;
  document.querySelectorAll("[data-order]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.order === state.order));
    button.disabled = blocked || !state.config.server || REPLAY || Boolean(state.reactionPending);
  });
  for (const id of ["sample", "files"]) {
    if ($(id)) $(id).disabled = blocked || !state.config.server;
  }
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.disabled = blocked || (button.dataset.page === "house" && !canUsePhoneMap());
  });
}

function houseEnded(moments) {
  return moments.some(({ kind, ready }) => kind === "end" && ready) ||
    RECORDING && state.replay.house.at(-1)?.frame.finalMemory;
}

function openRecord() {
  if (!canEnterHouse()) return;
  state.recordOpen = state.recordRequested = true;
  state.mapOpen = false;
  $("phone-content").scrollTop = 0;
  renderTimeline();
  if (!RECORDING) {
    const reader = state.reader;
    void refreshCards().then(() => {
      if (state.reader === reader) return refreshMemory();
    });
  }
}

function move(delta) {
  if (state.sharing || state.homeBusy) return;
  if (delta > 0 && state.page === "reason" && (!state.episodeId || !canMoveReasonForward() || state.draft)) return;
  state.auto = null;
  if (state.page === "house" && state.recordRequested) {
    if (delta < 0) {
      state.recordOpen = state.recordRequested = false;
      renderTimeline();
    }
  } else if (state.page === "house") {
    const moments = timeline();
    const index = RECORDING ? state.replayStep : moments.indexOf(currentMoment(moments));
    const next = delta < 0 ? moments.findLastIndex(({ ready }, i) => ready && i < index)
      : moments.findIndex(({ ready }, i) => ready && i > index);
    if (next >= 0) goHouse(next);
    else if (delta > 0 && houseEnded(moments)) {
      if (RECORDING) applyReplayFrame(state.replay.house.at(-1).frame);
      openRecord();
    }
  } else if (state.scenes.reason[state.step].id === "plan" && delta > 0) {
    enterHouse();
  } else {
    if (delta > 0) setStep(nextReasonStep());
    else {
      const previous = state.scenes.reason.slice(0, state.step).findLastIndex(({ beat }, index) =>
        !beat || reasonReady(index));
      setStep(previous);
    }
    if (delta > 0) autoAdvance();
  }
}

function canMoveReasonForward() {
  const { id } = state.scenes.reason[state.step];
  if (id === "plan") return RECORDING ? state.replay.house.length > 0 && canEnterHouse()
    : REPLAY && canEnterHouse() && stageReady("hub");
  const next = nextReasonStep();
  return (state.scenes.reason[next].id !== "plan" || canOpenPlan()) && reasonReady(next);
}

function fit() {
  const frame = $("frame");
  state.scale = Math.min(innerWidth / frame.offsetWidth, innerHeight / frame.offsetHeight);
  frame.style.setProperty("--scale", state.scale);
  state.house?.resize();
}

function resolveHouseLink() {
  if (!state.houseLink || !state.chain.ready.plan) return;
  const { record } = state.houseLink;
  if (state.runPath === "house" && !canEnterHouse()) return;
  state.houseLink = null;
  if (!canEnterHouse()) return;
  state.recordLink = record;
  enterHouse();
}

function applyReplayFrame(frame) {
  if (!frame) return;
  state.episode = frame.episode ?? null;
  state.rationale = frame.rationale ?? null;
  state.rationaleMissing = Boolean(frame.rationaleMissing);
  state.readProblems = frame.readProblems ?? {};
  state.cardsRead = Boolean(frame.cards);
  state.cards = frame.cards ?? [];
  state.hub = frame.hub ?? null;
  state.snapshot = frame.snapshot ?? null;
  state.memory = frame.memory;
  state.finalMemory = Boolean(frame.finalMemory && frame.memory);
  state.replayTime = frame.storyAt;
  refreshChain();
  applyHouseMarkers(frame.viewer);
  revealHouseState();
}

function flushReplayScenes() {
  if (!state.house || !state.replayPending?.length) return;
  for (const { frame, scene, moment } of state.replayPending.splice(0)) {
    applyReplayFrame(frame);
    if (scene) sendScene(state.house, state.validateScene, scene);
    else state.house.clearScene();
    if (moment) {
      updateHousePresentation(moment);
      directHouse(moment);
    }
  }
}

function playReplayVisit() {
  const visit = state.replay.house[state.replayStep];
  clearTimeout(state.replaySceneTimer);
  state.replayPending ??= [];
  const previous = state.replayVisit;
  if (previous) state.replayPending.push(...previous.scenes.slice(state.replaySceneIndex));
  state.replayVisit = visit;
  state.replaySceneIndex = 0;
  applyReplayFrame(visit.scenes[0]?.frame ?? visit.frame);

  const dwell = DWELL_MS ?? 6500;
  const showNext = () => {
    const next = visit.scenes[state.replaySceneIndex++];
    state.replayPending.push(next ?? { frame: visit.frame, moment: visit.moment });
    flushReplayScenes();
    if (state.replaySceneIndex < visit.scenes.length) {
      state.replaySceneTimer = setTimeout(showNext, dwell / visit.scenes.length);
    }
  };
  showNext();
  if (state.page === "house") renderTimeline();
}

async function playRecordedHouse() {
  const playback = {};
  state.auto = playback;
  while (state.auto === playback && state.page === "house" && !state.recordRequested) {
    await sleep(DWELL_MS ?? 6500);
    if (state.auto !== playback || state.page !== "house") return;
    if (state.replayStep < timeline().length - 1) goHouse(state.replayStep + 1);
    else {
      if (houseEnded(timeline())) {
        applyReplayFrame(state.replay.house.at(-1).frame);
        openRecord();
      }
      break;
    }
  }
  if (state.auto === playback) state.auto = null;
}

async function boot() {
  const [source, sceneData, itemTypes] = await Promise.all([
    api(RECORDING ? `/demo/api/recordings/${encodeURIComponent(RECORDING)}` : "/demo/api/config", {
      headers: query.has("episode") ? { "X-SPIRA-Demo-Episode": query.get("episode") } : {},
    }),
    api(new URL("./scenes.json", import.meta.url)),
    api(new URL("./item-types.json", import.meta.url)),
  ]);
  state.scenes = sceneData;
  state.itemTypes = itemTypes;
  state.config = RECORDING ? { household_id: source.household_id, story_timing: source.story_timing } : source;
  const stages = state.scenes.reason;
  state.scenes.reason = stages.flatMap((scene) => {
    const beats = JUDGMENT_STAGES[scene.id] ?? [];
    return beats.length ? beats.map((beat) => ({ ...scene, beat })) : [scene];
  });
  state.flow = createFlow($("stage-steps"), $("stage-beat"));
  $("orders").hidden = !state.config.fixture;
  $("demo-path").onchange = (event) => {
    if (!state.sharing) state.draftPath = event.target.value;
  };
  $("orders").addEventListener("click", (event) => {
    const button = event.target.closest("[data-order]");
    if (button) chooseOrder(button.dataset.order);
  });
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.onclick = () => {
      notice();
      if (button.dataset.page === "house" && state.page === "reason") {
        if (canUsePhoneMap()) enterHouse();
      }
      else showPage(button.dataset.page);
    };
  });
  $("timeline").addEventListener("click", (event) => {
    const button = event.target.closest("[data-step]");
    if (button) goHouse(Number(button.dataset.step));
  });
  $("presenter-controls").addEventListener("click", (event) => {
    const button = event.target.closest("[data-presenter]");
    if (button) void presenterAction({ name: button.dataset.presenter, event: button.dataset.event });
  });
  $("phone-map").onclick = () => {
    if (state.sharing || state.homeBusy || !canUsePhoneMap()) return;
    state.mapOpen = true;
    $("phone-content").scrollTop = 0;
    document.querySelectorAll(".flight").forEach((clone) => clone.remove());
    if (state.page === "reason") return enterHouse();
    renderPhone();
  };
  $("phone-order").onclick = () => {
    state.mapOpen = false;
    state.recordOpen = false;
    state.draft = false;
    $("phone-content").scrollTop = 0;
    renderPhone();
    renderControls();
  };
  $("phone-content").onclick = (event) => {
    const button = event.target.closest("button[data-reaction]");
    if (button?.dataset.reaction) return react(button.dataset.card, button.dataset.task, button.dataset.reaction);
  };
  $("previous").onclick = () => move(-1);
  $("next").onclick = () => move(1);
  document.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.repeat ||
      event.target.closest("input, textarea, select")) return;
    if (event.key.toLowerCase() === "r") {
      location.href = "/demo?recordings";
    } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      move(event.key === "ArrowRight" ? 1 : -1);
    }
  });
  window.addEventListener("resize", fit);
  fit();

  $("frame").toggleAttribute("data-owners", query.get("owners") === "1");
  // Rehearsal aid: ?camera=<name> holds a named camera (for framing close-ups).
  if (query.get("camera")) setTimeout(() => {
    $("view").setAttribute("data-closeup", "");
    state.house?.focus(roomCamera(query.get("camera")), { instant: true });
  }, 1500);
  if (RECORDING) {
    state.episodeId = source.episode_id;
    state.replay = replayFrames(source.entries, state.scenes.house);
    state.runPath = source.demo_path ?? (state.replay.house.length ? "house" : "plan");
    state.tags = source.tags?.data ?? [];
    applyReplayFrame(state.replay.judgment);
    setStep(reasonStep("extract"));
    if (!state.episode) notice("이 녹화에는 받은 주문 결과가 없어요.");
    autoAdvance();
    tickClock();
    return;
  }
  const id = query.get("episode");
  const requested = Number(query.get("step") || 0);
  const stage = Number.isInteger(requested) ? stages[Math.max(0, Math.min(stages.length - 1, requested))] : stages[0];
  const inHouse = id && (query.get("page") === "house" || requested === 6 || requested === 7);
  const step = reasonStep(inHouse ? "plan" : stage.id);
  state.houseLink = inHouse ? { record: requested === 7 } : null;
  state.cardOpen = Boolean(id && (inHouse || step >= reasonStep("plan")));
  if (id) readEpisode(id);
  setStep(step);
  if (id && !inHouse && (REPLAY || !query.has("step"))) autoAdvance();
  if (!state.config.server) notice("서버 연결 없음");
  pollHouse();
  tickClock();
}

boot().catch((error) => {
  notice("시연 화면을 불러오지 못했어요.");
  console.error(error);
});

for (const button of document.querySelectorAll(".room-key [data-room]")) {
  const { room } = button.dataset;
  button.textContent = ROOM_NAMES[room];
  button.addEventListener("click", () => {
    const moment = currentMoment();
    if (!state.house || !moment) return;
    clearTimeout(closeupTimer);
    state.roomCameraMoment = moment.id;
    $("view").removeAttribute("data-closeup");
    selectRoomCamera(room);
    state.house.focus(roomCamera(room));
  });
}
