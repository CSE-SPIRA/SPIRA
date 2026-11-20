import { displayTime, storyClock, storyLedgerTime, storyObservedTime, storyPlanTime } from "./story-time.js";

const SLOT_LABELS = { event: "행사", guests: "손님", activity: "활동", theme: "테마" };
const TRIGGERS = { guest_arrived: "손님이 오면", event_end: "행사가 끝나면", "package.brought_in": "택배를 들여오면" };
const OCCURRENCES = { guest_arrived: "손님 도착", event_end: "행사 종료", "package.brought_in": "택배 들여옴" };
const DEVICE_TYPES = {
  light: "조명", display: "TV", cleaner: "로봇청소기", cooktop: "인덕션",
  oven: "오븐", fridge: "냉장고", smart_plug: "스마트 플러그", speaker: "스피커",
};
export const HOUSE_DEVICES = {
  cleaner_01: { label: "로봇청소기", room: "living_room" },
  light_01: { label: "거실 조명", room: "living_room" },
  display_01: { label: "TV", room: "living_room" },
  cooktop_01: { label: "인덕션", room: "kitchen" },
  oven_01: { label: "오븐", room: "kitchen" },
  fridge_01: { label: "냉장고", room: "kitchen" },
  plug_kettle: { label: "전기포트 플러그", room: "kitchen" },
};

function lineTime(when, clock) {
  if (!when?.time) return { story: TRIGGERS[when?.event] ?? when?.event ?? "", derivation: null };
  const at = storyPlanTime(when.time, clock);
  const story = displayTime(at);
  if (!clock) return { story, derivation: null };
  const minutes = Math.round((clock.storyStart - at) / 60000);
  const relative = minutes === 0 ? "같은 시각" : `${Math.abs(minutes)}분 ${minutes > 0 ? "전" : "후"}`;
  return { story, derivation: `${displayTime(clock.storyStart)} 일정 → ${relative} → ${story}` };
}

function chainDevices(tasks, details, snapshot) {
  const observed = new Map((snapshot?.devices ?? []).map((device) => [device.logical_id, device]));
  const traces = new Map();
  for (const task of tasks) {
    for (const id of task.devices) {
      if (!traces.has(id)) traces.set(id, []);
      traces.get(id).push(task.id);
    }
  }
  const ids = new Set([...Object.keys(HOUSE_DEVICES), ...observed.keys(), ...traces.keys()]);
  return Array.from(ids, (logicalId) => {
    const model = HOUSE_DEVICES[logicalId];
    const live = observed.get(logicalId);
    const planned = details.get(logicalId);
    const type = live?.device_type ?? planned?.type;
    return {
      logicalId,
      label: model?.label ?? live?.label ?? DEVICE_TYPES[type] ?? type ?? logicalId,
      room: model?.room ?? live?.room ?? planned?.room ?? null,
      chosen: traces.has(logicalId),
      state: live?.values ?? null,
      traces: traces.get(logicalId) ?? [],
      modeled: Boolean(model),
      available: live?.available,
      observation: live?.observation,
      substrate: live?.substrate,
      assumption: live?.assumption,
    };
  });
}

function reportKey(row, report) {
  return JSON.stringify([row.device, Date.parse(row.at), report.kind, report.id]);
}

function ledgerReports(ledger, episodeId, cards, clocks, firstClock, timing) {
  const completions = new Set();
  for (const row of ledger) {
    if (row.kind !== "run" || row.status !== "completed" || !row.device) continue;
    for (const report of row.reports ?? []) {
      if (report.kind === "event") completions.add(reportKey(row, report));
    }
  }
  return ledger.filter((row) => row.kind !== "event" || !row.event_type?.endsWith(".completed") ||
    !row.reports?.length || !row.reports.every((report) => completions.has(reportKey(row, report))))
    .map((row) => {
      const command = row.commands?.[0];
      const planId = row.timing?.plan_id ?? row.plan_id ?? command?.plan ?? null;
      const taskId = row.timing?.task_id ?? row.task_id ?? command?.task ?? null;
      const deviceId = row.device ?? null;
      const card = cards.find(({ lines }) => lines.some((line) => line.task_id === taskId));
      const clock = !timing ? firstClock : planId && planId !== episodeId ? null
        : card ? clocks.get(card.card_id) : firstClock;
      const label = OCCURRENCES[row.event_type ?? row.timing?.event];
      return {
        ...row, planId, taskId, deviceId,
        deviceIds: deviceId ? [deviceId] : (row.items ?? []).map(({ device }) => device),
        story: storyLedgerTime(row, clock, label),
      };
    });
}

function houseTimeline(episode, episodeId, ledger, cards, clocks, firstClock, tasks) {
  const receipt = ledger.findLast((row) => row.kind === "plan" && row.plan_id === episodeId);
  const safety = tasks.find((task) => task.devices.includes("cooktop_01"));
  const party = cards.find((card) => card.starts_at);
  const events = Object.fromEntries(Object.entries(OCCURRENCES).map(([event, label]) => {
    const at = ledger.findLast((row) => row.event_type === event &&
      (!episode?.shared_at || Date.parse(row.at) >= Date.parse(episode.shared_at)))?.at;
    return [event, { at, story: storyObservedTime(at, firstClock, label) }];
  }));
  return {
    plan: { at: receipt?.at, story: storyObservedTime(receipt?.at, firstClock) },
    before: { at: safety?.time.at, story: safety?.time.at ? safety.time.story : "" },
    party: { at: party?.starts_at, story: displayTime(party?.starts_at, clocks.get(party?.card_id)?.offset) },
    events,
  };
}

export function buildChain({ episode, rationale, card, hubPlan, hubLedger = [], snapshot, storyTime } = {}) {
  const cards = Array.isArray(card) ? card : card ? [card] : [];
  const episodeId = episode?.episode_id ?? rationale?.episode_id ?? cards[0]?.episode_id;
  const sources = rationale?.evidence;
  const evidence = {
    calendar: sources?.calendar ?? [], unusual: sources?.unusual_items ?? null,
    kbCounts: sources?.kb_counts ?? null, kbExamples: sources?.kb_examples ?? [], kbNote: sources?.kb_note ?? null,
  };
  const unbundled = rationale?.unbundled ?? [];
  const items = (episode?.items ?? []).map(({ type, name, qty, item_id }) => ({
    id: type, name, qty, unbundled: unbundled.includes(type), sourceId: item_id,
  }));
  const basisIds = (basis) => basis.map((id) => {
    if (id === "가구 유형" || evidence.calendar.some((event) => event.id === id)) return id;
    return items.find((item) => item.id === id || item.sourceId === id || item.name === id)?.id ?? id;
  });

  const slots = [];
  const intentRows = rationale?.intents ?? [];
  const intents = intentRows.map((intent, index) => {
    const { intent_id, card_id, situation, basis, calendar_event_id } = intent;
    const duplicate = intentRows.some((other, n) => n !== index && other.intent_id === intent_id);
    const id = duplicate ? `${intent_id}:${card_id ?? index}` : intent_id;
    const situationSlots = Object.entries(SLOT_LABELS).map(([key, label]) => ({
      id: `${id}/${key}`, key, label, value: situation[key], basis: basisIds(basis[key]),
    }));
    slots.push(...situationSlots);
    return {
      id, text: intent.intent_text, cardId: card_id, calendarEvent: calendar_event_id,
      slotIds: situationSlots.map((slot) => slot.id), basis: basisIds(basis.intent),
    };
  });

  const intentsByCard = new Map(intents.filter(({ cardId }) => cardId).map((intent) => [intent.cardId, intent]));
  const clocks = new Map(cards.map((entry) => {
    const event = evidence.calendar.find(({ id }) => id === intentsByCard.get(entry.card_id)?.calendarEvent);
    const windows = storyTime?.guestWindows;
    const guestLine = entry.lines.find((line) => line.when?.event === "guest_arrived" && windows?.[line.task_id]);
    return [entry.card_id, storyClock(event, entry.starts_at, windows?.[guestLine?.task_id]?.to, storyTime?.timing)];
  }));
  const firstClock = Array.from(clocks.values()).find(Boolean);
  const chainCards = cards.map((entry) => {
    const clock = clocks.get(entry.card_id);
    return {
      ...entry,
      updatedStory: displayTime(entry.updated_at, clock?.offset),
      lines: entry.lines.map((line) => ({ ...line, time: lineTime(line.when, clock) })),
    };
  });
  const lines = new Map(chainCards.flatMap((entry) => entry.lines.map((line) => [line.task_id, line])));

  // The shell reads the Hub's action projection. A complete C-1 plan carries the same actions.
  const actions = Array.isArray(hubPlan?.tasks)
    ? Object.fromEntries(hubPlan.tasks.map(({ task_id, actions }) => [task_id, actions])) : hubPlan ?? {};
  const needs = new Map();
  const deviceDetails = new Map();
  const tasks = (rationale?.tasks ?? []).map((task) => {
    const { task_id: id, card_id, line, need, way } = task;
    if (!needs.has(need)) needs.set(need, []);
    needs.get(need).push(id);
    for (const device of task.devices) deviceDetails.set(device.id, device);
    const values = actions[id] ?? [];
    const devices = [...new Set([...task.devices.map((device) => device.id), ...values.map(({ device }) => device)])];
    const cardLine = lines.get(id);
    const time = { ...(cardLine?.time ?? lineTime()), at: cardLine?.when?.time };
    return { id, line, need, way, devices, time, values, intentId: intentsByCard.get(card_id)?.id ?? null };
  });

  return {
    episodeId, items, slots, intents, intent: intents[0] ?? null,
    ...(rationale && !intents.length ? { none: { reason: rationale.none_reason } } : {}),
    evidence, unbundled,
    needs: Array.from(needs, ([text, taskIds]) => ({ text, taskIds })),
    tasks,
    item_tasks: rationale?.item_tasks ?? episode?.item_tasks ?? [],
    devices: chainDevices(tasks, deviceDetails, snapshot),
    reports: ledgerReports(hubLedger, episodeId, cards, clocks, firstClock, storyTime?.timing),
    funnel: {
      items: episode?.item_count ?? 0,
      similar: (evidence.kbCounts ?? []).reduce((sum, { n }) => sum + n, 0),
      bundled: rationale ? items.filter((item) => !item.unbundled).length : 0,
      unbundled: unbundled.length,
      intents: intents.length,
      tasks: tasks.length,
      cardLines: lines.size,
      devices: new Set(Object.values(actions).flat().map(({ device }) => device)).size,
    },
    cards: chainCards,
    hasEpisode: Boolean(episode?.items), hasRationale: Boolean(rationale), hasHubPlan: Boolean(hubPlan),
    cardReady: Boolean(rationale && episode?.card_ids?.every((id) => cards.some((entry) => entry.card_id === id))),
    orderClock: displayTime(episode?.shared_at, null, false),
    cardClock: displayTime(cards[0]?.updated_at || episode?.shared_at, firstClock?.offset, false),
    timeline: houseTimeline(episode, episodeId, hubLedger, cards, clocks, firstClock, tasks),
  };
}
