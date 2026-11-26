export const SLOT_LABELS = { event: "행사", guests: "손님", activity: "활동", theme: "테마" };
export const JUDGMENT_STAGES = {
  extract: ["items"], context: ["unusual", "calendar", "similar"], intent: ["slots", "intent"], tasks: ["tasks"],
};

// One screen per stage: a stage is shown once all of its beats arrived (they arrive in one read), all at once.
export function stageScenes(scene) {
  const beats = JUDGMENT_STAGES[scene.id] ?? [];
  return beats.length ? [{ ...scene, beat: beats.at(-1), beats }] : [scene];
}

const HOUSEHOLD = "가구 유형";

function useCalendar(intents, calendar) {
  return calendar.flatMap((event) => {
    const using = intents.filter((intent) => intent.calendar_event_id === event.id);
    if (!using.length) return [];
    const items = using.flatMap(({ basis }) => Object.values(basis)
      .filter((sources) => sources.includes(event.id))
      .flatMap((sources) => sources.filter((id) => id !== HOUSEHOLD && !calendar.some((entry) => entry.id === id))));
    return [{ event, items: [...new Set(items)] }];
  });
}

// Use arrival to distinguish a confirmed empty list from stages the fixture
// has yet to publish. Keep the Server's order and its basis references.
export function buildJudgment(items, rationale, { extract, extractMissing, tasks, maskedCount, itemTaskCount = 0 } = {}) {
  if (!extract && !extractMissing) return [];
  const beats = extract ? [{ id: "items", items, maskedCount: rationale?.masked_count ?? maskedCount }] : [];
  const evidence = rationale?.evidence;
  if (!evidence) return beats;

  const { calendar, unusual_items, kb_counts, kb_examples, kb_note } = evidence;
  beats.push(
    { id: "unusual", comparison: unusual_items },
    { id: "calendar", candidates: calendar },
    { id: "similar", counts: kb_counts, examples: kb_examples.slice(0, 2), note: kb_note },
  );
  const { intents, none_reason, unbundled } = rationale;
  if (!intents.length && !none_reason) return beats;

  if (intents.length) {
    beats.push({ id: "slots", calendarUse: useCalendar(intents, calendar), groups: intents.map(({ situation, basis }) =>
      Object.entries(SLOT_LABELS).map(([key, label]) => ({ key, label, value: situation[key], basis: basis[key] }))) });
  }
  beats.push({ id: "intent", intents, reason: none_reason, unbundled });
  if (tasks) beats.push({ id: "tasks", count: rationale.tasks.length, itemTaskCount });
  return beats;
}
