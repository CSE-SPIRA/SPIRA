// Reasoning uses the Server's app contract. House surfaces use World observations.
import { createFlow } from "./flow.js";
import { buildChain } from "./chain.js";
import { readProblem } from "./wire.js";
import { JUDGMENT_STAGES } from "./judgment.js";
import { replayFrames } from "./run.js";
import { worldFacts } from "./scene-rules.js";
import { createReasoning } from "./reasoning.js";
import { createOrderShare } from "./order-share.js";
import { createHouseRecord } from "./house-record.js";
import { createEpisodeReader } from "./episode.js";
import { createHouseTimeline } from "./house-timeline.js";
import { createPresenter } from "./presenter.js";
import { createRecordingPlayback } from "./recording.js";

document.querySelector('meta[name="theme-color"]').content =
  getComputedStyle(document.documentElement).getPropertyValue("--paper").trim();

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const query = new URLSearchParams(location.search);
const RECORDING = query.get("recording");
const REPLAY = Boolean(RECORDING) || query.get("replay") === "1";
const QUIET_END = { event: "judgment.quiet_end" };
const OWNERS = { server: "서버 창" };

const defaultPath = (episode) => episode === "ep_9031" ? "house" : "plan";

const state = {
  config: null, scenes: null, flow: null, house: null, scale: 1, page: "reason",
  order: "birthday", draft: false, step: 0, sharing: false,
  runPath: null, draftPath: null, tags: [],
  episodeId: null, episode: null, rationale: null, rationaleMissing: false, judgment: [], cards: [], reader: null,
  sharedEpisode: null, recordRequested: false, recordVisible: false,
  quietEnd: null, quietRamped: new Set(), clockMissing: false, clockMoments: false,
  readProblems: {}, cardsRead: false,
  auto: null, shownAt: null, homeId: "plan", followGuest: false, homeBusy: false, hub: null, snapshot: null, houseMarkup: "", chain: buildChain(),
  facts: new Map(), pendingClockLines: new Set(), playedMotion: new Set(), appliedScene: null, replayStep: 0,
};

function retryNotice(error, reader) {
  if (state.reader !== reader || reader?.signal.aborted || !reader || readProblem(error.status)) return;
  state.retryUntil = performance.now() + 3500;
  ui.reasoning.renderStageIndicator();
}

async function observe(kind, path, options, { text = false, transform = (value) => value, read } = {}) {
  const { reader, record } = state;
  try {
    const response = await fetchResponse(path, options);
    const data = transform(await (text ? response.text() : response.json()));
    if (state.reader === reader) {
      const story = kind === "clock" ? Date.parse(data.now ?? data.story_at) : undefined;
      record?.(kind, data, ...ui.recording.stamp(story), read);
    }
    return data;
  } catch (error) {
    if (["episode", "rationale", "cards", "hub"].includes(kind)) retryNotice(error, reader);
    throw error;
  }
}

async function fetchResponse(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw Object.assign(new Error(response.status), { status: response.status });
  return response;
}

async function api(path, options) {
  return (await fetchResponse(path, options)).json();
}

function notice(text = "") {
  $("notice").textContent = text;
}

function linkDashboard() {
  const address = query.get("dashboard");
  if (!address) return;
  try {
    const url = new URL(address);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return;
    $("dashboard-link").href = url.href;
    $("dashboard-link").hidden = false;
  } catch {
    // A malformed address leaves the optional link hidden.
  }
}

async function exchange(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => null);
  return { status: response.status, ok: response.ok, body };
}

const AUTO_PLAY = !RECORDING && query.get("auto") === "1";

function decorateHouseLabel(marker, { focused, moment }) {
  const label = marker.firstElementChild;
  const resting = !focused && !marker.hasAttribute("data-changed");
  marker.toggleAttribute("data-resting", resting);
  const value = label.querySelector(".device-value");
  value?.classList.toggle("visually-hidden", resting);
  if (value && marker.dataset.device === "fridge_01") value.title = value.textContent;

  let annotation = label.querySelector(".marker-moment");
  if (!annotation && moment && value) {
    annotation = document.createElement("span");
    annotation.className = "marker-moment";
    label.append(annotation);
  }
  if (annotation) {
    annotation.textContent = moment;
    annotation.hidden = !moment;
  }
}

async function refreshSnapshot() {
  const { reader } = state;
  const snapshot = await observe("snapshot", "/demo/api/sim/snapshot", { signal: AbortSignal.timeout(2500) });
  if (state.reader !== reader) return;
  state.snapshot = snapshot;
  ui.reasoning.refreshChain();
  if (state.page === "house") {
    ui.house.renderTimeline();
    void loadHouse();
  }
  revealHouseState();
}

async function refreshHouseMarkers() {
  const { reader } = state;
  const markup = await observe("viewer", "/demo/api/sim/viewer", { signal: AbortSignal.timeout(2500) }, { text: true });
  if (state.reader === reader) {
    applyHouseMarkers(markup);
    if (state.page === "house") {
      ui.house.renderTimeline();
      void loadHouse();
    }
  }
}

const MARKER_TAGS = new Set(["SECTION", "DIV", "ARTICLE", "H2", "H3", "SPAN", "SMALL", "P", "BUTTON", "UL", "LI", "TIME"]);
const MARKER_ATTRIBUTE = /^(?:id|class|title|role|type|tabindex|datetime|popover|popovertarget|aria-[a-z-]+|data-[a-z-]+)$/;

async function checkHouseBeforeShare() {
  try {
    const response = await fetchResponse("/demo/api/sim/viewer", { cache: "no-store", signal: AbortSignal.timeout(2500) });
    const fragment = new DOMParser().parseFromString(await response.text(), "text/html");
    const markers = fragment.getElementById("viewer-markers");
    if (!markers) return;
    // These observations already exist before the order write, even if the next share rewinds story time.
    $("stale-house").hidden = !markers.querySelector("[data-signal], [data-guest-arrival], [data-device][data-changed]");
  } catch {
    // The share can still proceed if the viewer is temporarily unavailable.
  }
}

function checkHouseAtOpen(fragment, markers, facts) {
  const warning = $("stale-house");
  if (!warning.hidden) return;
  const sharedAt = Date.parse(state.episode?.shared_at);
  const worldAt = Date.parse(fragment.querySelector("time.wall-clock")?.getAttribute("datetime"));
  const guestAt = markers.querySelector("[data-guest-arrival]")?.dataset.guestArrival;
  const times = [...facts.map(({ at }) => Date.parse(at)), Date.parse(guestAt)];
  if (times.some((at) => at < sharedAt || at > worldAt)) warning.hidden = false;
}

function applyHouseMarkers(markup) {
  if (!markup || markup === state.houseMarkup) return;
  const fragment = new DOMParser().parseFromString(markup, "text/html");
  const markers = fragment.getElementById("viewer-markers");
  if (!markers || markers.tagName !== "DIV") return;
  for (const node of [markers, ...markers.querySelectorAll("*")]) {
    if (!MARKER_TAGS.has(node.tagName) || ["planned", "planned-clock", "planned-detail", "observed-outcome"].some((name) => node.classList.contains(name))) {
      node.remove();
      continue;
    }
    for (const attr of [...node.attributes]) {
      if (!MARKER_ATTRIBUTE.test(attr.name)) node.removeAttribute(attr.name);
    }
  }
  state.houseMarkup = markup;
  const facts = RECORDING ? [] : worldFacts(markers);
  if (!REPLAY && state.page === "house") checkHouseAtOpen(fragment, markers, facts);
  const clocks = [...markers.querySelectorAll("time.wall-clock")].map((node) => {
    const reading = { node, text: node.textContent, datetime: node.getAttribute("datetime") };
    node.textContent = "";
    node.removeAttribute("datetime");
    return reading;
  });
  const signature = markers.outerHTML;
  const current = $("viewer-markers");
  const unchanged = signature === state.markerSignature;
  const displayClocks = unchanged ? current.querySelectorAll("time.wall-clock") : clocks.map(({ node }) => node);
  clocks.forEach(({ text, datetime }, index) => {
    const node = displayClocks[index];
    if (node.textContent !== text) node.textContent = text;
    if (datetime === null) node.removeAttribute("datetime");
    else node.setAttribute("datetime", datetime);
  });
  if (unchanged) return;
  state.markerSignature = signature;
  if (!RECORDING) ui.house.rememberFacts(facts);
  state.displayReadings = new Map([...markers.querySelectorAll("[data-device][data-values]")].map(
    ({ dataset }) => [dataset.device, JSON.parse(dataset.values)]));
  if (state.houseModule) state.houseModule.replaceHouseMarkers(current, markers);
  else current.replaceWith(markers);
  state.house?.setMarkers(markers);
  revealHouseState();
}

function revealHouseState() {
  const ready = Boolean(state.snapshot && state.houseMarkup && $("world").hasChildNodes());
  $("house-waiting").hidden = ready;
  $("view").toggleAttribute("data-observed", ready);
}

async function loadHouse() {
  if (state.houseLoading || $("world").hasChildNodes() || !state.snapshot || !state.houseMarkup ||
      state.page !== "house") return;
  state.houseLoading = true;
  const base = RECORDING ? "/demo/replay-house/" : "/sim/assets/house/";
  try {
    const [module, devices, scenes, vocabulary] = await Promise.all([
      import(base + "house.js"), import(base + "devices.js"), import(base + "scene.js"), import(base + "scene-vocabulary.js"),
    ]);
    state.validateScene = scenes.validateScene;
    state.sceneVocabulary = vocabulary.default;
    state.houseModule = module;
    state.houseDevices = devices.HOUSE_DEVICES;
  } catch {
    return;
  } finally {
    state.houseLoading = false;
  }
  for (const name of ["house.css", "viewer.css"]) {
    const style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = base + name;
    document.head.insertBefore(style, $("shell-style"));
  }
  try {
    // An empty sample map keeps the renderer's TV party atmosphere out of the shell.
    // All device readings still come from the Simulator's observed markers.
    state.house = state.houseModule.createHouse($("world"), { decorateLabel: decorateHouseLabel, sampleReadings: {} });
    state.house.setMarkers($("viewer-markers"));
  } catch (error) {
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = "이 화면에서 입체 집을 열 수 없어요.";
    $("world").append(message);
    console.error(error);
  }
  ui.reasoning.refreshChain();
  ui.recording.flushReplayScenes();
  ui.house.renderTimeline({ instant: true });
  revealHouseState();
}

function embedApp(address) {
  if (!address) return;
  let url;
  try {
    url = new URL(address);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return;
  } catch {
    return;
  }
  $("app-preview").src = url.href;
  $("app-preview").hidden = false;
  $("app-placeholder").hidden = true;
}

async function boot() {
  const [source, sceneData, itemTypes] = await Promise.all([
    api(RECORDING ? `/demo/api/recordings/${encodeURIComponent(RECORDING)}` : "/demo/api/config", {
      headers: query.has("episode") ? { "X-SPIRA-Demo-Episode": query.get("episode") } : {},
    }),
    api(new URL("./scenes.json", import.meta.url)),
    api(new URL("./item-types.json", import.meta.url)),
  ]);
  state.scenes = sceneData;
  state.itemTypes = itemTypes;
  state.config = RECORDING ? { household_id: source.household_id, story_timing: source.story_timing } : source;
  embedApp(state.config.app_url);
  const stages = state.scenes.reason;
  state.scenes.reason = stages.flatMap((scene) => {
    const beats = JUDGMENT_STAGES[scene.id] ?? [];
    return beats.length ? beats.map((beat) => ({ ...scene, beat })) : [scene];
  });
  state.flow = createFlow($("stage-steps"), $("stage-beat"));
  ui.presenter.bindControls();

  $("frame").toggleAttribute("data-recording", Boolean(RECORDING));
  $("frame").toggleAttribute("data-owners", query.get("owners") === "1");
  linkDashboard();
  // Rehearsal aid: ?camera=<name> holds a named camera (for framing close-ups).
  if (query.get("camera")) setTimeout(() => {
    $("view").setAttribute("data-closeup", "");
    state.house?.focus(ui.house.roomCamera(query.get("camera")), { instant: true });
  }, 1500);
  if (RECORDING) {
    state.episodeId = source.episode_id;
    state.replay = replayFrames(source.entries, state.scenes.house);
    state.runPath = source.demo_path ?? (state.replay.house.length ? "house" : "plan");
    state.tags = source.tags?.data ?? [];
    ui.recording.applyReplayFrame(state.replay.judgment);
    ui.reasoning.setStep(ui.reasoning.reasonStep("extract"));
    if (!state.episode) notice("이 녹화에는 받은 주문 결과가 없어요.");
    ui.presenter.tickClock();
    return;
  }
  const id = query.get("episode");
  const requested = Number(query.get("step") || 0);
  const stage = Number.isInteger(requested) ? stages[Math.max(0, Math.min(stages.length - 1, requested))] : stages[0];
  const inHouse = id && (query.get("page") === "house" || requested === 6 || requested === 7);
  const step = ui.reasoning.reasonStep(inHouse ? "plan" : stage.id);
  state.houseLink = inHouse ? { record: requested === 7 } : null;
  if (id) ui.episode.readEpisode(id);
  else if (state.config.server && !REPLAY) void ui.episode.watchOrders();
  ui.reasoning.setStep(step);
  if (id && !inHouse && (REPLAY || !query.has("step"))) ui.reasoning.autoAdvance();
  if (!state.config.server) notice("서버 연결 없음");
  ui.house.pollHouse();
  ui.presenter.tickClock();
}

const context = {
  OWNERS, state, $, AUTO_PLAY, sleep, REPLAY, RECORDING, notice, exchange,
  defaultPath, api, QUIET_END, observe,
};
// Each viewer run owns its state and timers. Controllers call through this table after setup.
const ui = {
  surface: { revealHouseState, refreshSnapshot, refreshHouseMarkers, loadHouse, applyHouseMarkers, checkHouseBeforeShare },
};
ui.reasoning = createReasoning(context, ui);
ui.order = createOrderShare(context, ui);
ui.record = createHouseRecord(context, ui);
ui.episode = createEpisodeReader(context, ui);
// Keep the house timeline's existing render hook while the house renderer is updated separately.
ui.house = createHouseTimeline(context, Object.assign(Object.create(ui), {
  phone: { renderEnding: ui.record.render, renderPhone() {} },
}));
ui.presenter = createPresenter(context, ui);
ui.recording = createRecordingPlayback(context, ui);

boot().catch((error) => {
  notice("시연 화면을 불러오지 못했어요.");
  console.error(error);
});

ui.house.bindRoomControls();
