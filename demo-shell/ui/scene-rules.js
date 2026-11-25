import { fridgeValues } from "./artwork/fridge.js";
import { tvValues } from "./artwork/tv.js";
import { displayTime } from "./story-time.js";

const DELIVERED = "package.brought_in";
const EVENTS = {
  [DELIVERED]: { kind: "delivery", room: "entrance", signal: "package" },
  guest_arrived: { kind: "guests", room: "entrance", signal: "door" },
  event_end: { kind: "end", room: "living_room" },
};
const WORLD_EVENTS = { package: DELIVERED, presence: "guest_arrived", empty: "event_end" };
const MOTION_TYPES = { cleaner_sweep: "cleaner", light_spread: "light" };
// The house paints these surfaces from their own device markers.
const DISPLAYS = [
  { surface: "tv", device: "display_01", command: "play_mood" },
  { surface: "fridge_panel", device: "fridge_01", command: "show_notice" },
];
const time = (at) => Date.parse(at);
const atOrLast = (at) => Number.isFinite(time(at)) ? time(at) : Infinity;
const firstObservedAt = (observed) => observed.reduce((first, { at }) =>
  time(at) < atOrLast(first) ? at : first, "");

export function worldFacts(markers) {
  const facts = [];
  for (const node of markers.querySelectorAll("[data-signal]")) {
    const event = WORLD_EVENTS[node.dataset.signal];
    const at = node.querySelector("time")?.getAttribute("datetime");
    if (event && at) facts.push({ event, at });
  }
  for (const { dataset } of markers.querySelectorAll("[data-device][data-person-at]")) {
    facts.push({ event: "person", at: dataset.personAt, device: dataset.device });
  }
  return facts;
}

export function buildMoments({ chain, actions = {}, relations = {}, facts = [], tags = [], wording, since }) {
  if (!chain.receipt) return [];
  const inventory = new Map(chain.devices.map((device) => [device.logicalId, device]));
  const tasks = new Map(chain.tasks.map((task) => [task.id, task]));
  const cardLines = new Map(chain.cards.flatMap((card) => card.lines.map((line) => [line.task_id, line])));
  const lines = new Map();
  for (const id of new Set([...cardLines.keys(), ...Object.keys(relations), ...Object.keys(actions)])) {
    const card = cardLines.get(id);
    const task = tasks.get(id);
    const relation = relations[id];
    const when = card?.when ?? relation?.trigger;
    if (!when?.time && !when?.event) continue;
    const tag = tags.find((row) => row.kind === "line" && row.ref === id &&
      row.text === (task?.line ?? card?.text))?.tag;
    const devices = task?.devices?.length ? task.devices : (actions[id] ?? []).map((action) => action.device);
    const subset = tag?.devices;
    const focus = Array.isArray(subset) && subset.length && subset.every((device) => devices.includes(device))
      ? subset : devices;
    const observed = (relation?.observed ?? []).filter(({ device, at }) =>
      devices.includes(device) && time(at) >= time(since ?? chain.receipt.at));
    lines.set(id, { id, when, devices, focus, tag, observed, match: relation?.match, state: card?.state });
  }

  const plan = { id: "plan", kind: "plan", at: chain.receipt.at, ready: true, room: "overview", focusDevices: [],
    story: displayTime(chain.receipt.at), ...wording.plan };
  const moments = [];
  const events = new Map();
  function addMoment({ id, kind, at, ready, room, signal, attached = [], focus = [], state, event,
    observedAt = at, arrival = Infinity, follows }) {
    const focusDevices = [...new Set([...focus, ...attached.flatMap((line) => line.focus)])];
    const rooms = new Set(focusDevices.map((device) => inventory.get(device)?.room).filter(Boolean));
    const deviceNames = focusDevices.map((device) => inventory.get(device)?.label).filter(Boolean);
    moments.push({
      id, kind, event, follows, at, ready, room: room ?? (rooms.size === 1 ? [...rooms][0] : "overview"), signal,
      lines: attached, focusDevices, story: displayTime(at), state, observedAt, arrival,
      ...wording[kind],
      ...(kind === "line" && deviceNames.length ? { title: deviceNames.join(" · ") } : {}),
    });
  }

  const timed = [...lines.values()].filter(({ when }) => when.time);
  for (const line of timed) {
    const observed = line.observed.filter(({ at }) => time(at) >= time(line.when.time));
    addMoment({ id: `line:${line.id}`, kind: "line", at: line.when.time, ready: observed.length > 0,
      attached: [{ ...line, observed }], state: line.state,
      observedAt: firstObservedAt(observed) });
  }

  for (const [arrival, fact] of facts.entries()) {
    if (time(fact.at) < time(since ?? chain.receipt.at) || !Number.isFinite(time(fact.at))) continue;
    if (fact.event === "person") {
      addMoment({ id: `person:${fact.device}:${fact.at}`, kind: "person", at: fact.at, ready: true, event: "person",
        focus: [fact.device], arrival });
    } else {
      if (!events.has(fact.event)) events.set(fact.event, []);
      events.get(fact.event).push({ ...fact, arrival });
    }
  }

  const triggers = [...lines.values()].filter(({ when }) => !when.time);
  for (const event of new Set([...Object.keys(EVENTS), ...events.keys(), ...triggers.map((line) => line.when.event)])) {
    const appearance = Object.hasOwn(EVENTS, event) ? EVENTS[event] : { kind: "line", room: "entrance" };
    const occurrences = events.get(event) ?? [];
    const waiting = triggers.filter((line) => line.when.event === event);
    const pending = new Set(waiting);
    for (const { at, arrival } of occurrences) {
      const attached = waiting.filter((line) => time(line.match?.at) === time(at) &&
        (!line.match.event_type || line.match.event_type === event));
      for (const line of attached) pending.delete(line);
      const id = `event:${event}:${time(at)}`;
      const guests = event === "guest_arrived";
      addMoment({ id, event, at, ready: true, ...appearance, attached: guests ? [] : attached, arrival });
      if (!guests) continue;
      for (const line of attached) {
        const observed = line.observed.filter((reading) => time(reading.at) >= time(at));
        const observedAt = firstObservedAt(observed);
        addMoment({ id: `line:${line.id}`, kind: "line", at: observedAt || at, ready: observed.length > 0,
          attached: [{ ...line, observed }], focus: line.devices, follows: id, state: line.state, observedAt });
      }
    }
    if (!occurrences.length || pending.size) {
      addMoment({ id: `waiting:${event}`, ready: false, ...appearance, attached: [...pending] });
    }
  }

  // Equal supplied timestamps keep the observed arrival order. Unknown event times stay waiting.
  moments.sort((a, b) => (atOrLast(a.at) - atOrLast(b.at)) ||
    (atOrLast(a.observedAt) - atOrLast(b.observedAt)) || (a.arrival - b.arrival));
  return [plan, ...moments];
}

function deliveredProps(items, itemTypes, vocabulary, palette) {
  const props = new Map();
  for (const { id, qty } of items) {
    if (!Object.hasOwn(itemTypes, id)) continue;
    for (const { slot, anchor, placement, countPerUnit = 1 } of itemTypes[id].props ?? []) {
      const definition = vocabulary.find(({ id, kind }) => id === slot && kind === "goods");
      if (!definition?.anchors.includes(anchor)) continue;
      const placements = definition.parameters.placement?.enum;
      if (placement && !placements?.includes(placement)) continue;
      const key = JSON.stringify([slot, anchor, placement]);
      const found = props.get(key) ?? { slot, anchor, placement, parameters: definition.parameters, quantity: 0 };
      if (Number.isInteger(qty) && qty > 0) found.quantity += qty * countPerUnit;
      props.set(key, found);
    }
  }
  return [...props.values()].map(({ slot, anchor, placement, parameters, quantity }) => {
    const params = {};
    if (parameters.count?.type === "integer" && quantity > 0) {
      params.count = Math.min(parameters.count.maximum, Math.max(parameters.count.minimum, quantity));
    }
    if (placement) params.placement = placement;
    if (parameters.palette?.enum.includes(palette)) params.palette = palette;
    return { slot, anchor, params };
  });
}

function readingMatches(reading, observed, properties) {
  return reading?.observation === "current" && properties.every((property) =>
    Object.hasOwn(observed.values, property) && Object.hasOwn(reading.values, property) &&
    reading.revisions?.[property] === observed.revisions?.[property] &&
    JSON.stringify(reading.values[property]) === JSON.stringify(observed.values[property]));
}

function displayArtwork(lines, readings, displayReadings, itemTasks, itemTypes) {
  const artwork = {};
  for (const { surface, device, command } of DISPLAYS) {
    const reading = readings.get(device);
    const displayValue = values => surface === "tv" ? values?.[command]?.scene : values?.[command];
    const content = displayValue(reading?.values);
    if (typeof content !== "string" || !content ||
      (displayReadings !== undefined && displayValue(displayReadings?.get(device)) !== content)) continue;
    let latest;
    for (const line of lines) {
      for (const observed of line.observed) {
        if (observed.device === device && observed.cmd === command && readingMatches(reading, observed, [command]) &&
          (!latest || time(observed.at) >= latest.at)) {
          latest = { line, at: time(observed.at) };
        }
      }
    }
    if (!latest) continue;
    const { line } = latest;
    if (surface === "tv") {
      const values = tvValues(content, line.tag);
      if (values) artwork.tv = values;
    } else {
      const relation = itemTasks.find(({ task_id, text }) => task_id === line.id && text === content);
      const icon = relation && Object.hasOwn(itemTypes, relation.item) ? itemTypes[relation.item].icon : undefined;
      artwork.fridge_panel = fridgeValues(icon);
    }
  }
  return Object.keys(artwork).length ? artwork : undefined;
}

export function momentScene(moment, {
  moments, items, itemTasks, itemTypes, vocabulary, snapshot, displayReadings, devices,
  showArtwork = true, canPlay = () => true,
}) {
  if (!moment?.ready || moment.kind === "plan") return null;
  const readings = new Map((snapshot?.devices ?? []).map((device) => [device.logical_id, device]));
  const through = moments.filter(({ ready, at }) => ready && time(at) <= time(moment.at));
  const arrivedLines = through.flatMap(({ lines }) => lines ?? []);
  const balloonPalettes = vocabulary.find(({ id }) => id === "balloon")?.parameters.palette.enum ?? [];
  const palette = arrivedLines.findLast((line) => line.observed.length && balloonPalettes.includes(line.tag?.palette))?.tag.palette;
  const delivered = through.some(({ kind }) => kind === "delivery");
  const slots = delivered ? deliveredProps(items, itemTypes, vocabulary, palette) : [];

  const motions = [];
  for (const line of moment.lines) {
    const preset = line.tag?.motion;
    if (!canPlay(line.id) || !Object.hasOwn(MOTION_TYPES, preset)) continue;
    const slot = vocabulary.find(({ id, kind }) => id === preset && kind === "motion");
    const device = devices.find(({ logicalId, type }) => type === MOTION_TYPES[preset] && line.focus.includes(logicalId));
    const reading = device && readings.get(device.logicalId);
    const anchor = slot?.anchors.find((id) => id === device?.logicalId || id === device?.room);
    const properties = preset === "cleaner_sweep" ? ["job_status"] : ["color"];
    if (anchor && line.observed.some((observed) => observed.device === device.logicalId &&
      readingMatches(reading, observed, properties) &&
      (preset !== "cleaner_sweep" || reading.values.job_status === "running"))) {
      motions.push(line.id);
      slots.push({ slot: preset, anchor, params: {} });
    }
  }

  const artwork = showArtwork ? displayArtwork(arrivedLines, readings, displayReadings, itemTasks, itemTypes) : undefined;
  return { scene: { moment: moment.id, slots }, artwork, motions };
}

export function sendScene(house, validateScene, scene, onApplied) {
  const validation = validateScene(scene);
  if (!validation.ok) {
    console.warn("House scene rejected", scene.moment, validation.reasons);
    return false;
  }
  const result = house.setScene(scene);
  if (!result.ok) {
    console.warn("House scene rejected", scene.moment, result.reasons);
    return false;
  }
  onApplied?.(scene);
  return true;
}

// Close views use the built-in model's geometry, selected by inventory type.
const CLOSE_VIEWS = {
  cleaner: { aim: [.57, .32, .05], offset: [-7, 9, 13], zoom: 2.2 },
  cooktop: { aim: [3.60, 1.14, -3.02], offset: [-.5, 6.5, 10], zoom: 3.8 },
  display: { aim: [-.95, 1.95, -2.70], offset: [1.6, .75, 12], zoom: 3.6 },
  oven: { aim: [3.73, .85, -2.488], offset: [-3, 3.2, 11], zoom: 6 },
  fridge: { aim: [5.36, 1.26, -2.65], offset: [2, 2.8, 12], zoom: 4.2 },
  light: { aim: [-1.42, 2.2, -.4], offset: [8.6, 9.84, 17.4], zoom: 2.8 },
};
const DELIVERY_FRIDGE_VIEW = { aim: [5.42, 1.24, -2.65], offset: [2.8, 6.4, 12], zoom: 4.35 };
const MOOD_VIEW = { aim: [-1.08, 2.22, -1.66], offset: [2.8, 4.5, 12], zoom: 3.7 };

export function closeView(moment, devices) {
  const witnessed = new Set(moment.lines?.flatMap(({ observed }) => observed.map(({ device }) => device)));
  const focus = moment.focusDevices.map((id) => devices.find((device) => device.logicalId === id)).filter(Boolean);
  const model = focus.find(({ logicalId, type }) =>
    (moment.kind === "person" || witnessed.has(logicalId)) && Object.hasOwn(CLOSE_VIEWS, type));
  if (!model) return null;
  let view = CLOSE_VIEWS[model.type];
  if (moment.kind === "line" && focus.some(({ type }) => type === "display") && focus.some(({ type }) => type === "light")) {
    view = MOOD_VIEW;
  } else if (moment.kind === "delivery" && model.type === "fridge") {
    view = DELIVERY_FRIDGE_VIEW;
  }
  const { aim, offset, zoom } = view;
  return { aim, eye: aim.map((position, index) => position + offset[index]), zoom };
}
