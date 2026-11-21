import { HOUSE_DEVICES } from "../house/devices.js";
import { DEVICE_NAMES } from "../house/vocabulary.js";
import { displayTime, planReceiptTime, storyClock, storyLedgerTime, storyObservedTime, storyPlanTime } from "./story-time.js";

const PACKAGE_EVENT = "package.brought_in";
const PACKAGE_STORY = "파티 전";
const SLOT_LABELS = { event: "행사", guests: "손님", activity: "활동", theme: "테마" };
const TRIGGERS = { guest_arrived: "손님이 오면", event_end: "행사가 끝나면", [PACKAGE_EVENT]: "택배를 들여오면" };
const OCCURRENCES = { guest_arrived: "손님 도착", event_end: "행사 종료", [PACKAGE_EVENT]: "택배 들여옴" };

function lineTime(when, clock) {
  if (!when?.time) return { story: TRIGGERS[when?.event] ?? "", derivation: null };
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
      label: model?.label ?? live?.label ?? (Object.hasOwn(DEVICE_NAMES, type) ? DEVICE_NAMES[type] : "기기"),
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

function ledgerReports(ledger, episodeId, cards, clocks, firstClock, timing, receiptTime) {
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
      const event = row.event_type ?? row.timing?.event;
      const story = event === PACKAGE_EVENT ? PACKAGE_STORY
        : row.kind === "plan" ? (planId === episodeId ? receiptTime.ledger : "주문 직후")
        : storyLedgerTime(row, clock, OCCURRENCES[event]);
      return {
        ...row, planId, taskId, deviceId,
        deviceIds: deviceId ? [deviceId] : (row.items ?? []).map(({ device }) => device),
        story,
      };
    });
}

function houseTimeline(sharedAt, ledger, cards, clocks, firstClock, tasks, plan) {
  const cleaning = tasks.find((task) => task.devices.includes("cleaner_01"));
  const safety = tasks.find((task) => task.devices.includes("cooktop_01"));
  const party = cards.find((card) => card.starts_at);
  const since = Number.isFinite(sharedAt) ? sharedAt : Date.parse(plan.at);
  const events = Object.fromEntries(Object.entries(OCCURRENCES).map(([event, label]) => {
    const at = ledger.findLast((row) => row.event_type === event &&
      (!Number.isFinite(since) || Date.parse(row.at) >= since))?.at;
    const story = event === PACKAGE_EVENT ? `${PACKAGE_STORY} · ${label}` : storyObservedTime(at, firstClock, label);
    return [event, { at, story }];
  }));
  return {
    plan,
    clean: { at: cleaning?.time.at, story: cleaning?.time.at ? cleaning.time.story : "" },
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

  const receipt = hubLedger.find((row) => row.kind === "plan" && row.plan_id === episodeId);
  const sharedAt = Date.parse(episode?.shared_at);
  const fixtureShares = storyTime?.fixtureShares;
  // Live fixture replays append a sequence number to the recorded episode ID.
  const fixtureId = Object.keys(fixtureShares ?? {}).find((id) => episodeId === id ||
    (episodeId?.startsWith(id) && /^\d+$/.test(episodeId.slice(id.length))));
  const storyShare = sharedAt <= Date.parse(receipt?.at)
    ? (fixtureShares ? fixtureShares[fixtureId] : episode.shared_at) : null;
  const firstLead = fixtureId ? Infinity : Math.min(firstClock?.storyStart ?? Infinity,
    ...cards.flatMap((entry) => entry.lines.map(({ when }) =>
      storyPlanTime(when?.time, clocks.get(entry.card_id)))).filter(Number.isFinite));
  const receiptTime = planReceiptTime(storyShare, storyTime?.timing?.quiet_s?.normal, firstLead);
  const plan = { at: receipt?.at, story: receipt ? receiptTime.story : "" };

  return {
    episodeId, items, slots, intents, intent: intents[0] ?? null,
    ...(rationale && !intents.length ? { none: { reason: rationale.none_reason } } : {}),
    evidence, unbundled,
    needs: Array.from(needs, ([text, taskIds]) => ({ text, taskIds })),
    tasks,
    item_tasks: rationale?.item_tasks ?? episode?.item_tasks ?? [],
    devices: chainDevices(tasks, deviceDetails, snapshot),
    reports: ledgerReports(hubLedger, episodeId, cards, clocks, firstClock, storyTime?.timing, receiptTime),
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
    orderClock: displayTime(episode?.shared_at),
    cardClock: displayTime(cards[0]?.updated_at || episode?.shared_at, firstClock?.offset),
    timeline: houseTimeline(sharedAt, hubLedger, cards, clocks, firstClock, tasks, plan),
  };
}

function traceLabel(chain, device) {
  const [taskId, otherTaskId] = device.traces;
  if (!taskId || otherTaskId) return "";
  const task = chain.tasks.find(({ id }) => id === taskId);
  if (!task?.line) return "";
  const intent = chain.intents.find(({ id }) => id === task.intentId);
  const words = (text) => text.normalize("NFC").toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  const taskText = [task.line, task.need].map(words);
  const matchesTerm = (word, term) => word === term ||
    (word?.startsWith(term) && /\p{Script=Hangul}$/u.test(term) &&
      /^(?:은|는|이|가|을|를|과|와|에|에서|으로|로|의|도|만|까지|부터|에게)$/.test(word.slice(term.length)));
  const mentions = (phrase) => {
    const terms = words(phrase);
    return terms.length > 0 && taskText.some((text) => text.some((_, index) =>
      terms.every((term, offset) => matchesTerm(text[index + offset], term))));
  };
  const slots = (intent?.slotIds ?? []).flatMap((id) => {
    const slot = chain.slots.find((entry) => entry.id === id);
    if (!slot?.value) return [];
    const items = slot.basis.map((id) => chain.items.find((item) => item.id === id)).filter(Boolean);
    const namedItem = items.find((item) => mentions(item.id) || mentions(item.name));
    const valueWords = words(slot.value);
    const namesFullValue = mentions(slot.value);
    if (!namedItem && !namesFullValue && !valueWords.some((word) => word.length > 1 && mentions(word))) return [];
    // A field name only strengthens a value match, as in "공주 테마".
    const namesField = !valueWords.includes(slot.label) && mentions(slot.label);
    const strength = namedItem ? 4 : namesFullValue ? 3 : namesField ? 2 : 1;
    return [{ slot, item: (namedItem ?? items[0])?.id, strength }];
  });
  const [link, next] = slots.sort((a, b) => b.strength - a.strength);
  if (!link || link.strength === next?.strength) return task.line;
  return [task.line, `${link.slot.label}: ${link.slot.value}`, link.item].filter(Boolean).join(" ← ");
}

export function houseDevicePresentation(chain, focusDevices = []) {
  const focus = new Set(focusDevices);
  return new Map(chain.devices.map((device) => {
    const focused = focus.has(device.logicalId);
    const resting = chain.hasHubPlan && !device.chosen;
    let evidence = "";
    if (chain.hasHubPlan && focused) {
      if (device.logicalId === "fridge_01" && device.state?.show_notice) {
        const notices = chain.item_tasks.filter(({ text }) => text === device.state.show_notice);
        if (notices.length === 1) evidence = `← ${notices[0].item}`;
      } else if (device.chosen) {
        evidence = traceLabel(chain, device);
      }
    }
    return [device.logicalId, { focused, resting, evidence }];
  }));
}
