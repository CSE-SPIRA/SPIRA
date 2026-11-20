// Demo shell: page 1 projects the Server's reasoning from the team contract
// (episode, rationale, cards); page 2 shows the house from the World snapshot
// and the Hub's ledger. Staging lives in flow.js, house.js and tokens.css.
import { createFlow } from "/demo/assets/flow.js";
import { createHouse } from "/demo/assets/house.js";

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const DEVICE = {
  cleaner: "로봇청소기", light: "조명", display: "TV", cooktop: "인덕션", oven: "오븐",
  fridge: "냉장고", smart_plug: "스마트 플러그", speaker: "스피커",
};
const FIELD = { event: "행사", guests: "손님", activity: "활동", theme: "테마" };
const WAY = { run: "실행", standby: "대기", notice: "안내" };

const state = {
  config: null, scenes: null, flow: null, house: null,
  step: 0, episodeId: null, episode: null, rationale: null, card: null, error: null,
};

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

// ---------- page switching ----------
function showPage(name) {
  document.querySelectorAll(".tabs button").forEach((b) => {
    if (b.dataset.page === name) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  $("#page-reason").hidden = name !== "reason";
  $("#page-house").hidden = name !== "house";
  if (name === "house") {
    if (!state.house) state.house = createHouse($("#house3d"), $("#house-tags"), $("#house-hud"));
    state.house.resize();
    state.house.setReasons(reasonsByDevice());
  }
}

// ---------- page 1: reasoning ----------
async function share(files) {
  const form = new FormData();
  for (const f of files) form.append("images", f, f.name || "order.png");
  state.error = null;
  try {
    const accepted = await api("/demo/api/order", { method: "POST", body: form });
    state.episodeId = accepted.episode_id;
    state.episode = state.rationale = state.card = null;
    setStep(1);
    poll();
  } catch (e) {
    state.error = "주문을 보내지 못했어요 (" + e.message + ")";
    render();
  }
}

async function poll() {
  const id = state.episodeId;
  const hid = state.config.household_id;
  for (let i = 0; i < 600 && id === state.episodeId; i++) {
    try {
      state.episode = await api(`/demo/api/server/v1/episodes/${id}`);
      if (!state.rationale) {
        state.rationale = await api(`/demo/api/server/v1/episodes/${id}/rationale`).catch(() => null);
      }
      const cards = await api(`/demo/api/server/v1/households/${hid}/cards`);
      state.card = cards.cards.find((c) => c.episode_id === id) || state.card;
      render();
      if (state.rationale && state.card) return;
    } catch (e) { /* the Server may still be reading */ }
    await sleep(1000);
  }
}

function sampleOrder() {
  // A plain order list drawn on a canvas, so the demo runs without a real screenshot.
  const c = document.createElement("canvas");
  c.width = 720; c.height = 1280;
  const g = c.getContext("2d");
  g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = "#111"; g.font = "700 40px sans-serif"; g.fillText("주문 상세", 40, 80);
  const rows = ["설향 딸기 500g (냉장) × 2", "OO 컵케이크 믹스", "동물성 휘핑크림 500ml × 1",
    "OO 액체 세탁세제 3L × 1", "OO 베이비 로션 300ml × 1", "파티 풍선 세트 × 1",
    "디즈니 공주 케이크 토퍼 × 1", "파티 고깔모자 × 6", "아이싱 펜 × 1"];
  g.font = "32px sans-serif";
  rows.forEach((r, i) => { g.fillStyle = "#eee"; g.fillRect(40, 130 + i * 110, 120, 90); g.fillStyle = "#222"; g.fillText(r, 190, 190 + i * 110); });
  return new Promise((r) => c.toBlob((b) => r(new File([b], "sample-order.png", { type: "image/png" })), "image/png"));
}

function phone() {
  const s = state.step;
  if (s === 0 || !state.episodeId) {
    return `
      <div class="app-title">SPIRA</div>
      <div class="app-sub">우리 집 · 지아네</div>
      <div class="app-card"><h3>주문을 공유해 주세요</h3>
        <div class="app-when">쇼핑 앱의 주문 화면을 SPIRA로 공유하면, 집이 알아서 준비해요.</div></div>
      ${state.error ? `<div class="app-card" role="alert">${esc(state.error)}</div>` : ""}
      <div class="share">
        <label>스크린샷 공유<input type="file" id="files" accept="image/png,image/jpeg" multiple hidden></label>
        <button type="button" id="sample">예시 주문으로</button>
      </div>`;
  }
  const ep = state.episode;
  if (s < 5 || !state.card) {
    const read = ep && ep.item_count ? `주문을 읽었어요 (${ep.item_count}개)` : "주문을 읽는 중이에요";
    return `<div class="app-title">SPIRA</div><div class="app-sub">우리 집 · 지아네</div>
      <div class="app-card"><h3>${read}</h3><div class="app-when">준비할 일이 있으면 알려 드릴게요.</div></div>
      ${ep && ep.item_count ? "" : '<div class="spinner" aria-label="읽는 중"></div>'}`;
  }
  const card = state.card;
  return `<div class="app-title">SPIRA</div><div class="app-sub">우리 집 · 지아네</div>
    <div class="app-card"><h3>${esc(card.text)}</h3>
      ${card.lines.map((l) => `<div class="app-line"><span class="box"></span><div>${esc(l.text)}
        <div class="app-when">${esc(when(l.when))}</div></div></div>`).join("")}
    </div>
    <div class="app-sub">멈추기는 카드에서 언제든</div>`;
}

function when(w) {
  if (!w) return "";
  if (w.time) {
    const d = new Date(w.time);
    return d.toLocaleString("ko-KR", { weekday: "short", hour: "2-digit", minute: "2-digit" });
  }
  return { guest_arrived: "손님이 오시면", event_end: "행사가 끝나면", "package.brought_in": "택배를 들이면" }[w.event] || w.event || "";
}

function waiting(what) {
  return `<div class="spinner" aria-label="${what}"></div><p class="lead" style="text-align:center">${what}</p>`;
}

function stageBody(id) {
  const ep = state.episode, r = state.rationale;
  if (id === "share") {
    return `<p>앱은 주문 화면만 받습니다. 양식도, 질문도 없습니다.</p>`;
  }
  if (id === "extract") {
    if (!ep || !ep.items || !ep.items.length) return waiting("주문을 읽는 중");
    const inIntent = new Set((r?.intents || []).flatMap((i) => i.basis?.intent || []));
    return `<div class="items">${ep.items.map((it) => `
      <div class="item"><b>${esc(it.type)} × ${it.qty ?? "모름"}</b><small>${esc(it.name)}</small></div>`).join("")}</div>
      ${ep.masked_count ? `<h4>가린 물건 ${ep.masked_count}개</h4>` : ""}`;
  }
  if (!r) return waiting("판단하는 중");
  if (id === "context") {
    const ev = r.evidence || {};
    const total = (ev.kb_counts || []).reduce((a, b) => a + b.n, 0) || 1;
    return `
      <h4>이 집에서 평소와 다른 물건</h4>
      <div class="chips">${(ev.unusual_items?.items || []).map((u) => `<span class="chip hot" title="${esc(u.why)}">${esc(u.item)} · ${esc(u.why)}</span>`).join("")}
        ${(ev.unusual_items?.usual || []).map((u) => `<span class="chip">${esc(u)} · 평소</span>`).join("")}</div>
      <h4>캘린더 (공유한 날 기준)</h4>
      <div class="chips">${(ev.calendar || []).map((c) => `<span class="chip">${c.days_after}일 뒤 ${esc(c.day)} ${esc(c.start)}–${esc(c.end)} · ${esc(c.tags.join(", "))}</span>`).join("") || '<span class="chip">행사 일정 없음</span>'}</div>
      <h4>비슷한 다른 집 주문 ${total}건 (합성 지식 베이스)</h4>
      <div class="bars">${(ev.kb_counts || []).map((k, i) => `
        <div class="bar"><span>${esc(k.name)}</span><i class="${i ? "dim" : ""}" style="width:${(k.n / total) * 100}%"></i><span>${k.n}</span></div>`).join("")}</div>
      ${ev.kb_note ? `<p class="lead">${esc(ev.kb_note)}</p>` : ""}
      <h4>대표 사례</h4>
      <div class="items">${(ev.kb_examples || []).map((x) => `
        <div class="item"><b>${esc(x.intent_text)}</b><small>겹치는 물건 ${x.overlap.k}/${x.overlap.n}: ${esc(x.overlap.items.join(", "))}</small></div>`).join("")}</div>`;
  }
  if (id === "intent") {
    if (!r.intents.length) return `<p class="intent">의도 없음</p><p class="lead">${esc(r.none_reason)}</p>`;
    return r.intents.map((i) => `
      <p class="intent">${esc(i.intent_text)}</p>
      <dl class="situation">${Object.entries(FIELD).map(([k, label]) => i.situation[k] ? `
        <dt>${label}</dt><dd>${esc(i.situation[k])}</dd><span class="why">근거: ${esc((i.basis[k] || []).map((b) => b === i.calendar_event_id ? "캘린더 일정" : b).join(", "))}</span>` : "").join("")}
      </dl>
      <h4>의도와 묶지 않은 물건</h4>
      <div class="chips">${(r.unbundled || []).map((u) => `<span class="chip">${esc(u)}</span>`).join("")}</div>`).join("");
  }
  if (id === "tasks") {
    return `<div class="tasks">${r.tasks.map((t) => `
      <div class="task"><span class="need">${esc(t.need)}</span><span class="arrow">→</span>
        <span class="line"><b>${esc(t.line)}</b><small>${WAY[t.way] || t.way} · ${esc(t.devices.map((d) => DEVICE[d.type] || d.type).join(", "))}</small></span></div>`).join("")}</div>
      ${(r.item_tasks || []).length ? `<h4>택배를 들이면 (물건 단위)</h4><div class="chips">${r.item_tasks.map((t) => `<span class="chip">${esc(t.item)}: ${esc(t.text || t.kind)}</span>`).join("")}</div>` : ""}`;
  }
  if (id === "plan") {
    if (!state.card) return waiting("계획을 확정하는 중");
    return `<p class="intent">${esc(state.card.text)}</p>
      <p class="lead">카드 ${state.card.lines.length}줄, 사용자에게 한 번 알립니다. 계획은 집 허브로 갔습니다.</p>
      <button type="button" class="btn primary" id="to-house">집으로 →</button>`;
  }
  return "";
}

function render() {
  const scene = state.scenes.reason[state.step];
  state.flow.setStage(scene.node);
  $("#phone").innerHTML = phone();
  $("#stage-out").innerHTML = `<h2>${esc(scene.title)}</h2><p class="lead">${esc(scene.lead)}</p>${stageBody(scene.id)}`;
  $("#step-label").textContent = `${state.step + 1} / ${state.scenes.reason.length}`;
  $("#prev").disabled = state.step === 0;
  $("#next").disabled = state.step === state.scenes.reason.length - 1 || (state.step === 0 && !state.episodeId);
  const files = $("#files");
  if (files) files.onchange = () => files.files.length && share([...files.files].slice(0, 3));
  const sample = $("#sample");
  if (sample) sample.onclick = async () => share([await sampleOrder()]);
  const toHouse = $("#to-house");
  if (toHouse) toHouse.onclick = () => showPage("house");
}

function setStep(n) {
  state.step = Math.max(0, Math.min(state.scenes.reason.length - 1, n));
  render();
}

// ---------- page 2: house ----------
function reasonsByDevice() {
  const out = {};
  for (const t of state.rationale?.tasks || []) for (const d of t.devices) out[d.id] = t.line;
  for (const t of state.rationale?.item_tasks || []) out.fridge_01 = out.fridge_01 || t.text;
  return out;
}

let houseStep = -1;
function renderTimeline() {
  $("#timeline").innerHTML = state.scenes.house.map((s, i) => `
    <li><button type="button" data-i="${i}" ${i === houseStep ? 'aria-current="step"' : ""}>
      <span class="tm">${esc(s.time)}</span><span>${esc(s.title)}</span></button></li>`).join("");
  $("#timeline").querySelectorAll("button").forEach((b) => (b.onclick = () => goHouse(+b.dataset.i)));
}

async function goHouse(i) {
  const s = state.scenes.house[i];
  houseStep = i;
  renderTimeline();
  if (state.house) {
    state.house.focus(s.camera);
    state.house.setMoment(s.id);
  }
  if (s.action) {
    try { await api(`/demo/api/home/${s.action}`, { method: "POST" }); }
    catch (e) { $("#status").textContent = `사건을 보내지 못했어요: ${e.message}`; }
  }
}

async function pollHouse() {
  for (;;) {
    if (!$("#page-house").hidden && state.house) {
      try { state.house.update(await api("/sim/snapshot")); } catch (e) { /* keep last */ }
      if (state.config.hub) {
        try { renderLedger((await api("/demo/api/hub")).ledger); } catch (e) { /* keep last */ }
      }
    }
    await sleep(800);
  }
}

let ledgerSize = -1;
function renderLedger(rows) {
  if (rows.length === ledgerSize) return;
  ledgerSize = rows.length;
  const BY = { spira: "SPIRA", user: "사람", hub: "허브", unknown: "모름" };
  $("#ledger").innerHTML = rows.slice().reverse().map((row) => {
    const at = new Date(row.at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
    const sent = row.reports?.length ? (row.reports.every((x) => x.delivered) ? "서버에 보냄" : "보내는 중") : "";
    return `<li class="by-${esc(row.by)}"><time>${at}</time><div><b>${esc(row.label)}</b> ${esc(row.what)}
      <div class="sent">${BY[row.by] || esc(row.by)}${sent ? " · " + sent : ""}</div></div></li>`;
  }).join("");
}

// ---------- boot ----------
async function boot() {
  [state.config, state.scenes] = await Promise.all([api("/demo/api/config"), api("/demo/assets/scenes.json")]);
  state.flow = createFlow($("#flow"), state.scenes.flow);
  $("#status").textContent = [
    state.config.server ? (state.config.fixture ? "판단: 예시(fixture)" : "판단: Server") : "Server 연결 없음",
    state.config.hub ? "허브 연결" : "허브 없음",
  ].join(" · ");
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => showPage(b.dataset.page)));
  $("#prev").onclick = () => setStep(state.step - 1);
  $("#next").onclick = () => setStep(state.step + 1);
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea")) return;
    if (e.key === "ArrowRight") $("#page-house").hidden ? setStep(state.step + 1) : goHouse(Math.min(houseStep + 1, state.scenes.house.length - 1));
    if (e.key === "ArrowLeft" && $("#page-house").hidden) setStep(state.step - 1);
  });
  renderTimeline();
  // Deep links for rehearsal and screenshots: ?episode=ep_9031&step=3&page=house
  const q = new URLSearchParams(location.search);
  if (q.get("episode")) { state.episodeId = q.get("episode"); poll(); }
  state.step = Math.max(0, Math.min(state.scenes.reason.length - 1, +(q.get("step") || 0)));
  render();
  if (q.get("page") === "house") showPage("house");
  pollHouse();
}

boot();
