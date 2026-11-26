const STARTED_STATES = new Set(["running", "done", "partial", "user_changed", "unknown"]);

const STAGE_SOURCE = {
  extract: "episode", context: "rationale", intent: "rationale", tasks: "rationale", plan: "cards",
};
const READ_NOTICES = {
  missing: "서버가 아직 이 단계를 내보내지 않아요",
  failed: "서버에서 이 단계의 결과를 받지 못했어요.",
};

export function readProblem(status) {
  if (status === 404 || status === 405) return "missing";
  if (status >= 400 && status < 500 && status !== 408 && status !== 429) return "failed";
  return null;
}

export function stageNotice(stage, problems) {
  if (stage === "record") return READ_NOTICES[problems.rationale] ?? READ_NOTICES[problems.memory];
  return READ_NOTICES[problems[STAGE_SOURCE[stage]]];
}

export function shareControls(fixture, capture, buttonState, inputState) {
  return `${fixture ? `<div class="scan-picture"><img src="${capture()}" alt="공유할 주문 화면"></div>` : ""}
    <div class="phone-share order-actions">
      ${fixture ? `<button type="button" id="sample"${buttonState}>예시 주문으로 공유 <span aria-hidden="true">↗</span></button>` : ""}
      <label>주문 분석하기<input type="file" id="files" accept="image/png,image/jpeg" multiple${inputState}></label>
    </div>`;
}

export function rehearsalControls(clock, moments, missing, replay) {
  return { advance: !replay && Boolean(clock && moments && !missing), unavailable: !replay && missing };
}

export function startedLines(previous, cards, executions = []) {
  return new Set([...previous,
    ...executions.filter(({ status }) => status !== "blocked").map(({ task_id }) => task_id),
    ...cards.flatMap(({ lines }) => lines.filter(({ state, end_state }) =>
      STARTED_STATES.has(state) || end_state != null).map(({ task_id }) => task_id)),
  ]);
}

export function lineReaction(card, line, started = new Set(), episodeStatus) {
  if (episodeStatus === "closed" || card.stopped || line.end_state != null) return null;
  if (line.state === "off") return started.has(line.task_id) ? null : "line_on";
  if (["held", "scheduled", "blocked"].includes(line.state) || STARTED_STATES.has(line.state) ||
      (line.state === "failed" && started.has(line.task_id))) return "line_off";
  return null;
}

export function reactionConfirmed(card, pending) {
  if (!card || !pending?.ack) return false;
  if (pending.reaction === "stop") return card.stopped;
  if (card.stopped) return false;
  if (pending.reaction === "line_off") {
    return card.lines.some(({ task_id, state }) => task_id === pending.taskId && state === "off");
  }
  const previousTask = card.lines.some(({ task_id }) => task_id === pending.taskId);
  const priorIds = new Set(pending.before.map(({ task_id }) => task_id));
  const newLine = pending.ack.lines.find(({ task_id, checked }) => !priorIds.has(task_id) && checked);
  return !previousTask && Boolean(newLine && card.lines.some(({ task_id, checked }) => task_id === newLine.task_id && checked));
}
