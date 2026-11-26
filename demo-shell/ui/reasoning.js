import { STAGE_NAMES } from "./flow.js";
import { DEVICE_NAMES, STATE_WORDS } from "/demo/shared/vocabulary.js";
import { buildChain } from "./chain.js";
import { stageNotice } from "./wire.js";
import { buildJudgment } from "./judgment.js";
import {
  calendarMarkup, contextMarkup, extractionMarkup, intentMarkup, judgmentBeatLine, slotsMarkup,
} from "./judgment-view.js";
import { esc, rows, setMarkup, skeletonBars } from "./markup.js";
import { findTag, lineWithTag } from "./tags.js";

export function createReasoning(context, ui) {
  const { OWNERS, state, $, AUTO_PLAY, sleep, REPLAY, RECORDING } = context;

  const ownerTag = (owner) => `<span class="owner-tag">${OWNERS[owner]}</span>`;

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
      extract: state.chain.ready.extract,
      extractMissing: Boolean(state.readProblems.episode),
      tasks: state.chain.ready.tasks, maskedCount: episode?.masked_count,
      itemTaskCount: state.chain.item_tasks.length,
    });
    renderStageIndicator();
  }

  function renderStageIndicator() {
    const scene = state.scenes.reason[state.step];
    const stage = state.recordVisible ? "record" : state.page === "house" ? "hub" : scene.id === "share" ? "extract" : scene.id;
    const beat = state.page === "reason" && !problemFor(stage)
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
    const ready = { ...state.chain.ready, record: state.episode?.status === "closed" && ui.record.ready() };
    let prior = true;
    for (const id of ["extract", "context", "intent", "tasks", "plan"]) {
      if (problemFor(id)) {
        ready[id] = false;
        continue;
      }
      prior = ready[id] = prior && ready[id];
    }
    state.flow(stage, ready, line);

    if (!state.recordFinished && state.record && ((state.recordVisible && (state.finalMemory || ui.record.unavailable())) ||
        (state.page === "reason" && scene.id === "plan" && state.chain.cardReady && state.runPath === "plan"))) {
      state.recordFinished = true;
      ui.recording.log("finish", { stage: state.recordVisible ? "record" : "plan" });
    }
  }

  function waitingStage(scene) {
    if (state.page === "house") {
      return state.recordVisible && !state.finalMemory && !ui.record.unavailable() ? "record" : null;
    }
    if (!state.episodeId || state.draft) return null;
    if (scene.id === "share" && !reasonReady(reasonStep("extract"))) return "extract";
    if (scene.id === "plan" && state.runPath === "house" && state.cards.length && !state.chain.ready.hub) return "hub";
    if (!reasonReady(state.step)) return scene.id;
    return null;
  }

  function intentSlots(intent) {
    return intent?.slotIds.map((id) => state.chain.slots.find((slot) => slot.id === id)) ?? [];
  }

  function themeFor(intent) {
    return intentSlots(intent).find(({ key }) => key === "theme")?.value;
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
    <p class="plan-text">${esc(card.text)}</p>
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

  function waitingForQuiet() {
    const now = ui.presenter.clockNow();
    return !state.chain.ready.context && now !== null && state.quietEnd !== null && now < state.quietEnd;
  }

  function waitingForJudgment() {
    if (!waitingForQuiet()) return "판단하고 있어요.";
    const minutes = (state.quietEnd - Date.parse(state.episode.shared_at)) / 60000;
    return `같은 주문이 더 오는지 ${minutes}분 기다려요.`;
  }

  function stageBody(scene) {
    const { id, beat } = scene;
    if (id === "share") return "";
    const problem = problemFor(id);
    if (problem) return `<p class="lead">${problem}</p>`;
    const result = state.judgment.find((entry) => entry.id === beat);
    if (id === "extract") {
      if (state.episode?.status === "read_failed") return '<p class="lead">읽지 못했어요. 다시 보내 주세요.</p>';
      return extractionMarkup(result?.items, result?.maskedCount);
    }
    if (id === "context") return contextMarkup(result, state.chain.orderClock);
    if (!reasonReady(state.step)) {
      const layout = { intent: "intent", tasks: "tasks", plan: "plan" }[id];
      return `<div class="stage-skeleton" data-layout="${layout}">${skeletonBars(6)}</div>
        <p class="lead">${waitingForJudgment()}</p>`;
    }
    if (id === "intent") {
      const items = state.chain.items;
      const calendar = state.chain.evidence.calendar;
      const slots = state.judgment.find((entry) => entry.id === "slots");
      const linked = calendar.filter(({ id }) => slots?.calendarUse.some(({ event }) => event.id === id));
      const proofs = slots ? `<section id="judgment-slots">${slotsMarkup(slots.groups, items, calendar, state.tags)}</section>` : "";
      const evidence = beat === "slots" && linked.length
        ? `<section class="panel linked-calendar">${calendarMarkup(linked, slots.calendarUse, items)}</section>` : "";
      const intent = beat === "intent"
        ? `<section id="judgment-intent">${intentMarkup(result, items, calendar, state.tags)}</section>` : "";
      return `<div id="judgment-scene">${evidence}${proofs}${intent}</div>`;
    }
    if (id === "tasks") return tasksStage(state.chain);
    if (!state.chain.cardReady && state.cardsRead) return '<p class="lead">아직 도착한 준비 카드가 없어요.</p>';
    const receipt = state.runPath === "plan" && state.chain.receiptStory;
    return planStage(state.chain) + (receipt ? `<p class="lead">${esc(receipt)}</p>` : "");
  }

  function renderReason() {
    if (state.scenes.reason[state.step].beat === "slots" && noSlots()) {
      state.step += 1;
      state.shownAt = null;
    }
    const scene = state.scenes.reason[state.step];
    const { id } = scene;
    const ready = reasonReady(state.step);
    if (state.shownAt === null && ready) state.shownAt = performance.now();
    $("reason-layout").dataset.stage = id;
    renderStageIndicator();
    const { chain } = state;
    const title = id === "plan" && chain.cardReady && !problemFor(id)
      ? chain.cards.length ? scene.readyTitle : scene.noCardTitle
      : scene.title ?? STAGE_NAMES[id];
    const markup = `<div class="copy-enter"><header class="stage-head">${ownerTag("server")}
    <h1${id === "share" ? ' class="headline"' : ""}>${esc(title)}</h1>
    ${ready && scene.lead && !problemFor(id) ? `<p class="lead">${esc(scene.lead)}</p>` : ""}
    </header>${stageBody(scene)}</div>`;
    $("stage-copy").setAttribute("aria-busy", String(!ready && !RECORDING));
    setMarkup($("stage-copy"), markup);
    ui.presenter.renderControls();
  }

  function reasonStep(id) {
    return state.scenes.reason.findIndex((scene) => scene.id === id);
  }

  function stageReady(scene) {
    if (scene.id === "extract" && state.episode?.status === "read_failed") return true;
    if (scene.id === "plan" && state.cardsRead && state.readProblems.episode && !state.config.fixture) return true;
    return scene.beat ? state.judgment.some(({ id }) => id === scene.beat) : state.chain.ready[scene.id] ?? true;
  }

  function missingJudgment() {
    return state.rationaleMissing && !state.rationale && state.chain.cardReady;
  }

  function noSlots() {
    return state.judgment.some(({ id, intents }) => id === "intent" && !intents.length);
  }

  function problemFor(id) {
    const problem = stageNotice(id, state.readProblems);
    if (["context", "intent", "tasks"].includes(id)) {
      if (missingJudgment()) return stageNotice(id, { rationale: "missing" });
      if (problem && !state.chain.cardReady && ["received", "reading"].includes(state.episode?.status)) return null;
    }
    if (problem) return problem;
    if (!RECORDING) return null;
    const steps = state.scenes.reason.filter((scene) => scene.id === id);
    if (steps.some(stageReady)) return null;
    return stageNotice(id, { episode: "missing", rationale: "missing", cards: "missing" });
  }

  function reasonReady(step) {
    const scene = state.scenes.reason[step];
    return Boolean(problemFor(scene.id) || stageReady(scene));
  }

  function nextReasonStep() {
    let next = state.step + 1;
    const { id } = state.scenes.reason[state.step];
    if (problemFor(id)) {
      while (state.scenes.reason[next]?.id === id) next += 1;
    }
    if (state.scenes.reason[next]?.beat === "slots" && noSlots()) next += 1;
    return next;
  }

  function stageDwell() {
    const { beat } = state.scenes.reason[state.step];
    if (beat === "items") return 2200;
    if (beat && beat !== "tasks") return 1600;
    return 3000;
  }

  async function autoAdvance() {
    if (!AUTO_PLAY || state.auto || state.draft) return;
    const run = {};
    state.auto = run;
    while (state.auto === run && state.page === "reason" && state.step < reasonStep("plan")) {
      const remaining = state.shownAt === null ? 0 : Math.ceil(state.shownAt + stageDwell() - performance.now());
      if (remaining > 0) await sleep(remaining);
      else if (state.shownAt !== null && canMoveReasonForward()) setStep(nextReasonStep(), true);
      else {
        renderStageIndicator();
        await sleep(120);
      }
    }
    if (state.auto === run) state.auto = null;
  }

  function setStep(step, automatic = false) {
    if (!automatic) state.auto = null;
    let next = Math.max(0, Math.min(step, state.scenes.reason.length - 1));
    if (state.scenes.reason[next].beat === "slots" && noSlots()) next += 1;
    if (next !== state.step) state.shownAt = null;
    state.step = next;
    renderReason();
  }

  function canMoveReasonForward() {
    const { id } = state.scenes.reason[state.step];
    if (id === "plan") return ui.presenter.canEnterHouse();
    if (state.episode?.status === "read_failed") return id === "share";
    return reasonReady(state.step);
  }

  return {
    reasonStep, reasonReady, setStep, renderReason, autoAdvance,
    renderStageIndicator, refreshChain, missingJudgment, canMoveReasonForward, nextReasonStep,
  };
}
