import { END_WORDS, LINE_WORDS } from "/demo/shared/vocabulary.js";
import { lineReaction, reactionConfirmed, shareControls, stageNotice } from "./wire.js";
import { esc, rows, setMarkup, skeletonBars } from "./markup.js";
import { displayTime } from "./story-time.js";
import { itemIcon } from "./tags.js";

const VERDICTS = { match: "예상대로 쓰였어요", stopped: "멈추셨어요", unconfirmed: "확인하지 못했어요" };
const FEEDBACK = { off: "끔", changed: "바꿈", kept: "그대로" };
const TRIGGERS = {
  guest_arrived: "손님 도착을 기다리는 중", event_end: "행사 끝을 기다리는 중",
  "package.brought_in": "택배를 기다리는 중",
};
const LINE_STATES = { ...LINE_WORDS, user_changed: "사람이 바꿈" };
const DATE = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", year: "numeric", month: "numeric", day: "numeric",
});
const SEOUL = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", dateStyle: "short" });

export function createPhone(context, ui) {
  const { state, REPLAY, RECORDING, $, PHONE_CLOCK, OWNERS, notice, exchange, defaultPath } = context;

  const SAMPLE_EPISODES = { birthday: "ep_9031", groceries: "ep_9150" };

  // These are sample inputs for the share action. Judgment always comes back from the Server.
  const SAMPLE_ORDERS = {
    birthday: ["설향 딸기 500g (냉장) × 2", "OO 컵케이크 믹스", "동물성 휘핑크림 500ml × 1",
      "OO 액체 세탁세제 3L × 1", "OO 베이비 로션 300ml × 1", "파티 풍선 세트 × 1",
      "디즈니 공주 케이크 토퍼 × 1", "파티 고깔모자 × 6", "아이싱 펜 × 1"],
    groceries: ["우유 1L × 1", "계란 10구 × 1", "바지락 400g × 1", "딸기 500g × 1", "두루마리 휴지 × 1", "주방 세제 × 1"],
  };

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

  function orderItems() {
    const { items = [], item_tasks = [], masked_count } = state.episode ?? {};
    const list = `<ul class="receipt-list">${rows(items, (item) => {
      const task = item_tasks.find(({ item: type }) => type === item.type);
      const status = task ? LINE_STATES[task.state] : "";
      return `<li class="receipt-row">${itemIcon(state.itemTypes, item.type)}
        <span>${esc(item.name)}${status ? `<small>${esc(status)}</small>` : ""}</span>
        <span class="receipt-qty">${item.qty == null ? "" : esc(item.qty) + "개"}</span>
      </li>`;
    })}</ul>`;
    return list + (masked_count ? `<p class="masked-count">가린 품목 ${esc(masked_count)}개</p>` : "");
  }

  function shareMarkup({ next = false } = {}) {
    if (REPLAY) return "";
    const disabled = state.sharing ? " disabled" : "";
    return shareControls(!next && state.config.fixture, () => esc(sampleOrder().toDataURL()),
      (state.sharing || next ? "" : " data-expected") + disabled, disabled);
  }

  function orderMarkup() {
    const header = '<div class="phone-head"><h2>주문</h2></div>';
    if (!state.episodeId || state.draft) return header + shareMarkup();
    const status = state.episode?.status ?? state.shareStatus;
    if (status === "read_failed") return header + '<p class="phone-message">읽지 못했어요. 다시 보내 주세요.</p>' + shareMarkup();
    if (state.episode?.items?.length || state.episode?.masked_count ||
        ["judged", "notified", "held", "closed"].includes(status)) {
      return header + orderItems() + (status === "closed" ? shareMarkup({ next: true }) : "");
    }
    const thumbnail = state.capture ? `<img class="order-thumbnail" src="${esc(state.capture)}" alt="공유한 주문 화면">` : "";
    const received = status ? `<p class="order-received">${thumbnail}받았어요</p>` : "";
    const unavailable = stageNotice("extract", state.readProblems);
    if (unavailable) return header + received + `<p class="phone-message">${unavailable}</p>`;
    return header + received + (status === "reading"
      ? `<div class="order-skeleton" role="status" aria-label="주문 읽는 중">${skeletonBars(4)}</div>` : "");
  }

  function phoneCard(card) {
    const pending = state.reactionPending?.cardId === card.card_id;
    const stop = !REPLAY && !card.stopped && card.buttons.includes("stop");
    const disabled = state.reactionPending || state.homeBusy ? "disabled" : "";
    const waiting = TRIGGERS[card.summary?.waiting_for];
    return `<section class="app-card"><h3>${esc(card.text)}</h3>
    ${waiting ? `<p class="card-waiting">${waiting}</p>` : ""}<ul>${rows(card.lines, (line) => {
      const reaction = allowedReaction(card, line);
      const switching = pending && state.reactionPending.taskId === line.task_id;
      const action = reaction === "line_on" ? "켜기" : "끄기";
      const status = [LINE_STATES[line.state], END_WORDS[line.end_state]].filter(Boolean).join(" · ");
      const when = displayTime(line.when?.time) || TRIGGERS[line.when?.event];
      const note = line.user_changed_note ?? line.note;
      return `<li><span>${esc(line.text)}<small>${when ? esc(when) + " · " : ""}<b class="line-state">${esc(status)}</b></small>
        ${note ? `<small>${esc(note)}</small>` : ""}</span>
      ${reaction || switching ? `<button class="phone-action app-switch" type="button"
        data-reaction="${reaction ?? ""}" data-card="${esc(card.card_id)}" data-task="${esc(line.task_id)}"
        aria-label="${esc(line.text)} ${action}" ${disabled}>${switching ? "요청함" : action}</button>` : ""}</li>`;
    })}</ul>${stop ? `<button class="phone-action app-stop" type="button" data-reaction="stop" data-card="${esc(card.card_id)}"
    ${disabled}>${pending && !state.reactionPending.taskId ? "요청함" : "멈추기"}</button>` : ""}</section>`;
  }

  function allowedReaction(card, line) {
    return REPLAY ? null : lineReaction(card, line, state.started, state.episode?.status);
  }

  function observations() {
    return state.rationale?.observations ?? [];
  }

  function observationFor(id) {
    return observations().find(({ card_id, verdict }) => card_id === id && verdict);
  }

  function memoryIds() {
    return [...new Set([
      ...(state.episode?.card_ids ?? []),
      ...state.cards.map(({ card_id }) => card_id),
      ...observations().map(({ card_id }) => card_id),
    ])];
  }

  function firstExecution(ids) {
    const times = (state.rationale?.executions ?? []).filter(({ task_id, status }) =>
      ids.has(task_id) && ["running", "completed"].includes(status)).map(({ at }) => Date.parse(at)).filter(Number.isFinite);
    return times.length ? Math.min(...times) : null;
  }

  function memoryCard(id, card = state.cards.find(({ card_id }) => card_id === id)) {
    const observation = observationFor(id);
    if (!observation) return "";
    const intent = card?.text ?? state.rationale?.intents?.find(({ card_id }) => card_id === id)?.intent_text;
    const tasks = state.rationale?.tasks?.filter(({ card_id }) => card_id === id) ?? [];
    const lineNames = new Map(tasks.map(({ task_id, line }) => [task_id, line]));
    for (const { task_id, text } of card?.lines ?? []) lineNames.set(task_id, text);
    const start = displayTime(observation.start_at ?? firstExecution(new Set(lineNames.keys())) ?? card?.starts_at);
    const end = displayTime(observation.end_at);
    return `<section class="app-card memory-card"><h3>이렇게 기억할게요</h3>
      ${intent ? `<p>${esc(intent)}</p>` : ""}<div class="app-review"><b>${esc(VERDICTS[observation.verdict])}</b>
        <ul>${rows(observation.task_feedback ?? [], ({ task_id, user }) =>
          `<li><span>${esc(lineNames.get(task_id))}</span><span>${esc(FEEDBACK[user])}</span></li>`)}</ul>
        ${start ? `<p>시작 ${esc(start)}</p>` : ""}${end ? `<p>끝 ${esc(end)}</p>` : ""}
      </div></section>`;
  }

  function memoryDate() {
    if (state.episode?.status !== "closed" || !memoryIds().length) return null;
    const scheduled = state.cards.map(({ starts_at }) => Date.parse(starts_at)).filter(Number.isFinite);
    const taskIds = new Set(state.rationale?.tasks?.map(({ task_id }) => task_id));
    return scheduled.length ? Math.min(...scheduled) : firstExecution(taskIds);
  }

  function calendarMarkup() {
    const date = memoryDate();
    const at = date ?? ui.presenter.clockNow() ?? Date.parse(state.episode?.shared_at);
    if (!Number.isFinite(at)) return '<div class="phone-head"><h2>캘린더</h2></div>';
    const { year, month, day } = Object.fromEntries(SEOUL.formatToParts(at).map(({ type, value }) => [type, Number(value)]));
    const first = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
    const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const dot = date == null ? null : day;
    return `<div class="phone-head"><h2>${year}년 ${month}월</h2></div>
    <div class="calendar-grid" aria-label="캘린더">
      ${rows(["일", "월", "화", "수", "목", "금", "토"], (name) => `<b>${name}</b>`)}
      ${'<span aria-hidden="true"></span>'.repeat(first)}
      ${rows(Array.from({ length: days }, (_, index) => index + 1), (number) => number === dot
        ? `<button type="button" id="memory-dot" aria-label="${DATE.format(date)} 준비 기록">${number}<i aria-hidden="true"></i></button>`
        : `<span>${number}</span>`)}
    </div>${state.memoryOpen ? `<section class="memory-sheet" aria-labelledby="memory-heading">
      <div class="phone-head"><h2 id="memory-heading">기억</h2><p>${DATE.format(date)}</p></div>
      ${orderItems()}${rows(memoryIds(), (id) => memoryCard(id) || '<p class="phone-message">아직 판정 전</p>')}
    </section>` : ""}`;
  }

  const calendarVisible = () => !state.draft && state.recordOpen &&
    (!state.recordRequested || state.episode?.status === "closed");

  function renderPhone() {
    const orderClock = displayTime(state.episode?.shared_at);
    const calendar = calendarVisible();
    const closed = state.episode?.status === "closed";
    const storyNow = ui.presenter.clockNow();
    $("phone-time").textContent = storyNow !== null ? PHONE_CLOCK.format(storyNow) : orderClock;
    $("phone-owner").textContent = OWNERS[calendar ? "calendar" : state.cardOpen && !closed ? "card" : "share"];
    $("phone-order").setAttribute("aria-pressed", String(!calendar));
    $("phone-calendar").setAttribute("aria-pressed", String(calendar));
    $("phone-calendar").disabled = !state.episodeId || state.draft;
    const notification = state.notifications.keys().next().value;
    let preparation = "";
    if (!closed && !state.draft && ui.reasoning.canPresentCard()) {
      if (state.cards.length && (!state.cardOpen || notification) && (!REPLAY || RECORDING)) {
        const label = notification || (RECORDING && state.cards.some(({ notify }) => notify)) ? "준비 카드 알림" : "준비 카드 열기";
        preparation += `<button type="button" class="phone-action card-notification" id="card-notification" data-expected>${label}</button>`;
      }
      if (state.cardOpen) {
        preparation += rows(state.cards, (card) => memoryCard(card.card_id, card) || phoneCard(card));
        if (state.recordRequested && !recordReady()) preparation += '<p class="phone-message">아직 판정 전</p>';
      }
    }
    const error = state.controlError ? `<p class="phone-error" role="status">${esc(state.controlError)}</p>` : "";
    const screen = calendar ? calendarMarkup() : `<div class="phone-main${preparation ? " with-preparation" : ""}">
      <section class="phone-order-area" id="phone-order-area">${orderMarkup()}</section>
      ${preparation ? `<section id="phone-preparation" aria-label="준비 카드">${error}${preparation}</section>` : error}</div>`;
    const content = $("phone-content");
    if (content.dataset.content === screen) return;
    const focused = content.contains(document.activeElement) ? document.activeElement : null;
    const scroll = content.scrollTop;
    const orderScroll = $("phone-order-area")?.scrollTop ?? 0;
    const planScroll = $("phone-preparation")?.scrollTop ?? 0;
    setMarkup(content, screen);
    content.scrollTop = scroll;
    if ($("phone-order-area")) $("phone-order-area").scrollTop = orderScroll;
    if ($("phone-preparation")) $("phone-preparation").scrollTop = planScroll;
    if (focused?.id) $(focused.id)?.focus({ preventScroll: true });
    else if (focused?.dataset.card) {
      [...content.querySelectorAll("[data-card]")].find((button) =>
        button.dataset.card === focused.dataset.card && button.dataset.task === focused.dataset.task)
        ?.focus({ preventScroll: true });
    }
    if ($("sample")) $("sample").onclick = () => shareSample();
    if ($("card-notification")) $("card-notification").onclick = () => openCard(notification);
    if ($("memory-dot")) $("memory-dot").onclick = openMemory;
    if ($("files")) $("files").onchange = (event) => {
      const files = [...event.target.files].slice(0, 3);
      if (files.length) share(files);
    };
  }

  function openCard(notification = state.notifications.keys().next().value) {
    if (!ui.reasoning.canPresentCard() || !state.cards.length || state.episode?.status === "closed" ||
        state.sharing || state.homeBusy) return;
    if (notification) {
      state.notifications.delete(notification);
      state.dismissed.add(notification);
    }
    state.cardOpen = true;
    state.recordOpen = false;
    if (state.page === "reason" && state.runPath === "house" && state.episode?.status !== "held") {
      state.houseOnReceipt = true;
      if (ui.presenter.resolveHouseLink()) return;
    }
    if (state.page === "reason") ui.reasoning.renderReason();
    else renderPhone();
  }

  function applyCapture(url) {
    if (state.capture) URL.revokeObjectURL(state.capture);
    state.capture = url;
  }

  async function shareSample() {
    if (state.sharing || !state.config.fixture) return false;
    state.sharing = true;
    ui.presenter.renderControls();
    try {
      const blob = await new Promise((resolve) => sampleOrder().toBlob(resolve, "image/png"));
      if (!blob) throw new Error("No sample image");
      return await share([new File([blob], "sample-order.png", { type: "image/png" })], state.order);
    } catch {
      notice("예시 주문 화면을 만들지 못했어요.");
      return false;
    } finally {
      state.sharing = false;
      ui.reasoning.renderReason();
    }
  }

  async function share(files, sample = null) {
    const demoPath = draftPath();
    state.sharing = true;
    ui.presenter.renderControls();
    const form = new FormData();
    for (const file of files) form.append("images", file, file.name || "order.png");
    if (sample && state.config.fixture) form.append("sample", sample);
    try {
      await ui.surface.checkHouseBeforeShare();
      notice("주문을 보내는 중이에요.");
      const sharedAt = ui.recording.stamp();
      const result = await exchange("/demo/api/order", { method: "POST", body: form, signal: AbortSignal.timeout(35000) });
      if (!result.ok || !result.body?.episode_id) throw new Error(result.status);
      const accepted = result.body;
      state.sharedEpisode = accepted.episode_id;
      state.recordOpen = state.memoryOpen = false;
      state.shareStatus = accepted.status ?? "received";
      applyCapture(URL.createObjectURL(files[0]));
      state.draft = false;
      state.draftPath = null;
      state.cardOpen = false;
      ui.episode.readEpisode(accepted.episode_id, { data: { ...accepted, sample, images: files.length }, at: sharedAt, demoPath });
      ui.reasoning.setStep(ui.reasoning.reasonStep("extract"));
      if (state.page === "house") ui.presenter.showPage("reason");
      ui.reasoning.autoAdvance();
      notice();
      return true;
    } catch (error) {
      notice(`주문을 보내지 못했어요. (${error.message})`);
      return false;
    } finally {
      state.sharing = false;
      ui.reasoning.renderReason();
    }
  }

  function chooseOrder(order) {
    if (state.sharing || state.reactionPending || REPLAY) return;
    state.order = order;
    state.draft = Boolean(state.episodeId);
    if (state.draft) state.auto = null;
    $("phone-content").scrollTop = 0;
    ui.reasoning.renderReason();
  }

  function draftPath() {
    return state.draftPath ?? (state.config.fixture ? defaultPath(SAMPLE_EPISODES[state.order]) : "house");
  }

  async function react(cardId, taskId, reaction) {
    if (state.reactionPending || state.sharing || state.homeBusy || REPLAY) return;
    const card = state.cards.find(({ card_id }) => card_id === cardId);
    const line = card?.lines.find(({ task_id }) => task_id === taskId);
    if (!card || card.stopped || state.episode?.status === "closed") return;
    if (reaction === "stop" ? !card.buttons.includes("stop") : !line || allowedReaction(card, line) !== reaction) return;
    ui.recording.log("reaction", { card_id: cardId, reaction, ...(taskId ? { task_id: taskId } : {}) });
    const pending = { cardId, taskId, reaction, before: card.lines };
    const reader = state.reader;
    state.reactionPending = pending;
    state.controlError = "";
    renderPhone();
    ui.presenter.renderControls();
    try {
      const result = await exchange("/demo/api/reaction", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ card_id: cardId, reaction, ...(taskId ? { task_id: taskId } : {}) }),
        signal: AbortSignal.timeout(12000),
      });
      if (state.reader !== reader) return;
      if (result.body?.code === "line_started") {
        state.started.add(taskId);
        state.controlError = "이미 시작된 항목은 켤 수 없어요.";
      } else if (!result.ok || result.body?.card_id !== cardId) {
        state.controlError = "준비 변경을 확인하지 못했어요.";
      } else {
        pending.ack = result.body;
        if (!reactionConfirmed(result.body, pending)) {
          pending.ack = null;
          state.controlError = { line_off: "꺼짐 상태를 확인하지 못했어요.", line_on: "켜짐 상태를 확인하지 못했어요.",
            stop: "중지를 확인하지 못했어요." }[reaction];
        }
      }
    } catch {
      if (state.reader === reader) state.controlError = "서버 응답을 확인하지 못했어요.";
    } finally {
      if (state.reader === reader) {
        if (!pending.ack || reactionConfirmed(state.cards.find(({ card_id }) => card_id === cardId), pending)) {
          state.reactionPending = null;
        }
        renderPhone();
        ui.presenter.renderControls();
        await ui.episode.refreshCards().catch(() => {});
      }
    }
  }

  function openCalendar() {
    if (!state.episodeId || state.draft) return;
    state.recordOpen = true;
    state.memoryOpen = false;
    $("phone-content").scrollTop = 0;
    if (state.page === "house") ui.house.renderTimeline();
    else renderPhone();
  }

  function openMemory() {
    if (!calendarVisible() || memoryDate() === null) return;
    state.memoryOpen = true;
    if (state.page === "house") ui.house.renderTimeline();
    else renderPhone();
    $("memory-heading")?.scrollIntoView({ block: "nearest" });
  }

  function recordReady() {
    const ids = memoryIds();
    return ids.length > 0 && ids.every(observationFor);
  }

  function renderEnding() {
    const problem = stageNotice("record", state.readProblems) ??
      (ui.reasoning.missingJudgment() ? stageNotice("record", { rationale: "missing" }) : null);
    state.finalMemory = state.episode?.status === "closed" && recordReady();
    const unavailable = state.page === "house" && state.recordRequested && problem && !recordReady();
    state.recordVisible = state.page === "house" && Boolean((state.memoryOpen && calendarVisible()) || unavailable);
    $("reason").hidden = state.page !== "reason" && !unavailable;
    $("home").hidden = state.page !== "house" || Boolean(unavailable);
    ui.reasoning.renderStageIndicator();
    if (!unavailable) return;
    $("reason-layout").dataset.stage = "record";
    setMarkup($("stage-copy"), `<header class="stage-head"><h1>기록</h1></header><p class="lead">${problem}</p>`);
  }

  return {
    recordReady, memoryDate, openCalendar, openMemory, renderPhone, renderEnding,
    draftPath, chooseOrder, react, openCard, shareSample,
  };
}
