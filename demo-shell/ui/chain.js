import { DEVICE_NAMES } from "/demo/shared/vocabulary.js";
import { SLOT_LABELS } from "./judgment.js";
import { displayTime, storyClock, storyPlanTime } from "./story-time.js";

const PACKAGE_EVENT = "package.brought_in";
const TRIGGERS = { guest_arrived: "손님이 오면", event_end: "행사가 끝나면", [PACKAGE_EVENT]: "택배를 들여오면" };
function lineTime(when, clock) {
  if (!when?.time) return { story: TRIGGERS[when?.event] ?? "", derivation: null };
  const at = storyPlanTime(when.time, clock);
  const story = displayTime(at);
  if (!clock) return { story, derivation: null };
  const minutes = Math.round((clock.storyStart - at) / 60000);
  const relative = minutes === 0 ? "같은 시각" : `${Math.abs(minutes)}분 ${minutes > 0 ? "전" : "후"}`;
  return { story, derivation: `${displayTime(clock.storyStart)} 일정 → ${relative} → ${story}` };
}

function chainDevices(tasks, details, snapshot, houseDevices) {
  const observed = new Map((snapshot?.devices ?? []).map((device) => [device.logical_id, device]));
  const traces = new Map();
  for (const task of tasks) {
    for (const id of task.devices) {
      if (!traces.has(id)) traces.set(id, []);
      traces.get(id).push(task.id);
    }
  }
  const ids = new Set([...Object.keys(houseDevices), ...observed.keys(), ...traces.keys()]);
  return Array.from(ids, (logicalId) => {
    const model = houseDevices[logicalId];
    const live = observed.get(logicalId);
    const planned = details.get(logicalId);
    const type = live?.device_type ?? planned?.type;
    return {
      logicalId,
      label: model?.label ?? live?.label ?? (Object.hasOwn(DEVICE_NAMES, type) ? DEVICE_NAMES[type] : "기기"),
      room: live?.room ?? planned?.room ?? model?.room ?? null,
      type,
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

export function buildChain({
  episode, rationale, card, hubPlan, hubLedger = [], snapshot, storyTime, houseDevices = {},
  allowReceiptWithoutShareTime = false,
} = {}) {
  const cards = Array.isArray(card) ? card : card ? [card] : [];
  const episodeId = episode?.episode_id ?? rationale?.episode_id ?? cards[0]?.episode_id;
  const sharedAt = Date.parse(episode?.shared_at);
  const receipt = hubLedger.find((row) => row.kind === "plan" && row.plan_id === episodeId &&
    (Number.isFinite(sharedAt) ? Date.parse(row.at) >= sharedAt : allowReceiptWithoutShareTime && row.at));
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
    const windows = receipt && storyTime?.guestWindows;
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
    const values = receipt ? actions[id] ?? [] : [];
    const devices = task.devices.map(({ id }) => id);
    const cardLine = lines.get(id);
    const time = { ...(cardLine?.time ?? lineTime()), at: cardLine?.when?.time };
    return { id, line, need, way, devices, time, values, intentId: intentsByCard.get(card_id)?.id ?? null };
  });

  const none = !intents.length && rationale?.none_reason ? { reason: rationale.none_reason } : undefined;
  const itemTasks = rationale?.item_tasks?.length ? rationale.item_tasks : episode?.item_tasks ?? [];
  const judged = ["judged", "notified", "held", "closed"].includes(episode?.status);
  const intentReady = intents.length > 0 || Boolean(none);
  const tasksReady = tasks.length > 0 || itemTasks.length > 0 || (judged && intentReady);
  const hubReady = Boolean(receipt?.at);
  // Item-only orders have no card. Let the receipt confirm their plan was published.
  const cardless = judged && intentReady && episode?.card_ids?.length === 0 &&
    intents.every(({ cardId }) => cardId === null);
  const cardReady = cards.length > 0 || (cardless && (hubReady || (!tasks.length && !itemTasks.length)));

  return {
    episodeId, items, slots, intents, intent: intents[0] ?? null,
    ...(none ? { none } : {}),
    evidence, unbundled,
    needs: Array.from(needs, ([text, taskIds]) => ({ text, taskIds })),
    tasks,
    item_tasks: itemTasks,
    devices: chainDevices(tasks, deviceDetails, snapshot, houseDevices),
    cards: chainCards,
    hasEpisode: Boolean(episode?.items), hasRationale: Boolean(rationale), hasHubPlan: hubReady,
    cardReady,
    ready: {
      extract: items.length > 0 || Boolean(episode?.items && (sources || judged)),
      context: Boolean(sources),
      intent: intentReady,
      tasks: tasksReady,
      plan: cardReady,
      hub: hubReady,
    },
    orderClock: displayTime(episode?.shared_at),
    cardClock: displayTime(cards[0]?.updated_at || episode?.shared_at, firstClock?.offset),
    receipt, receiptStory: receipt ? `${displayTime(receipt.at, firstClock?.offset)} · 계획 받음` : "",
  };
}

export function houseDevicePresentation(chain, focusDevices = [], moment = "") {
  const focus = new Set(focusDevices);
  return new Map(chain.devices.map((device) => {
    const focused = focus.has(device.logicalId);
    const resting = chain.hasHubPlan && !device.chosen;
    return [device.logicalId, { focused, resting, moment: focused && device.state ? moment : "" }];
  }));
}
