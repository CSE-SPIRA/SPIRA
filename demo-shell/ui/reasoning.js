import { STAGE_NAMES } from "./flow.js";
import { DEVICE_NAMES, STATE_WORDS } from "/demo/shared/vocabulary.js";
import { buildChain } from "./chain.js";
import { stageNotice } from "./wire.js";
import { buildJudgment } from "./judgment.js";
import {
  calendarMarkup, comparisonText, intentMarkup, itemComparison, judgmentBeatLine, quantityCards, similarMarkup, slotsMarkup,
} from "./judgment-view.js";
import { esc, rows, setMarkup } from "./markup.js";
import { findTag, lineWithTag } from "./tags.js";

export function createReasoning(context, ui) {
  const { OWNERS, state, $, MANUAL, motion, sleep, REPLAY, RECORDING, DWELL_MS } = context;

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
    const ready = { ...state.chain.ready, record: ui.phone.recordReady() };
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

    if (!state.recordFinished && state.record && ((state.recordVisible && ui.phone.recordReady()) ||
        (state.page === "reason" && scene.id === "plan" && state.chain.cardReady && state.runPath === "plan"))) {
      state.recordFinished = true;
      ui.recording.log("finish", { stage: state.recordVisible ? "record" : "plan" });
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
    ui.phone.renderPhone();
    const problem = stageNotice(scene.id, state.readProblems);
    if (scene.beat && scene.beat !== "tasks" && !problem) {
      renderJudgment(copy, scene);
      ui.presenter.renderControls();
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
      setMarkup(copy, markup);
      ++flightVersion;
    }
    ui.presenter.renderControls();
  }

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

  async function autoAdvance({ cue = false } = {}) {
    if ((MANUAL && !cue) || state.auto || state.draft) return;
    const run = {};
    state.auto = run;
    while (state.auto === run && state.page === "reason" && (RECORDING || state.step < reasonStep("plan"))) {
      const remaining = state.shownAt === null ? 0 : Math.ceil(state.shownAt + stageDwell() - performance.now());
      if (remaining > 0) await sleep(remaining);
      else if (state.shownAt !== null && canMoveReasonForward()) {
        if (state.step === reasonStep("plan")) ui.presenter.enterHouse();
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

  function canMoveReasonForward() {
    const { id } = state.scenes.reason[state.step];
    if (id === "plan") return RECORDING ? state.replay.house.length > 0 && ui.house.canEnterHouse()
      : REPLAY && ui.house.canEnterHouse() && stageReady("hub");
    const next = nextReasonStep();
    return (state.scenes.reason[next].id !== "plan" || canOpenPlan()) && reasonReady(next);
  }

  return {
    themeFor, canPresentCard, reasonStep, reasonReady, stageDwell, setStep, renderReason, autoAdvance,
    renderStageIndicator, refreshChain, missingJudgment, canMoveReasonForward, nextReasonStep,
  };
}
