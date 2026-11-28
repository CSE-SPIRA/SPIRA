import { startedLabel } from "./replays.js";
// Presenter log of one judgment (right panel, Server mode): built only from the demo trace
// (GET /v1/demo/episodes/{id}/trace, contracts/openapi/demo.yaml). Finished stages fold into one summary line,
// the stage being presented is expanded, and the next stage shows its real Server state underneath.
import { SLOT_LABELS } from "./judgment.js";
import { esc, rows } from "./markup.js";

export const TRACE_OF = { extract: "s1", context: "s2", intent: "s3", tasks: "s4", plan: "s5" };
const TITLES = { s1: "S1 주문 추출", s2: "S2 맥락 검색", s3: "S3 의도 추론", s4: "S4 할 일 생성", s5: "S5 계획 확정" };
const RUNNING = { s1: "주문 화면 읽는 중", s2: "맥락·KB 검색 중", s3: "의도 추론 중", s4: "할 일 생성 중", s5: "계획 확정 중" };
const ORDER = ["s1", "s2", "s3", "s4", "s5"];
// Why S4/S5 left a task out (server/spec.md 10.1, 11.2): the stored code, then plain words.
const DROP_WHY = {
  late: "시각이 이미 지남", quiet_hours: "조용한 시간", not_delegated: "이 집이 맡기지 않은 기기·명령",
  unsafe_cmd: "허용되지 않은 명령", value_out_of_range: "값이 기기 범위 밖", room_mismatch: "다른 방 기기",
  paused: "일시정지 중", card_limit: "카드 수 한도", overlap: "이미 있는 할 일과 겹침",
  notices_per_screen: "안내 수 한도", repeated_notice: "같은 안내 반복", max_lines: "줄 수 한도",
  switched_off: "사용자가 꺼 둔 줄", unclassified_run: "의도 없는 실행", format: "형식 오류", schema: "형식 오류",
  public_text: "문구 검사",
};
const why = (reason) => DROP_WHY[reason] ? `${reason} · ${DROP_WHY[reason]}` : reason;

const clock = (seconds) => {
  if (seconds == null) return "--:--.-";
  const s = Math.max(0, seconds);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`;
};
const secs = (ms) => `${(ms / 1000).toFixed(1)}s`;
const num = (n) => Number(n).toLocaleString("en-US");
const pct = (x) => `${Math.round((x ?? 0) * 100)}%`;

// S1 attributes are {key, value, source} (contracts); older reads may hold plain text.
function attributeText(attribute) {
  if (attribute && typeof attribute === "object") return [attribute.key, attribute.value].filter(Boolean).join(" ");
  return String(attribute ?? "");
}

export function traceStage(trace, name) {
  return trace?.stages?.find((stage) => stage.name === name);
}

export function stageFinished(trace, name) {
  return ["done", "failed", "skipped"].includes(traceStage(trace, name)?.state);
}

function intentNames(trace) {
  const counts = traceStage(trace, "s2")?.result?.kb?.intent_counts ?? [];
  return Object.fromEntries(counts.map(({ intent_id, name }) => [intent_id, name]));
}

function took(trace, name) {
  const index = ORDER.indexOf(name);
  const stage = traceStage(trace, name);
  const before = ORDER.slice(0, index).map((n) => traceStage(trace, n)?.done_s).filter((v) => v != null).at(-1) ?? 0;
  return stage?.done_s == null ? null : stage.done_s - before;
}

function llmText(stage) {
  return stage?.llm ? `LLM ${stage.llm.calls}회 ${secs(stage.llm.ms)} · ${num(stage.llm.input_tokens + stage.llm.output_tokens)} tok`
    : "LLM 없음";
}

// One-line summaries of finished stages.
function summary(trace, name) {
  const stage = traceStage(trace, name);
  const r = stage?.result ?? {};
  if (stage?.state === "skipped") return "건너뜀 (앞 단계에서 멈춤)";
  if (stage?.state === "failed") return `실패 · ${r.error ?? "오류"}`;
  if (name === "s1") {
    const shown = (r.items ?? []).filter(({ masked }) => !masked).length;
    const masked = (r.items ?? []).length - shown;
    return `물건 ${shown}종 · 가린 물건 ${masked} · ${llmText(stage)}`;
  }
  if (name === "s2") {
    const unusual = r.unusual_items?.status === "list" ? r.unusual_items.items.length : 0;
    const kb = r.kb_search ? `KB 후보 ${r.kb_search.searched} → ${r.kb_search.sim_floor} 초과 ${r.kb_search.above_floor} → 사용 ${r.kb_search.used}`
      : r.kb ? "KB 사용" : "KB 꺼짐";
    return `평소와 다른 물건 ${unusual} · 일정 ${(r.calendar ?? []).length} · ${kb}`;
  }
  if (name === "s3") {
    const names = intentNames(trace);
    const intents = (r.bundles ?? []).map(({ intent_id }) => names[intent_id] ?? intent_id);
    return `${intents.length ? intents.join(", ") : `의도 없음 (${r.none_reason ?? "-"})`} · ${llmText(stage)}`;
  }
  if (name === "s4") {
    const drafts = r.drafts ?? [];
    const notices = drafts.filter(({ source }) => source === "item").length;
    return `할 일 ${drafts.length - notices} · 냉장고 안내 ${notices} · 버림 ${(r.dropped ?? []).length} · ${llmText(stage)}`;
  }
  return `카드 ${(r.cards ?? []).length} · 계획 v${r.plan_version ?? "-"} · 뺀 할 일 ${(r.dropped ?? []).length}`;
}

// Row keys as attributes, so the stylesheet can lay out S2 in columns without changing what the log says.
const ROW_KEYS = { "읽은 물건": "items", "가린 물건": "masked", "평소와 다른 물건": "unusual", "가까운 일정": "calendar",
  "가구 유형": "household", "KB 검색": "kb-search", "유사도 분포": "kb-dist", "의도별 이번 / 평소 · S3가 받은 예시": "kb-intents",
  "KB 메모": "kb-note" };
function row(key, value) {
  const data = ROW_KEYS[key] ? ` data-key="${ROW_KEYS[key]}"` : "";
  return `<div class="log-row"${data}><span class="log-key">${esc(key)}</span><div>${value}</div></div>`;
}

function itemsBody(r) {
  const items = r.items ?? [];
  const masked = items.filter(({ masked }) => masked).length;
  const lines = rows(items.filter(({ masked }) => !masked), ({ type, name, qty, attributes }) =>
    `<div class="log-item"><b>${esc(type)}</b><span class="log-qty">×${qty ?? "?"}</span>
    <span class="log-muted">← ${esc(name)}</span>${rows(attributes ?? [], (a) => `<span class="log-tag">${esc(attributeText(a))}</span>`)}</div>`);
  return row("읽은 물건", `<div class="log-items">${lines}</div>`) + (masked ? row("가린 물건", `${masked}개 (이름은 저장하지 않음)`) : "");
}

// Similarity of every searched case, binned; bins right of the floor are the cases kept (stored kb_search only).
function simDistribution({ sims, sim_floor, above_floor, used }) {
  const lo = Math.min(...sims, sim_floor), hi = Math.max(...sims, sim_floor), bins = 16;
  const width = (hi - lo) / bins || 1;
  const counts = Array(bins).fill(0);
  for (const s of sims) counts[Math.min(bins - 1, Math.floor((s - lo) / width))] += 1;
  const top = Math.max(...counts, 1);
  const bars = counts.map((c, i) => `<span class="${lo + i * width >= sim_floor ? "on" : ""}" style="height:${c ? Math.max(6, Math.round((c / top) * 100)) : 0}%"></span>`).join("");
  const line = Math.round(((sim_floor - lo) / (hi - lo || 1)) * 100);
  const capped = above_floor > used ? ` · 그중 점수 상위 ${used}건 사용` : "";
  return `<div class="log-dist">${bars}<u style="left:${line}%"></u></div>
    <span class="log-muted">검색된 ${sims.length}건 · 빨간 선 ${sim_floor} 오른쪽 ${above_floor}건${capped}</span>`;
}

function exampleCard({ items, intent_text }, sim) {
  return `<div class="log-example"><span class="log-muted">예시</span>${sim == null ? "" : ` <b class="log-mono">${sim.toFixed(2)}</b>`}
    ${esc((items ?? []).join(" · "))}
    <div><span class="log-muted">의도 문장</span> ${intent_text ? esc(intent_text) : "—"}</div></div>`;
}

function contextBody(trace, r) {
  const unusual = r.unusual_items;
  const unusualText = !unusual ? "이 집 맥락 꺼짐"
    : unusual.status === "list" ? rows(unusual.items, ({ item, why }) => `<span class="log-tag new">${esc(item)} · ${esc(why)}</span>`)
      : unusual.status === "all_usual" ? "모두 평소 사던 물건" : "지난 주문이 적어 비교 안 함";
  const calendar = (r.calendar ?? []).length ? rows(r.calendar, ({ id, tags, day, start, end, days_after }) =>
    `<div>${esc(id)} ${esc((tags ?? []).join("·") || "태그 없음")} · ${esc(day ?? "")} ${esc(start ?? "")}${end ? `–${esc(end)}` : ""}
    <span class="log-muted">· ${days_after ?? "?"}일 뒤</span></div>`) : "가까운 일정 없음";
  let out = row("평소와 다른 물건", unusualText) + row("가까운 일정", calendar);
  if (r.household_types?.length) out += row("가구 유형", esc(r.household_types.join(", ")));
  const search = r.kb_search;
  if (!search && !r.kb) return out + row("KB 검색", "꺼짐");
  const names = intentNames(trace);
  if (search) {
    out += row("KB 검색", `<span class="log-mono">후보 ${search.searched} → <span class="log-floor">유사도 ${search.sim_floor} 초과 ${search.above_floor}</span> → 사용 ${search.used}</span>`);
    if (search.sims?.length) out += row("유사도 분포", simDistribution(search));
  }
  const counts = (r.kb?.intent_counts ?? []).filter(({ n }) => n >= 1).slice(0, 4);
  if (counts.length) {
    const examples = r.kb?.examples ?? [];
    const sims = Object.fromEntries((search?.examples ?? []).map(({ case_id, sim }) => [case_id, sim]));
    out += row("의도별 이번 / 평소 · S3가 받은 예시", rows(counts, ({ intent_id, name, n, share, base_share }) => {
      const ex = examples.find((e) => e.intent_id === intent_id);
      return `<div class="log-share"><span>${esc(name)}</span><span class="log-mono">${n}건</span>
      <span class="log-bar"><i style="width:${Math.round((share ?? 0) * 100)}%"></i></span><b>${pct(share)}</b>
      <span class="log-muted">평소 ${pct(base_share)}</span></div>${ex ? exampleCard(ex, sims[ex.case_id]) : ""}`;
    }));
  }
  if (r.kb?.note) out += row("KB 메모", esc(r.kb.note));
  return out;
}

function intentBody(trace, r) {
  const names = intentNames(trace);
  if (!(r.bundles ?? []).length) return row("결과", `의도 없음 · ${esc(r.none_reason ?? "-")}`);
  return rows(r.bundles, ({ intent_id, intent_text, situation, basis, calendar_event_id, use_window }) => {
    const slots = rows(Object.entries(SLOT_LABELS), ([key, label]) => situation?.[key]
      ? `<div>${esc(label)} = <b>${esc(situation[key])}</b> <span class="log-muted">← ${esc((basis?.[key] ?? []).join(", ") || "-")}</span></div>` : "");
    const hm = (iso) => (iso ?? "").slice(5, 16).replace("T", " ");
    const when = use_window?.start ? ` · ${esc(hm(use_window.start))}${use_window.end ? `–${esc(hm(use_window.end).slice(6))}` : ""}` : "";
    return row("의도", `<b>${esc(names[intent_id] ?? intent_id)}</b> <span class="log-muted log-mono">${esc(intent_id)}</span>`)
      + row("문장", `<span class="log-big">${esc(intent_text)}</span>`)
      + row("근거", esc((basis?.intent ?? []).join(", ") || "-"))
      + row("상황", slots || "-")
      + row("일정", `${esc(calendar_event_id ?? "연결 없음")}${when}`);
  }) + ((r.unbundled ?? []).length ? row("묶지 않은 물건", esc(r.unbundled.join(", "))) : "");
}

function taskTime(trigger) {
  if (!trigger) return "-";
  if (trigger.time) return trigger.time.slice(5, 16).replace("T", " ");
  return trigger.on ?? trigger.event ?? JSON.stringify(trigger);
}

function tasksBody(r) {
  const drafts = r.drafts ?? [];
  const situation = drafts.filter(({ source }) => source !== "item");
  const notices = drafts.filter(({ source }) => source === "item");
  let out = row("할 일", situation.length ? rows(situation, ({ trigger, line, actions, way }) =>
    `<div class="log-task"><span class="log-mono log-muted">${esc(taskTime(trigger))}</span><span>${esc(line ?? "")}</span>
    <span class="log-mono log-muted">${esc((actions ?? []).map(({ device, cmd }) => `${device}.${cmd}`).join(" "))} · ${esc(way ?? "")}</span></div>`) : "없음");
  if (notices.length) {
    out += row("냉장고 안내", rows(notices, ({ meta, actions }) =>
      `<div>${esc(meta?.item ?? "")} · ${esc((actions ?? []).find(({ cmd }) => cmd === "show_notice")?.value ?? "")}</div>`));
  }
  if ((r.dropped ?? []).length) {
    out += row("버린 할 일", rows(r.dropped, ({ slug, item, reason, line }) =>
      `<div class="log-dropped"><s>${esc(line ?? slug ?? item ?? "")}</s> <span class="log-muted">· ${esc(why(reason))}</span></div>`));
  }
  return out;
}

function planBody(r) {
  const cards = r.cards ?? [];
  const dropped = r.dropped ?? [];
  let out = cards.length ? rows(cards, ({ card_id, text, lines }) => row(`카드 ${card_id}`, `<span class="log-big">${esc(text)}</span>${rows(lines ?? [], ({ text: line, state, when }) =>
    `<div class="log-task"><span class="log-mono log-muted">${esc(when?.time ? when.time.slice(11, 16) : when?.event ?? "")}</span><span>${esc(line)}</span><span class="log-mono log-muted">${esc(state)}</span></div>`)}`))
    : row("카드", dropped.some(({ source }) => source === "situation")
      ? "준비 카드 없음 · 상황 할 일이 아래 이유로 모두 빠짐" : "이번 주문에는 준비 카드가 없어요");
  if (dropped.length) {
    out += row("S5에서 뺀 할 일", rows(dropped, ({ line, item, reason }) =>
      `<div class="log-dropped"><s>${esc(line ?? item ?? "")}</s> <span class="log-muted">· ${esc(why(reason))}</span></div>`));
  }
  return out + row("계획", `v${r.plan_version ?? "-"} → 허브`);
}

function body(trace, name) {
  const stage = traceStage(trace, name);
  const r = stage?.result ?? {};
  if (stage?.state !== "done") return row("결과", esc(summary(trace, name)));
  if (name === "s1") return itemsBody(r);
  if (name === "s2") return contextBody(trace, r);
  if (name === "s3") return intentBody(trace, r);
  if (name === "s4") return tasksBody(r);
  return planBody(r);
}

// `shown` = the stage being presented (s1..s5) or null before S1 is shown; `now` = Server seconds since the order;
// `open` = a finished stage the presenter opened instead (one at a time; the shown stage folds meanwhile).
export function serverLog(trace, shown, now, { replay = null, open = null, kept = false, keeping = false } = {}) {
  const shownIndex = shown ? ORDER.indexOf(shown) : -1;
  const focus = open && ORDER.indexOf(open) <= shownIndex ? open : shown;
  const lines = [`<div class="log-line log-done"><span class="log-time">${clock(0)}</span><b>주문 받음</b><span>→ ${esc(trace.episode_id)}</span></div>`];
  ORDER.forEach((name, index) => {
    const stage = traceStage(trace, name);
    const mark = stage?.state === "done" ? "✓" : "";
    if (index <= shownIndex && name !== focus) {
      // Folded; a click opens it (and folds the one open now).
      const current = name === shown ? ' <span class="log-now">현재</span>' : "";
      lines.push(`<div class="log-line log-done log-fold" data-log-stage="${name}" role="button" tabindex="0" aria-expanded="false">
        <span class="log-time">${clock(stage?.done_s)}</span>
        <b>▸ ${TITLES[name]} <span class="log-ok">${mark}</span>${current}</b><span>${esc(summary(trace, name))}</span></div>`);
    } else if (index <= shownIndex) {
      const spent = took(trace, name);
      const reopened = name !== shown;
      lines.push(`<section class="log-current${reopened ? " log-opened" : ""}" data-trace="${name}">
        <header${reopened ? ` data-log-stage="${name}" role="button" tabindex="0" aria-expanded="true"` : ""}><span class="log-time">${clock(stage?.done_s)}</span>
        <b>${reopened ? "▾ " : ""}${TITLES[name]} <span class="log-ok">${mark}</span></b>
        <span class="log-muted">${spent == null ? "" : `${spent.toFixed(1)}s · `}${esc(stage?.llm || ["s1", "s3", "s4"].includes(name) ? llmText(stage) : "LLM 없음")}</span>
        ${reopened ? '<span class="log-back">눌러서 현재 단계로</span>' : ""}</header>
        ${body(trace, name)}</section>`);
    } else if (index === shownIndex + 1) {
      const before = traceStage(trace, ORDER[index - 1])?.done_s ?? 0;
      if (stage?.state === "running" && now != null) {
        lines.push(`<div class="log-line log-next"><span class="log-time">${clock(now)}</span><b>${TITLES[name]}</b>
          <span>${RUNNING[name]} … ${Math.max(0, Math.floor(now - before))}s <span class="log-cursor"></span></span></div>`);
      } else if (["done", "failed"].includes(stage?.state)) {
        lines.push(`<div class="log-line log-next"><span class="log-time">${clock(stage.done_s)}</span><b>${TITLES[name]}</b>
          <span>${stage.state === "done" ? "✓ 결과 도착 · 곧 펼침" : "실패"}</span></div>`);
      }
    }
  });
  const end = traceStage(trace, "s5");
  const ended = stageFinished(trace, "s5") && end?.done_s != null;
  const elapsed = replay ? Math.min(now ?? trace.at ?? 0, ended ? end.done_s : Infinity) : now;
  const badge = replay ? ["재현", startedLabel(trace.started_at), replay.speed ? `${replay.speed}×` : ""]
    .filter(Boolean).join(" · ") : "LIVE";
  // A finished live run can be kept for the replay (it survives the next reset).
  const keep = replay || end?.state !== "done" ? ""
    : kept ? '<span class="log-kept">✓ 재현용 보관됨</span>'
    : `<button type="button" class="log-keep" data-keep${keeping ? " disabled" : ""}>재현용 보관</button>`;
  return `<div class="server-log${replay ? " is-replay" : ""}"><div class="log-head"><b>SPIRA server</b><span>${esc(trace.episode_id)}</span>
    <span class="log-badge${replay ? " replay" : ""}">${esc(badge)}</span><span>경과 ${clock(elapsed)}</span>${keep}</div>
    <div class="log-body">${lines.join("")}</div></div>`;
}

// Before an order (server mode): the console waits and shows what the Server already knows about the home
// (GET /v1/demo/households/{id}/status), so S2 has its ground on screen before it runs.
const TAG_WORDS = { birthday: "생일", party: "파티", guests: "손님", family: "가족", dinner: "저녁", health: "병원·접종" };

function shortTime(iso, nowIso) {
  const at = new Date(iso);
  const now = nowIso ? new Date(nowIso) : new Date();
  if (Number.isNaN(at.getTime())) return "";
  const two = (n) => String(n).padStart(2, "0");
  const clockText = `${two(at.getHours())}:${two(at.getMinutes())}`;
  const sameDay = at.toDateString() === now.toDateString();
  return sameDay ? `오늘 ${clockText}` : `${at.getMonth() + 1}/${at.getDate()} ${clockText}`;
}

export function idleLog(status, { household = "" } = {}) {
  const head = `<div class="log-head"><b>SPIRA server</b><span>${esc(status?.household_id ?? household)}</span>
    <span class="log-badge idle">대기</span></div>`;
  if (!status) {
    return `<div class="server-log is-idle">${head}<div class="log-body"><div class="log-line log-next">
      <span class="log-time">--:--.-</span><b>서버 연결 확인</b><span>이 집 정보를 읽는 중 … <span class="log-cursor"></span></span></div></div></div>`;
  }
  const rooms = Object.entries(status.devices?.rooms ?? {}).map(([room, n]) => `${room} ${n}`).join(" · ");
  const latest = status.orders?.latest;
  const latestText = latest ? ` · 최근 ${shortTime(latest.shared_at, status.now)}${latest.items?.length
    ? ` (${latest.items.slice(0, 4).join(", ")}${latest.items.length > 4 ? " …" : ""})` : ""}` : "";
  const events = (status.calendar ?? []).slice(0, 3).map(({ id, start, tags }) =>
    `${esc(id)}${tags?.length ? ` ${esc(tags.map((tag) => TAG_WORDS[tag] ?? tag).join("·"))}` : ""} ${esc(shortTime(start, status.now))}`);
  const row = (key, value) => `<div class="log-row"><span class="log-key">${esc(key)}</span><div>${value}</div></div>`;
  return `<div class="server-log is-idle">${head}<div class="log-body">
    <section class="log-current log-idle"><header><span class="log-time">00:00.0</span><b>서버 준비</b>
      <span class="log-muted">데모 집 ${esc(status.household_id)} · 이 집에 대해 이미 아는 것</span></header>
      ${row("가구 유형", esc((status.household_types ?? []).join(", ") || "없음"))}
      ${row("집 기기", `${status.devices?.count ?? 0}대${rooms ? ` <span class="log-muted">(${esc(rooms)})</span>` : ""}`)}
      ${row("지난 주문", `${status.orders?.count ?? 0}건${esc(latestText)}`)}
      ${row("일정", events.length ? events.join(" <span class=\"log-muted\">·</span> ") : "다가오는 일정 없음")}
    </section>
    <div class="log-line log-next"><span class="log-time"></span><b>주문 대기</b>
      <span>왼쪽 앱에서 주문 화면을 올리면 여기서 시작해요 <span class="log-cursor"></span></span></div>
  </div></div>`;
}
