import { esc, rows, setMarkup } from "./markup.js";
import { stageNotice } from "./wire.js";

const VERDICTS = { match: "예상대로 쓰였어요", stopped: "멈추셨어요", unconfirmed: "확인하지 못했어요" };
const FEEDBACK = { off: "끔", changed: "바꿈", kept: "그대로" };

export function createHouseRecord({ state, $, RECORDING }, ui) {
  function cardIds() {
    return [...new Set([
      ...(state.episode?.card_ids ?? []),
      ...state.cards.map(({ card_id }) => card_id),
      ...(state.rationale?.observations ?? []).map(({ card_id }) => card_id),
    ])];
  }

  function observation(id) {
    return state.rationale?.observations?.find(({ card_id, verdict }) => card_id === id && verdict);
  }

  function ready() {
    const ids = cardIds();
    return ids.length > 0 && ids.every(observation);
  }

  function cardRecord(id) {
    const result = observation(id);
    if (!result) return "";
    const card = state.cards.find(({ card_id }) => card_id === id);
    const rationale = state.rationale;
    const title = card?.text ?? rationale.intents?.find(({ card_id }) => card_id === id)?.intent_text;
    const names = new Map((rationale.tasks ?? []).map(({ task_id, line }) => [task_id, line]));
    for (const { task_id, text } of card?.lines ?? []) names.set(task_id, text);
    return `<section class="context-card">${title ? `<h2>${esc(title)}</h2>` : ""}
      <p class="pill">${esc(VERDICTS[result.verdict])}</p>
      <ul class="plan-list">${rows(result.task_feedback ?? [], ({ task_id, user }) =>
        `<li><strong>${esc(FEEDBACK[user])}</strong><span>${esc(names.get(task_id))}</span></li>`)}</ul></section>`;
  }

  function unavailable() {
    return stageNotice("record", state.readProblems) ??
      (ui.reasoning.missingJudgment() ? stageNotice("record", { rationale: "missing" }) : null);
  }

  function render() {
    const problem = unavailable();
    const complete = ready();
    state.finalMemory = complete && state.episode?.status === "closed";
    state.recordVisible = state.page === "house" && state.recordRequested;
    $("reason").hidden = state.page !== "reason" && !state.recordVisible;
    $("home").hidden = state.page !== "house" || state.recordVisible;
    ui.reasoning.renderStageIndicator();
    if (!state.recordVisible) return;
    $("reason-layout").dataset.stage = "record";
    $("stage-copy").setAttribute("aria-busy", String(!complete && !problem && !RECORDING));
    const notice = complete ? "" : `<p class="lead">${esc(problem ?? "아직 판정 전")}</p>`;
    setMarkup($("stage-copy"), `<header class="stage-head"><h1>기록</h1></header>
      <div id="judgment-scene">${rows(cardIds(), cardRecord)}${notice}</div>`);
  }

  function open() {
    state.house?.focus();
    state.recordRequested = true;
    state.mapOpen = false;
    ui.house.renderTimeline();
    if (!RECORDING) void ui.episode.refreshCards();
  }

  return { open, ready, render, unavailable };
}
