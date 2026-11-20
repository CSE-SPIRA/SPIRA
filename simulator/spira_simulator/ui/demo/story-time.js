const DAY = 86400000;
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
  const at = Date.parse(stamp) - (offset ?? 0);
  if (!Number.isFinite(at)) return "";
  const time = clock.format(at);
  return withDay ? `${weekday.format(at)} ${time}` : time;
}
