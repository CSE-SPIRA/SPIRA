// Architecture strip (11-28): one row of the system figure above the presenter log, judgment stages S1–S5 only.
// Input: the demo trace and the stage open in the log (s1..s5). Output: HTML. Nodes and labels are HTML, lines are SVG.
// Only the open stage's links are drawn, in the accent; a soft accent field sits behind the parts that stage uses.
// No motion: the state is shown by colour and weight only.
import { esc } from "./markup.js";

const ASSET = "/demo/assets/arch/";
// Big name = the part's role, small name = what it is built with. Logos from Seojin (11-28); Home keeps a line icon.
export const ARCH_NODES = [
  { id: "app", name: "App", sub: "Flutter", w: 120, logo: "spira-app.png" },
  { id: "server", name: "Server", sub: "EC2 · FastAPI", w: 160, logo: "amazon-ec2.svg" },
  { id: "llm", name: "LLM", sub: "Claude API", w: 138, logo: "claude.png" },
  { id: "db", name: "DB", sub: "RDS · PostgreSQL", w: 184, logo: "amazon-rds.svg" },
  { id: "kb", name: "Knowledge base", sub: "GitHub Actions", w: 206, logo: "github.png", join: true },
  { id: "hub", name: "Hub", sub: "LG ThinQ ON", w: 152, logo: "lg.svg" },
  { id: "home", name: "Home", sub: "가전 · IoT", w: 134, join: true },
];
const HOME_ICON = '<svg class="arch-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11l8-7 8 7"/><path d="M6 9.5V20h12V9.5"/>'
  + '<path d="M12 12.5a2.5 2.5 0 0 1 1.5 4.5v1.5h-3V17a2.5 2.5 0 0 1 1.5-4.5z"/></svg>';

// Parts and links each stage uses (server/spec.md, docs/architecture.md). A link to or from the Server runs over a
// lane above the row; a joined pair (DB ← Knowledge base) is linked inside its plate.
export const ARCH_STAGES = {
  s1: { nodes: ["app", "server", "llm"], main: "llm", links: [
    { from: "app", to: "server", label: "주문 캡처" }, { from: "server", to: "llm", label: "주문 추출" }] },
  s2: { nodes: ["server", "db", "kb"], main: "db", links: [
    { from: "server", to: "db", label: "이 집 기록 · 비슷한 사례 검색", both: true }, { from: "kb", to: "db", joined: true }] },
  s3: { nodes: ["server", "llm"], main: "llm", links: [
    { from: "server", to: "llm", label: "주문 · 맥락 · 사례 → 의도" }] },
  s4: { nodes: ["server", "llm"], main: "llm", links: [
    { from: "server", to: "llm", label: "의도 · 이 집 기기 → 할 일" }] },
  s5: { nodes: ["server", "app", "hub"], main: "server", links: [
    { from: "server", to: "app", label: "준비 카드" }, { from: "server", to: "hub", label: "기기 계획" }] },
};
export const ARCH_TITLES = { s1: "S1 주문 추출", s2: "S2 맥락 검색", s3: "S3 의도 추론", s4: "S4 할 일 생성", s5: "S5 계획 확정" };

const LANE = { app: 46, llm: 46, db: 28, hub: 10 };
const ANCHOR = { app: -18, llm: 6, db: 14, hub: 22 };
const TOP = 58, HEIGHT = 64, JOIN = 28;

// x, width and centre of every node for a strip `width` px wide.
export function archLayout(width) {
  const joins = ARCH_NODES.filter((n) => n.join).length;
  const gap = (width - ARCH_NODES.reduce((s, n) => s + n.w, 0) - joins * JOIN) / (ARCH_NODES.length - 1 - joins);
  const at = {};
  let x = 0;
  ARCH_NODES.forEach((node, i) => {
    if (i) x += node.join ? JOIN : gap;
    at[node.id] = { x, w: node.w, cx: x + node.w / 2 };
    x += node.w;
  });
  return at;
}

// The stage's state from the trace: done, running, failed, skipped or pending.
export function archState(trace, open) {
  return trace?.stages?.find((stage) => stage.name === open)?.state ?? "pending";
}

export function archStrip(trace, open, { width = 1280, replay = false } = {}) {
  // No stage yet (waiting for an order): the parts only, nothing lit.
  const spec = open == null ? { nodes: [], main: null, links: [] } : ARCH_STAGES[open];
  if (!spec) return "";
  const at = archLayout(width);
  const state = archState(trace, open);
  const server = at.server;
  const lane = (to) => `M${server.cx + ANCHOR[to]},${TOP} V${LANE[to]} H${at[to].cx} V${TOP}`;
  const mid = TOP + HEIGHT / 2;

  const lines = spec.links.map((l) => {
    if (l.joined) return `<path class="arch-link" pathLength="1" d="M${at[l.from].x - 3},${mid} H${at[l.to].x + at[l.to].w + 3}" marker-end="url(#arch-head)"/>`;
    const toServer = l.to === "server";
    const part = toServer ? l.from : l.to;
    const ends = l.both ? ' marker-start="url(#arch-head)" marker-end="url(#arch-head)"'
      : toServer ? ' marker-start="url(#arch-head)"' : ' marker-end="url(#arch-head)"';
    return `<path class="arch-link" pathLength="1" d="${lane(part)}"${ends}/>`;
  }).join("");
  const labels = spec.links.filter((l) => l.label).map((l) => {
    const part = l.to === "server" ? l.from : l.to;
    const a = server.cx + ANCHOR[part], b = at[part].cx;
    // A long lane runs over nearer parts: its label sits over the last gap so it does not cover their links.
    const x = part === "db" ? (at.llm.cx + at.db.cx) / 2 + 10 : part === "hub" ? (at.kb.x + at.hub.cx) / 2 : (a + b) / 2;
    return `<span class="arch-label" style="left:${x}px;top:${LANE[part]}px">${esc(l.label)}</span>`;
  }).join("");

  const used = ARCH_NODES.filter((n) => spec.nodes.includes(n.id));
  const left = Math.min(...used.map((n) => at[n.id].x)) - 10;
  const right = Math.max(...used.map((n) => at[n.id].x + n.w)) + 10;
  const field = used.length ? `<div class="arch-field" style="left:${left}px;width:${right - left}px"></div>` : "";
  const plates = ARCH_NODES.filter((n) => n.join).map((n) => {
    const prev = ARCH_NODES[ARCH_NODES.indexOf(n) - 1];
    return `<div class="arch-plate" style="left:${at[prev.id].x - 7}px;width:${at[n.id].x + n.w - at[prev.id].x + 14}px"></div>`;
  }).join("");
  const nodes = ARCH_NODES.map((n) => {
    const cls = ["arch-node", spec.nodes.includes(n.id) ? "on" : "", n.id === spec.main ? "main" : ""].filter(Boolean).join(" ");
    const icon = n.logo ? `<img class="arch-icon" src="${ASSET}${n.logo}" alt="">` : HOME_ICON;
    return `<div class="${cls}" data-node="${n.id}" style="left:${at[n.id].x}px;width:${n.w}px">${icon}<b>${esc(n.name)}</b><span>${esc(n.sub)}</span></div>`;
  }).join("");

  const label = open == null ? "시스템 구성 · 주문 대기" : `시스템 구성 · ${ARCH_TITLES[open]}이 쓰는 부품: ${used.map((n) => n.name).join(", ")}`;
  return `<div class="arch-strip arch-${open == null ? "idle" : state}${replay ? " is-replay" : ""}" data-arch="${open ?? "idle"}" role="img"
    aria-label="${esc(label)}">
    ${field}${plates}
    <svg class="arch-lines" width="${width}" height="${TOP + HEIGHT}" aria-hidden="true">
      <defs><marker id="arch-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" class="arch-head"/></marker></defs>${lines}</svg>
    ${labels}${nodes}</div>`;
}
