const DAY = 86400000;
const MINUTE = 60000;
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
const seoulDate = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
});
const weekday = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", weekday: "short" });
const clock = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

export function storyTimeOffset(event, rebasedStart) {
  const start = Date.parse(rebasedStart);
  const day = WEEKDAYS.indexOf(event?.day);
  if (!Number.isFinite(start) || day < 0) return null;
  // The rationale gives a weekday and time. Use the nearest such weekday to
  // anchor the display; the absolute date is immaterial to weekday labels.
  const delta = day - WEEKDAYS.indexOf(weekday.format(start));
  const days = delta - Math.round(delta / 7) * 7;
  const parts = Object.fromEntries(seoulDate.formatToParts(start).map(({ type, value }) => [type, value]));
  const storyStart = Date.parse(`${parts.year}-${parts.month}-${parts.day}T${event.start}:00+09:00`) + days * DAY;
  return Number.isFinite(storyStart) ? start - storyStart : null;
}

export function displayTime(stamp, offset = null, withDay = true) {
  const at = (typeof stamp === "number" ? stamp : Date.parse(stamp)) - (offset ?? 0);
  if (!Number.isFinite(at)) return "";
  const time = clock.format(at);
  return withDay ? `${weekday.format(at)} ${time}` : time;
}

export function storyClock(event, startsAt, endsAt, timing) {
  const offset = storyTimeOffset(event, startsAt);
  if (offset === null) return null;
  const liveStart = Date.parse(startsAt);
  const storyStart = liveStart - offset;
  const date = new Date(storyStart + 9 * 60 * MINUTE).toISOString().slice(0, 10);
  const end = Date.parse(`${date}T${event.end}:00+09:00`);
  return {
    offset, timing, liveStart, storyStart, liveEnd: Date.parse(endsAt),
    storyEnd: end + (end < storyStart ? DAY : 0),
  };
}

function leadPairs(timing, anchor) {
  if (anchor === "end") return [timing.end_fallback_min];
  return [timing.guest_window_before_min, timing.before_start_default_min];
}

export function storyPlanTime(stamp, story, anchor) {
  const at = Date.parse(stamp);
  if (!story?.timing) return at - (story?.offset ?? 0);
  const fromEnd = anchor === "end" || (!anchor && (at === story.liveEnd ||
    at === story.liveEnd + story.timing.end_fallback_min.demo * MINUTE));
  const live = fromEnd ? story.liveEnd : story.liveStart;
  const target = fromEnd ? story.storyEnd : story.storyStart;
  const minutes = (at - live) / MINUTE;
  const sign = fromEnd ? 1 : -1;
  const pair = leadPairs(story.timing, fromEnd ? "end" : "start").find(({ demo }) => minutes === sign * demo);
  return target + (pair ? sign * pair.normal : minutes) * MINUTE;
}

export function storyObservedTime(stamp, story, label = "", withDay = true) {
  if (!story?.timing) return displayTime(stamp, story?.offset, withDay);
  const at = Date.parse(stamp);
  if (!Number.isFinite(at)) return "";
  const shifted = at - story.offset;
  const landmarks = leadPairs(story.timing, "start").map(({ demo, normal }) => [
    story.liveStart - demo * MINUTE, story.storyStart - normal * MINUTE,
  ]);
  if (Number.isFinite(story.liveEnd) && Number.isFinite(story.storyEnd)) {
    const { demo, normal } = story.timing.end_fallback_min;
    landmarks.push([story.liveEnd, story.storyEnd], [story.liveEnd + demo * MINUTE, story.storyEnd + normal * MINUTE]);
  }
  // Keep the real offset when it puts this observation on the same side of the
  // schedule landmarks in both clocks. A live occurrence need not hit a landmark.
  if (landmarks.every(([live, target]) => Math.sign(at - live) === Math.sign(shifted - target))) {
    return displayTime(shifted, null, withDay);
  }
  const minutes = Math.round(Math.abs(at - story.liveStart) / MINUTE);
  return label || (minutes ? `일정 ${minutes}분 ${at < story.liveStart ? "전" : "후"}` : "일정 시작 무렵");
}

export function storyLedgerTime(row, story, label = "") {
  const timing = row.timing;
  if (story?.timing && timing?.scheduled_at) {
    const scheduled = storyPlanTime(timing.scheduled_at, story, timing.anchor);
    if (!Number.isFinite(scheduled)) return label || "예약한 종료 시각";
    // A late dispatch still belongs to its planned story slot. Keep elapsed
    // time after dispatch, for example the time a cleaning job took to finish.
    return displayTime(scheduled + Date.parse(row.at) - Date.parse(timing.observed_at));
  }
  return storyObservedTime(row.at, story, label, Boolean(story));
}
