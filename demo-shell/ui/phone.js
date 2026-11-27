import { END_WORDS, LINE_WORDS, ROOM_NAMES, STATE_WORDS, VERDICT_WORDS } from "/demo/shared/vocabulary.js";
import { expectedAction, lineReaction, shareControls, stageNotice } from "./wire.js";
import { paintTheme } from "./judgment-view.js";
import { esc, rows, setMarkup } from "./markup.js";
import { itemIcon } from "./tags.js";

export function createPhone(context, ui) {
  const { state, REPLAY, $, PHONE_CLOCK, OWNERS, MANUAL, notice, exchange, defaultPath } = context;

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

  // Line states and the after-party review use the App's words (demo-shell/design/vocabulary.json) and
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
    const theme = ui.reasoning.themeFor(state.chain.intents.find((intent) => intent.cardId === card.card_id));
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
    const ids = new Set(ui.house.currentMoment()?.lines?.map(({ id }) => id));
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
      notification: ui.reasoning.canPresentCard() && (state.notifications.size || (!state.cardOpen && state.cards.length)),
      cardOpen: ui.presenter.canUsePhoneMap() && state.cardOpen,
      cardless: ui.presenter.canUsePhoneMap() && state.chain.cardReady && !state.cards.length,
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
    const plan = state.cardOpen || (ui.reasoning.canPresentCard() && cardReady && !cards.length);
    const storyNow = ui.presenter.clockNow();
    $("phone-time").textContent = storyNow !== null ? PHONE_CLOCK.format(storyNow) : plan ? cardClock : orderClock;
    $("phone-owner").textContent = OWNERS[state.mapOpen ? "home" : plan ? "card" : "share"];
    $("phone-order").textContent = plan ? "준비" : "주문";
    $("phone-order").setAttribute("aria-pressed", String(!state.mapOpen));
    $("phone-map").setAttribute("aria-pressed", String(state.mapOpen));
    $("phone-map").toggleAttribute("data-expected", expected === "house");
    $("phone-order").toggleAttribute("data-expected", expected === "preparations");
    const notification = state.notifications.keys().next().value;
    const cardButton = !REPLAY && ui.reasoning.canPresentCard() && (notification || (!state.cardOpen && cards.length))
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

  function openCard(notification = state.notifications.keys().next().value) {
    if (!ui.reasoning.canPresentCard() || !state.cards.length || state.sharing || state.homeBusy) return;
    if (notification) {
      state.notifications.delete(notification);
      state.dismissed.add(notification);
    }
    const wasOpen = state.cardOpen;
    state.cardOpen = true;
    $("phone-content").scrollTop = 0;
    if (state.page === "reason" && !wasOpen) {
      if (state.step === ui.reasoning.reasonStep("tasks") && ui.reasoning.reasonReady(state.step) &&
          (MANUAL || performance.now() >= state.shownAt + ui.reasoning.stageDwell())) ui.reasoning.setStep(ui.reasoning.reasonStep("plan"));
      else {
        ui.reasoning.renderReason();
        ui.reasoning.autoAdvance();
      }
      $("phone-map").focus({ preventScroll: true });
    } else {
      renderPhone();
    }
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
      state.recordOpen = false;
      applyCapture(URL.createObjectURL(files[0]));
      state.draft = false;
      state.draftPath = null;
      state.cardOpen = false;
      state.mapOpen = false;
      ui.episode.readEpisode(accepted.episode_id, { data: { ...accepted, sample, images: files.length }, at: sharedAt, demoPath });
      ui.reasoning.setStep(0);
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
      await ui.episode.refreshCards().catch(() => {});
    }
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
    ui.reasoning.renderStageIndicator();
    if (!state.recordVisible) return;
    $("reason-layout").dataset.stage = "record";
    const markup = `<div class="copy-enter"><header class="stage-head"><h1>${esc(state.scenes.record.title)}</h1></header>
    <div class="record-grid"><section>${recordReviews(state.chain.cards, "h2") ||
        (problem ? `<p>${problem}</p>` : "")}</section>
    <section class="memory-panel"><h2>이 집의 기억</h2>${memoryContent()}</section></div></div>`;
    setMarkup($("stage-copy"), markup);
  }

  return {
    recordReady, renderPhone, reviewsReady, renderEnding, draftPath, chooseOrder, react, openCard, shareSample,
  };
}
