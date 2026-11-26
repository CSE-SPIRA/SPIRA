import { displayTime } from "./story-time.js";

const HOME_CUES = {
  "package.brought_in": { name: "delivery", label: "택배 들이기" },
  guest_arrived: { name: "guests_arrive", label: "손님 맞이" },
  event_end: { name: "event_end", label: "일정 끝내기" },
};

const clockLabel = (at) => displayTime(at).split(" ").at(-1);
const NO_EFFECT = new Set(["off", "failed", "blocked", "held"]);
export const canObserveLine = ({ state }) => !NO_EFFECT.has(state);

function scheduleEnd({ cards, intents, evidence }, guestWindows) {
  const ends = cards.flatMap(({ card_id, starts_at, lines }) => {
    const end = lines.map(({ task_id }) => Date.parse(guestWindows[task_id]?.to)).find(Number.isFinite);
    if (end !== undefined) return [end];
    const link = intents.find(({ cardId }) => cardId === card_id);
    const event = evidence.calendar.find(({ id }) => id === link?.calendarEvent);
    if (!event?.start || !event.end || !starts_at) return [];
    const day = "2000-01-01T";
    const duration = Date.parse(day + event.end + "Z") - Date.parse(day + event.start + "Z");
    return [Date.parse(starts_at) + (duration < 0 ? duration + 86400000 : duration)];
  });
  return ends.filter(Number.isFinite).sort((a, b) => b - a)[0];
}

export function buildPresenterCues({ path, chain, timeline = [], published = [], guestWindows = {}, clock }) {
  const cues = [{ id: "share", label: "공유" }, { id: "card", label: "준비 카드" }];
  if (path !== "house") return cues;
  cues.push({ id: "house", label: "우리 집" });
  const moments = [];
  const eventTime = (type) => published.map(({ at, event }) => event === type ? Date.parse(at) : NaN)
    .find(Number.isFinite);
  const addEvent = (event, { at, target, until, label = HOME_CUES[event].label } = {}) => {
    moments.push({ id: event, kind: "event", event, ...HOME_CUES[event], label, at, target, until });
  };
  addEvent("package.brought_in", { at: eventTime("package.brought_in") ?? -Infinity });

  if (clock) {
    const timed = new Map();
    for (const { id, at, lines, ready } of timeline) {
      if (!lines?.some((line) => line.when.time && (ready || canObserveLine(line)))) continue;
      const time = Date.parse(at);
      if (!Number.isFinite(time)) continue;
      if (!timed.has(time)) timed.set(time, { id: `time:${time}`, kind: "time", at: time,
        target: time, label: clockLabel(time), momentIds: [] });
      timed.get(time).momentIds.push(id);
    }
    moments.push(...timed.values());
  }

  const windows = Object.values(guestWindows).map(({ from, to }) => ({ from: Date.parse(from), to: Date.parse(to) }))
    .filter(({ from, to }) => Number.isFinite(from) && Number.isFinite(to)).sort((a, b) => a.from - b.from);
  const guestAt = clock ? eventTime("guest_arrived") : undefined;
  const guestWindow = windows.find(({ from, to }) => from <= guestAt && guestAt < to) ?? windows[0];
  const guestStart = chain.cards.filter(({ lines }) => lines.some(({ when }) => when?.event === "guest_arrived"))
    .map(({ starts_at }) => Date.parse(starts_at)).filter(Number.isFinite).sort((a, b) => a - b)[0];
  const guestTarget = guestWindow ? (guestAt >= guestWindow.from && guestAt < guestWindow.to ? guestAt : guestWindow.from)
    : guestAt ?? guestStart;
  const hasGuests = timeline.some(({ event, ready, lines }) => event === "guest_arrived" &&
    (ready || lines.some(canObserveLine)));
  if (guestWindow || hasGuests || guestAt !== undefined) {
    addEvent("guest_arrived", { at: guestTarget ?? Infinity, target: guestTarget, until: guestWindow?.to });
  }

  const end = scheduleEnd(chain, guestWindows);
  const publishedEnd = clock ? eventTime("event_end") : undefined;
  const endTarget = publishedEnd >= (end ?? -Infinity) ? publishedEnd : end;
  if (endTarget !== undefined || timeline.some(({ kind, ready }) => kind === "end" && ready)) {
    addEvent("event_end", { at: endTarget ?? Infinity, target: endTarget,
      label: clock && endTarget !== undefined ? `${clockLabel(endTarget)} 일정 끝내기` : "일정 끝내기" });
  }
  cues.push(...moments.sort((a, b) => a.at - b.at));
  if (cues.some(({ id }) => id === "event_end")) cues.push({ id: "record", label: "7 기록" });
  return cues;
}
