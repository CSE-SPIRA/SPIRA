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
  if (stage === "record") return READ_NOTICES[problems.rationale];
  return READ_NOTICES[problems[STAGE_SOURCE[stage]]];
}

export function rehearsalControls(clock, moments, missing, replay) {
  return { advance: !replay && Boolean(clock && moments && !missing), unavailable: !replay && missing };
}
