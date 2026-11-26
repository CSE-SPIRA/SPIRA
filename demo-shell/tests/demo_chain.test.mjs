import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import test from "node:test";
import { setImmediate as settle } from "node:timers/promises";
import { fixture, sceneFixture } from "./scene-fixture.mjs";
import { fridgeValues } from "../ui/artwork/fridge.js";
import { withSceneArtwork } from "../ui/artwork/scene.js";
import { tvValues } from "../ui/artwork/tv.js";

const house = new URL("../../simulator/spira_simulator/ui/house/", import.meta.url);
// Resolve the Simulator's public URLs to their source files for the Node test.
registerHooks({
  resolve(specifier, context, nextResolve) {
    const prefixes = ["/sim/assets/house/", "/demo/replay-house/"];
    if (specifier === "/demo/shared/vocabulary.js") specifier = prefixes[0] + "vocabulary.js";
    const prefix = prefixes.find((value) => specifier.startsWith(value));
    if (prefix) {
      const asset = specifier.slice(prefix.length);
      specifier = asset === "house.js" && globalThis.sceneRenderer
        ? "data:text/javascript,export const createHouse = (...args) => globalThis.sceneRenderer(...args); export const replaceHouseMarkers = (old, next) => old.replaceWith(next)"
        : new URL(asset, house).href;
    }
    return nextResolve(specifier, context);
  },
});
const { buildChain: makeChain, houseDevicePresentation } = await import("../ui/chain.js");
const { HOUSE_DEVICES } = await import(new URL("devices.js", house));
const buildChain = (options) => makeChain({ houseDevices: HOUSE_DEVICES, ...options });
const { HOUSE_ROOM_VIEWS, layoutHouseLabels, orientHouseCamera, projectHouseLabels } = await import(new URL("house.js", house));
const { OrthographicCamera, Vector3 } = await import(new URL("vendor/three.module.min.js", house));

const shellScenes = JSON.parse(readFileSync(
  new URL("../ui/scenes.json", import.meta.url)));
const { house: wording, cameras } = shellScenes;
const { buildMoments, closeView } = await import("../ui/scene-rules.js");
const { buildPresenterCues } = await import("../ui/presenter-cues.js");
const itemTypes = JSON.parse(readFileSync(new URL("../ui/item-types.json", import.meta.url)));
const shellHtml = readFileSync(new URL("../ui/index.html", import.meta.url), "utf8");
const shellCss = readFileSync(new URL("../ui/demo.css", import.meta.url), "utf8");

function birthday() {
  const episode = fixture("ep_9031", "episode");
  const rationale = fixture("ep_9031", "rationale");
  const card = fixture("ep_9031", "card.v1");
  const hubPlan = fixture("ep_9031", "plan.v1");
  return { episode, rationale, card, hubPlan };
}

function receipt(episode, at = episode.shared_at) {
  return { kind: "plan", plan_id: episode.episode_id, at };
}

let shellRun = 0;

async function openShell(t, query, reply, withHouse = false) {
  const elements = new Map();
  const element = () => {
    const attributes = new Map();
    const classes = new Set();
    return {
      ownerDocument: globalThis.document,
      dataset: {}, style: new Map(),
      classList: {
        toggle(name, force) { if (force) classes.add(name); else classes.delete(name); },
        contains(name) { return classes.has(name); },
      },
      children: [], append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      addEventListener(type, listener) { this[`on${type}`] = listener; },
      setAttribute(name, value) { attributes.set(name, value); },
      getAttribute(name) { return attributes.get(name); },
      removeAttribute(name) { attributes.delete(name); },
      toggleAttribute(name, force) { if (force) attributes.set(name, ""); else attributes.delete(name); },
      contains() { return false; }, replaceWith(node) { elements.set("viewer-markers", node); },
      hasChildNodes() { return true; }, querySelectorAll() { return []; }, focus() {},
    };
  };
  const byId = (id) => {
    if (!elements.has(id)) {
      const node = element();
      node.style.setProperty = node.style.set;
      node.hidden = new RegExp(`id="${id}"[^>]*\\bhidden\\b`).test(shellHtml);
      elements.set(id, node);
    }
    return elements.get(id);
  };
  const pageButtons = ["reason", "house"].map((page) => Object.assign(element(), { dataset: { page } }));
  const roomButtons = [...shellHtml.matchAll(/<button[^>]+data-room="([^"]+)"/g)]
    .map(([, room]) => Object.assign(element(), { dataset: { room } }));
  const cameraMoves = [];
  const drawn = [];
  if (withHouse) byId("world").hasChildNodes = () => byId("world").children.length > 0;
  const frameDimensions = Object.fromEntries([...shellCss.matchAll(/--stage-(width|height): (\d+)px/g)]
    .map(([, key, value]) => [key, Number(value)]));
  let resize;
  const timers = [];
  const recordings = new Map();
  const recordingPaths = new Map();
  const confirmations = [];
  const navigations = [];
  let now = 0;
  let timerId = 0;
  const globals = {
    sceneRenderer: withHouse ? (stage) => {
      stage.append({});
      return {
        resize() {}, focus(view) { cameraMoves.push(view); }, setMarkers() {}, setEntrance() {}, setPresentation() {}, clearScene() {},
        setScene(scene) { drawn.push(scene); return { ok: true }; },
      };
    } : undefined,
    document: {
      head: { insertBefore() {} },
      getElementById: byId, querySelector: element,
      createElement(tag) {
        if (tag !== "canvas") return element();
        const drawn = [];
        return {
          getContext: () => ({ fillRect() {}, fillText(text) { drawn.push(text); } }),
          toDataURL: () => "data:image/png;base64,",
          toBlob: (callback) => callback(new Blob(drawn, { type: "image/png" })),
        };
      },
      querySelectorAll: (selector) => ({
        "[data-page]": pageButtons, ".room-key [data-room]": roomButtons,
      }[selector] ?? []),
      addEventListener(type, listener) { this[`on${type}`] = listener; },
    },
    window: {
      addEventListener(event, handler) { if (event === "resize") resize = handler; },
      confirm(message) { confirmations.push(message); return true; },
    },
    location: { search: query, replace(url) { navigations.push(url); } },
    CSS: { supports: () => false },
    DOMParser: class {
      parseFromString(markup) {
        const start = markup.indexOf('<div id="viewer-markers"');
        const markerMarkup = markup.slice(start);
        const clockTag = /<time class="wall-clock" datetime="([^"]+)">([^<]*)<\/time>/g;
        const clocks = [...markerMarkup.matchAll(clockTag)].map(([, datetime, textContent]) => {
          const clock = Object.assign(element(), { textContent });
          clock.setAttribute("datetime", datetime);
          return clock;
        });
        const marker = Object.assign(element(), { id: "fridge-marker" });
        const guestArrival = /data-guest-arrival="([^"]+)"/.exec(markerMarkup)?.[1];
        const root = Object.assign(element(), {
          tagName: "DIV", attributes: [], markup,
          querySelector(selector) {
            if (selector === "#fridge-marker" && markerMarkup.includes(marker.id)) return marker;
            if (selector === "[data-guest-arrival]" && guestArrival) return { dataset: { guestArrival } };
            if (selector === "[data-signal], [data-guest-arrival], [data-device][data-changed]" &&
                (guestArrival || /data-(signal|changed)=/.test(markerMarkup))) return {};
            return null;
          },
          querySelectorAll(selector) {
            if (selector === "time.wall-clock") return clocks;
            if (selector === "[data-signal]") {
              return [...markup.matchAll(/data-signal="([^"]+)"><time datetime="([^"]+)"/g)]
                .map(([, signal, at]) => ({ dataset: { signal }, querySelector: () => ({ getAttribute: () => at }) }));
            }
            if (selector === "[data-device][data-person-at]") {
              return [...markup.matchAll(/data-device="([^"]+)" data-person-at="([^"]+)"/g)]
                .map(([, device, personAt]) => ({ dataset: { device, personAt } }));
            }
            if (selector === "[data-device][data-values]") {
              return [...markup.matchAll(/data-device="([^"]+)" data-values='([^']+)'/g)]
                .map(([, device, values]) => ({ dataset: { device, values } }));
            }
            return [];
          },
        });
        Object.defineProperty(root, "outerHTML", {
          get() {
            let index = 0;
            return markerMarkup.replace(clockTag, () => {
              const clock = clocks[index++];
              return JSON.stringify([clock.getAttribute("datetime"), clock.textContent]);
            });
          },
        });
        const wallClock = [...markup.slice(0, start).matchAll(clockTag)][0];
        return {
          getElementById: () => start < 0 ? null : root,
          querySelector: (selector) => selector === "time.wall-clock" && wallClock
            ? { getAttribute: () => wallClock[1] } : null,
        };
      }
    },
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    matchMedia: () => ({ matches: true }), requestAnimationFrame() {},
    innerWidth: 1920, innerHeight: 1080,
  };
  for (const [key, value] of Object.entries(globals)) {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, value });
    t.after(() => descriptor ? Object.defineProperty(globalThis, key, descriptor) : delete globalThis[key]);
  }
  t.mock.method(performance, "now", () => now);
  t.mock.method(globalThis, "setTimeout", (callback, ms) => {
    const id = ++timerId;
    timers.push({ id, callback, ms, at: now + ms });
    return id;
  });
  t.mock.method(globalThis, "clearTimeout", (id) => {
    const index = timers.findIndex((timer) => timer.id === id);
    if (index >= 0) timers.splice(index, 1);
  });
  t.mock.method(globalThis, "fetch", async (input, options) => {
    if (input instanceof URL && input.pathname.endsWith("/scenes.json")) return Response.json(shellScenes);
    if (input instanceof URL && input.pathname.endsWith("/item-types.json")) return Response.json(itemTypes);
    if (options?.method === "POST" && input.startsWith("/demo/api/recordings/")) {
      const batch = JSON.parse(options.body);
      const entries = recordings.get(input) ?? [];
      assert.equal(batch.offset, entries.length);
      entries.push(...batch.entries);
      recordings.set(input, entries);
      recordingPaths.set(input, batch.demo_path);
      return Response.json({ offset: entries.length });
    }
    return reply(input, options);
  });
  Object.assign(byId("frame"), { offsetWidth: frameDimensions.width, offsetHeight: frameDimensions.height });
  await import(`../ui/demo.js?test=${++shellRun}`);
  await settle();
  return {
    byId, pageButtons, roomButtons, cameraMoves, recordings, recordingPaths, drawn, confirmations, navigations,
    pressKey(key) {
      const event = { key, target: { closest: () => null }, preventDefault() { this.handled = true; } };
      document.onkeydown(event);
      assert.equal(event.handled, true);
    },
    resize(width, height) {
      Object.defineProperty(globalThis, "innerWidth", { configurable: true, value: width });
      Object.defineProperty(globalThis, "innerHeight", { configurable: true, value: height });
      resize();
      return byId("frame").style.get("--scale");
    },
    async runTimer(ms) {
      const index = timers.findIndex((timer) => timer.ms === ms);
      assert.notEqual(index, -1, `expected a ${ms}ms timer`);
      const [timer] = timers.splice(index, 1);
      now = Math.max(now, timer.at);
      timer.callback();
      await settle();
    },
    async advanceTime(ms) {
      const end = now + ms;
      for (;;) {
        const next = timers.filter(({ at }) => at <= end).sort((a, b) => a.at - b.at)[0];
        if (!next) break;
        timers.splice(timers.indexOf(next), 1);
        now = Math.max(now, next.at);
        next.callback();
        await settle();
      }
      now = end;
    },
  };
}

test("clock-only viewer changes keep the marker tree and focused fridge node", async (t) => {
  let second = 0;
  const { episode, rationale, card, hub } = sceneFixture();
  const shell = await openShell(t, "?episode=ep_9031&page=house", (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith("/ep_9031")) return Response.json(episode);
    if (path === "/demo/api/sim/viewer") return new Response(
      `<time class="wall-clock" datetime="2026-10-17T10:00:0${second}.123456+09:00">10:00</time>
      <div id="viewer-markers"><article id="fridge-marker"></article>
      <time class="wall-clock" datetime="2026-10-17T10:00:0${second}.123456+09:00">10:00:0${second}</time></div>`);
    return new Response(null, { status: 404 });
  });
  const markers = shell.byId("viewer-markers");
  const fridge = markers.querySelector("#fridge-marker");
  document.activeElement = fridge;
  const [clock] = markers.querySelectorAll("time.wall-clock");
  second++;
  await shell.runTimer(800);
  assert.ok(fridge);
  assert.equal(shell.byId("viewer-markers"), markers);
  assert.equal(markers.querySelector("#fridge-marker"), fridge);
  assert.equal(document.activeElement, fridge);
  assert.equal(clock.textContent, "10:00:01");
  assert.equal(clock.getAttribute("datetime"), "2026-10-17T10:00:01.123456+09:00");
});

test("a second share warns before sending when the World still shows guests", async (t) => {
  const { episode, facts, viewer } = sceneFixture();
  const guests = facts.find(({ event }) => event === "guest_arrived");
  assert.ok(Date.parse(guests.at) > Date.parse(episode.shared_at));
  let existing = [];
  let shares = 0;
  const checks = [];
  const shell = await openShell(t, "?auto=0", (path, options) => {
    if (path === "/demo/api/config") return Response.json({ server: true, fixture: true, household_id: "h_042" });
    if (path === "/demo/api/sim/viewer") {
      assert.equal(options.cache, "no-store");
      return new Response(viewer(existing));
    }
    if (path === "/demo/api/order") {
      checks.push(shell.byId("stale-house").hidden);
      shares++;
      return Response.json({ episode_id: shares === 1 ? episode.episode_id : episode.episode_id + "2" });
    }
    return new Response(null, { status: 404 });
  });
  assert.equal(shell.byId("stale-house").hidden, true);
  await shell.byId("next-cue").onclick();
  await settle();
  existing = [guests];
  shell.byId("orders").onclick({ target: { closest: () => ({ dataset: { order: "birthday" } }) } });
  assert.equal(shell.byId("next-cue").textContent, "다음: 공유");
  await shell.byId("next-cue").onclick();
  await settle();
  assert.deepEqual(checks, [true, false]);
  assert.equal(shell.byId("stale-house").hidden, false);
  assert.match(shellHtml, /이전 시연의 집 상태가 남아 있어요\./);
  assert.match(shellHtml, /id="reset-notice"[^>]*>새로 시작<\/button>/);
  assert.match(shellHtml, /터미널에서는 Ctrl-C 후 <code>scripts\/demo-up<\/code>을 실행하세요\./);
  assert.equal((shellHtml.match(/id="stale-house"/g) ?? []).length, 1);
});

for (const control of ["reset-drawer", "reset-notice"]) {
  test(`${control} confirms, saves the reset entry, and returns to stage 1 after readiness`, async (t) => {
    const { episode, facts, viewer } = sceneFixture();
    const guests = facts.filter(({ event }) => event === "guest_arrived");
    const reset = Promise.withResolvers();
    const requests = [];
    const shell = await openShell(t, "?auto=0", (path, options) => {
      if (path === "/demo/api/config") return Response.json({ server: true, fixture: true, reset: true, household_id: "h_042" });
      if (path === "/demo/api/sim/viewer") return new Response(viewer(guests));
      if (path === "/demo/api/order") return Response.json({ episode_id: episode.episode_id });
      if (path === "/demo/api/reset") {
        requests.push(options.method);
        const [entries] = shell.recordings.values();
        assert.deepEqual(entries.slice(-2).map(({ kind, data }) => [kind, data]), [
          ["presenter", { action: "reset" }], ["finish", { stage: "reset" }],
        ]);
        return reset.promise;
      }
      return new Response(null, { status: 404 });
    });
    await shell.byId("next-cue").onclick();
    assert.equal(shell.byId("stale-house").hidden, false);
    assert.equal(shell.byId(control).hidden, false);
    await shell.byId(control).onclick();
    assert.equal(shell.byId("reset-status").textContent, "집과 판단 기록을 처음 상태로 돌려요. 녹화는 남아요. 한 번 더 누르면 시작해요.");
    assert.equal(shell.byId(control).textContent, "한 번 더 눌러 새로 시작");
    assert.deepEqual(requests, []);
    assert.deepEqual(shell.confirmations, []);
    const pending = shell.byId(control).onclick();
    await settle();
    assert.match(shell.byId("reset-status").textContent, /돌리는 중/);
    assert.equal(shell.byId(control).textContent, "새로 시작");
    assert.equal(shell.byId("reset-drawer").disabled, true);
    assert.equal(shell.byId("reset-notice").disabled, true);
    await shell.byId(control).onclick();
    assert.deepEqual(requests, ["POST"]);
    assert.deepEqual(shell.navigations, []);
    reset.resolve(new Response(null, { status: 204 }));
    await pending;
    assert.deepEqual(shell.navigations, ["/demo"]);
  });
}

test("a failed reset shows the local scope and leaves the current page available", async (t) => {
  const requests = [];
  const shell = await openShell(t, "?auto=0", (path, options) => {
    if (path === "/demo/api/config") return Response.json({ server: true, reset: true });
    if (path === "/demo/api/reset") {
      requests.push(options.method);
      return new Response(null, { status: 503 });
    }
    return new Response(null, { status: 404 });
  });
  assert.equal(shell.byId("reset-scope").hidden, false);
  assert.match(shellHtml, /이 컴퓨터의 Hub와 집 상태만 초기화해요\./);
  await shell.byId("reset-drawer").onclick();
  assert.match(shell.byId("reset-status").textContent, /서버의 주문과 판단 기록, 녹화는 남아요\. 한 번 더 누르면 시작해요\./);
  assert.deepEqual(requests, []);
  await shell.byId("reset-drawer").onclick();
  assert.deepEqual(requests, ["POST"]);
  assert.match(shell.byId("reset-status").textContent, /새로 시작하지 못했어요/);
  assert.deepEqual(shell.navigations, []);
  assert.equal(shell.byId("reset-drawer").disabled, false);
  assert.equal(shell.byId("phone-dock").inert, false);
});

test("opening the house detects guest presence from before a story-clock rewind", async (t) => {
  const { episode, rationale, card, hub, facts, viewer } = sceneFixture();
  const guests = facts.find(({ event }) => event === "guest_arrived");
  const now = hub.ledger[0].at;
  assert.ok(Date.parse(guests.at) > Date.parse(now));
  assert.ok(Date.parse(now) >= Date.parse(episode.shared_at));
  const shell = await openShell(t, "?episode=ep_9031&page=house", (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path === "/demo/api/sim/viewer") return new Response(
      `<time class="wall-clock" datetime="${now}"></time>${viewer([guests])}`);
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith("/ep_9031")) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  assert.equal(shell.byId("home").hidden, false);
  assert.equal(shell.byId("stale-house").hidden, false);
});

test("the stage strip marks each stage done only when its own result arrives", async (t) => {
  const { episode, rationale, card, hubPlan } = birthday();
  const id = episode.episode_id;
  const detail = { ...episode, status: "reading", items: [], item_tasks: [], card_ids: [] };
  let rationaleResult;
  let cards = [];
  let ledger = [];
  const shell = await openShell(t, `?episode=${id}&step=1&auto=0`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json({ ledger });
    if (path.endsWith("/rationale")) return rationaleResult ? Response.json(rationaleResult) : new Response(null, { status: 404 });
    if (path.includes("/cards")) return Response.json({ cards });
    if (path.endsWith(id)) return Response.json(detail);
    return new Response(null, { status: 404 });
  });
  const strip = shell.byId("stage-steps").children;
  const done = () => strip.filter((node) => node.classList.contains("done")).map((node) => node.dataset.stage);
  const current = () => strip.find((node) => node.getAttribute("aria-current") === "step")?.dataset.stage;
  assert.deepEqual(strip.map(({ textContent }) => textContent), ["1 추출", "2 맥락", "3 의도", "4 할 일", "5 계획", "6 집", "7 기록"]);
  assert.equal(current(), "extract");
  assert.deepEqual(done(), []);

  detail.items = episode.items;
  await shell.runTimer(1000);
  assert.deepEqual(done(), ["extract"]);
  rationaleResult = { ...rationale, intents: [], tasks: [], item_tasks: [] };
  await shell.runTimer(1000);
  assert.deepEqual(done(), ["extract", "context"]);
  rationaleResult.intents = rationale.intents;
  await shell.runTimer(1000);
  assert.deepEqual(done(), ["extract", "context", "intent"]);
  rationaleResult.tasks = rationale.tasks;
  await shell.runTimer(1000);
  assert.deepEqual(done(), ["extract", "context", "intent", "tasks"]);
  cards = [card];
  await shell.runTimer(1000);
  assert.deepEqual(done(), ["extract", "context", "intent", "tasks", "plan"]);
  assert.equal(current(), "extract");

  ledger = [{ kind: "plan", plan_id: "ep_other", at: hubPlan.sent_at }];
  await shell.runTimer(800);
  assert.equal(strip[5].classList.contains("done"), false);
  ledger.push({ kind: "plan", plan_id: id, at: hubPlan.sent_at });
  await shell.runTimer(800);
  assert.equal(strip[5].classList.contains("done"), true);
  assert.equal(current(), "extract");
});

test("the phone and presenter toggle switch the same right area in place", async (t) => {
  const { episode, rationale, card, hubPlan } = birthday();
  card.notify = false;
  let receiptAt = new Date(Date.parse(episode.shared_at) - 1000).toISOString();
  const shell = await openShell(t, `?episode=${episode.episode_id}&step=5`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json({ ledger: [receipt(episode, receiptAt)] });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  assert.match(shellHtml, /id="phone-dock"[\s\S]*<\/aside>\s*<div id="right-area">[\s\S]*id="stage-steps"[\s\S]*id="reason"[\s\S]*id="home"[\s\S]*<\/section>\s*<\/div>\s*<\/main>/);
  assert.equal((shellHtml.match(/id="phone-dock"/g) ?? []).length, 1);
  const current = () => shell.byId("stage-steps").children.find((node) => node.getAttribute("aria-current") === "step");
  const view = () => [shell.byId("reason").hidden, shell.byId("home").hidden, current().dataset.stage];
  assert.deepEqual(view(), [false, true, "plan"]);
  assert.equal(shell.byId("phone-map").disabled, true);
  assert.equal(shell.pageButtons[1].disabled, true);
  assert.equal(shell.byId("stage-steps").children[5].classList.contains("done"), false);
  shell.byId("phone-map").onclick();
  shell.pageButtons[1].onclick();
  assert.deepEqual(view(), [false, true, "plan"]);
  receiptAt = hubPlan.sent_at;
  await shell.runTimer(800);
  assert.equal(shell.byId("phone-map").getAttribute("data-expected"), "");
  shell.byId("phone-map").onclick();
  assert.deepEqual(view(), [true, false, "hub"]);
  assert.equal(current().classList.contains("done"), true);
  assert.equal(shell.byId("phone-map").getAttribute("aria-pressed"), "true");
  assert.match(shell.byId("phone-content").innerHTML, /우리 집/);
  const [judgment, house] = shell.pageButtons;
  judgment.onclick();
  assert.deepEqual(view(), [false, true, "plan"]);
  house.onclick();
  assert.deepEqual(view(), [true, false, "hub"]);
});

test("the desktop frame fits the two projector viewports without changing the stage layout", async (t) => {
  const shell = await openShell(t, "?auto=0", (path) => {
    if (path === "/demo/api/config") return Response.json({ server: false });
    return new Response(null, { status: 404 });
  });
  assert.equal(shell.resize(1920, 1080), 1);
  assert.equal(shell.resize(1440, 900), 0.75);
  assert.match(shellCss, /body\{overflow:hidden/);
  assert.doesNotMatch(shellCss.match(/#stage-copy\{[^}]+\}/)[0], /overflow/);
});

test("the phone highlights sharing and the presenter helper explains why it waits", async (t) => {
  const shares = [];
  const detail = Promise.withResolvers();
  const episode = fixture("ep_9150", "episode");
  const rationale = fixture("ep_9150", "rationale");
  const shell = await openShell(t, "?auto=0", (path, options) => {
    if (path === "/demo/api/config") return Response.json({ server: true, fixture: true, household_id: "h_042" });
    if (path === "/demo/api/order") {
      shares.push(options.body);
      return Response.json({ episode_id: episode.episode_id, status: "received" });
    }
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.endsWith("/cards")) return Response.json({ cards: [] });
    if (path.endsWith(episode.episode_id)) return detail.promise;
    return new Response(null, { status: 404 });
  });
  assert.equal(shell.byId("next").disabled, true);
  assert.equal(shell.byId("orders").hidden, false);
  assert.equal(shell.byId("next-share").hidden, false);
  assert.match(shell.byId("phone-content").innerHTML, /id="sample" data-expected/);
  assert.match(shellHtml, /먼저 주문을 공유해 주세요/);
  shell.byId("next").onclick();
  await settle();
  assert.equal(shares.length, 0);
  shell.byId("orders").onclick({ target: { closest: () => ({ dataset: { order: "groceries" } }) } });
  await shell.byId("sample").onclick();
  await settle();
  assert.equal(shares.length, 1);
  assert.equal(shares[0].get("sample"), "groceries");
  assert.match(await shares[0].get("images").text(), /우유 1L/);
  assert.equal(shell.byId("next-share").hidden, true);
  assert.match(shell.byId("phone-content").innerHTML, /주문을 보냈어요/);
  detail.resolve(Response.json(episode));
  await settle();
  assert.equal(shell.byId("next").disabled, false);
  assert.match(shell.byId("phone-content").innerHTML, /주문을 읽었어요/);
});

test("a real Server run shows missing stages and uses its own card and Hub receipt", async (t) => {
  const id = "ep_123";
  const household = "h_123";
  const base = birthday().card;
  const liveCard = { ...base, episode_id: id, card_id: "nc_123",
    lines: [{ ...base.lines[0], text: "서버가 보낸 준비" }] };
  const ledger = [{ kind: "plan", plan_id: id, plan_version: 1, at: liveCard.updated_at }];
  const writes = [];
  const shell = await openShell(t, "?auto=0", (path, options) => {
    if (options?.method === "POST") writes.push(path);
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: household });
    if (path === "/demo/api/hub") return Response.json({ ledger });
    if (path === "/demo/api/sim/viewer") {
      return new Response(`<div id="viewer-markers"><div data-signal="empty"><time datetime="${liveCard.updated_at}"></time></div></div>`);
    }
    if (path === "/demo/api/order") {
      assert.deepEqual([...options.body.keys()], ["images"]);
      return Response.json({ episode_id: id, status: "received" }, { status: 202 });
    }
    if (path.startsWith(`/demo/api/server/v1/households/${household}/cards`)) return Response.json({ cards: [liveCard] });
    return new Response(null, { status: 404 });
  });
  assert.equal(shell.byId("orders").hidden, true);
  assert.doesNotMatch(shell.byId("phone-content").innerHTML, /예시 주문|scan-picture/);
  shell.byId("files").onchange({ target: { files: [new File(["real order"], "order.png", { type: "image/png" })] } });
  await settle();

  for (const stage of ["extract", "context", "intent", "tasks"]) {
    shell.byId("next").onclick();
    assert.equal(shell.byId("reason-layout").dataset.stage, stage);
    assert.match(shell.byId("stage-copy").innerHTML, /서버가 아직 이 단계를 내보내지 않아요/);
    assert.doesNotMatch(shell.byId("stage-beat").textContent, /기다려요/);
  }
  shell.byId("card-notification").onclick();
  await shell.runTimer(800);
  assert.equal(shell.byId("reason-layout").dataset.stage, "plan");
  assert.match(shell.byId("stage-copy").innerHTML, /서버가 보낸 준비/);
  assert.equal(shell.byId("phone-map").disabled, false);
  shell.byId("phone-map").onclick();
  assert.equal(shell.byId("home").hidden, false);
  assert.equal(shell.byId("presenter-clock").hidden, true);
  assert.equal(shell.byId("clock-unavailable").hidden, false);
  shell.byId("presenter-controls").onclick({ target: { closest: () => ({ dataset: { presenter: "clock" } }) } });
  await settle();
  assert.deepEqual(writes, ["/demo/api/order"]);
  shell.byId("next").onclick();
  shell.byId("next").onclick();
  await settle();
  assert.equal(shell.byId("reason-layout").dataset.stage, "record");
  assert.match(shell.byId("stage-copy").innerHTML, /서버가 아직 이 단계를 내보내지 않아요/);
});

test("opt-in live playback dwells on each ready stage and waits for a notification tap", async (t) => {
  const { episode, rationale, card } = birthday();
  episode.status = "notified";
  const { episode_id: id } = episode;
  const plan = { kind: "plan", plan_id: id, plan_version: 1, previous_version: null, at: card.updated_at,
    reports: [{ kind: "ack", delivered: true }], ack: { status: "admitted", rejected_tasks: [] } };
  let upload;
  const shell = await openShell(t, "?auto=1", (path, options) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/order") {
      upload = options.body;
      return Response.json({ episode_id: id, status: "received" }, { status: 202 });
    }
    if (path === "/demo/api/hub") return Response.json({ ledger: [plan] });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  shell.byId("files").onchange({ target: { files: [new File(["order image"], "order.png", { type: "image/png" })] } });
  await settle();
  assert.equal(shell.byId("next").disabled, false, shell.byId("notice").textContent);
  assert.deepEqual([...upload.keys()], ["images"]);
  const stage = () => shell.byId("reason-layout").dataset.stage;
  assert.equal(stage(), "share");
  assert.equal(shell.byId("orders").hidden, true);
  assert.equal(shell.byId("phone-map").disabled, true);
  assert.doesNotMatch(shell.byId("phone-content").innerHTML, /준비 카드 알림/);
  const beat = () => shell.byId("stage-beat").textContent;
  const pane = (id) => shell.byId(`judgment-${id}`);
  await shell.runTimer(3000);
  assert.equal(stage(), "extract");
  assert.match(beat(), /물건 9종 읽음/);
  assert.doesNotMatch(beat(), /평소|일정|의도/);
  assert.equal(pane("calendar").hidden, true);
  await shell.runTimer(2200);
  assert.equal(stage(), "context");
  assert.match(beat(), /평소와 다른 물건 7종/);
  assert.equal(pane("calendar").hidden, true);
  await shell.runTimer(1600);
  assert.match(pane("calendar").innerHTML, /토 14:00–17:00 · 2일 뒤/);
  assert.doesNotMatch(pane("calendar").innerHTML, /판단에 사용/);
  assert.equal(pane("similar").hidden, true);
  await shell.runTimer(1600);
  assert.match(beat(), /비슷한 다른 집 주문 12건/);
  assert.match(pane("similar").innerHTML, /6개 중 4개 같음/);
  assert.equal(pane("slots").hidden, true);
  await shell.runTimer(1600);
  assert.equal(stage(), "intent");
  assert.match(pane("calendar").innerHTML, /판단에 사용[\s\S]*케이크 토퍼/);
  assert.doesNotMatch(pane("calendar").innerHTML, /가족 모임/);
  assert.match(pane("slots").innerHTML, /가구 유형/);
  assert.equal(pane("intent").hidden, true);
  await shell.runTimer(1600);
  for (const id of ["items", "calendar", "similar"]) assert.equal(pane(id).hidden, true);
  assert.equal(pane("slots").hidden, false);
  assert.match(pane("intent").innerHTML, /디즈니 공주[\s\S]*준비와 따로 본 물건[\s\S]*세탁 세제/);
  assert.doesNotMatch(shell.byId("phone-content").innerHTML, /준비 카드 알림/);
  await shell.runTimer(1600);
  assert.equal(stage(), "tasks");
  assert.match(beat(), /할 일 4개 · 냉장고 안내 2개/);
  assert.match(shell.byId("phone-content").innerHTML, /id="card-notification" data-expected>\s*준비 카드 알림/);
  assert.equal(shell.byId("next").disabled, true);

  shell.byId("card-notification").onclick();
  assert.equal(stage(), "tasks");
  await shell.runTimer(3000);
  assert.equal(stage(), "plan");
  for (const { text } of card.lines) assert.ok(shell.byId("stage-copy").innerHTML.includes(text));
  assert.match(shell.byId("phone-content").innerHTML, /data-reaction="line_off"/);
  assert.doesNotMatch(shell.byId("phone-content").innerHTML, /준비 카드 알림/);
  assert.equal(shell.byId("phone-map").disabled, true);
  await shell.runTimer(800);
  assert.equal(shell.byId("phone-map").disabled, false);
  assert.equal(stage(), "plan");
  assert.equal(shell.byId("next").disabled, true);
  shell.byId("phone-map").onclick();
  assert.equal(shell.byId("home").hidden, false);
  assert.match(shell.byId("phone-content").innerHTML, /우리 집/);
});

test("the live cue waits for intent and tasks without queuing presses", async (t) => {
  const { episode, rationale } = birthday();
  const id = episode.episode_id;
  const reading = { ...episode, status: "reading", card_ids: [], item_tasks: [] };
  const evidence = { ...rationale, intents: [], tasks: [], item_tasks: [], unbundled: [] };
  let payload = null;
  let detail = reading;
  const shell = await openShell(t, `?episode=${id}&auto=0`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, fixture: true, household_id: "h_042" });
    if (path.endsWith("/rationale")) return payload ? Response.json(payload) : new Response(null, { status: 404 });
    if (path.includes("/cards")) return Response.json({ cards: [] });
    if (path.endsWith(id)) return Response.json(detail);
    return new Response(null, { status: 404 });
  });
  const next = shell.byId("next-cue");
  shell.pressKey("ArrowRight");
  assert.equal(next.textContent, "대기 · 2 맥락");
  assert.equal(next.disabled, true);
  assert.equal(shell.byId("judgment-calendar").hidden, true);
  payload = evidence;
  await shell.runTimer(1000);
  assert.equal(shell.byId("reason-layout").dataset.stage, "extract");
  shell.pressKey("ArrowRight");
  shell.pressKey(" ");
  await next.onclick();
  assert.equal(next.textContent, "대기 · 3 의도");
  assert.equal(next.disabled, true);
  assert.match(shell.byId("stage-beat").textContent, /비슷한 다른 집 주문 12건/);
  assert.doesNotMatch(shell.byId("judgment-calendar").innerHTML, /판단에 사용/);
  assert.equal(shell.byId("judgment-slots").hidden, true);

  shell.pressKey(" ");
  payload = { ...rationale, tasks: [], item_tasks: [] };
  await shell.runTimer(1000);
  assert.equal(shell.byId("reason-layout").dataset.stage, "context");
  await next.onclick();
  assert.match(shell.byId("judgment-calendar").innerHTML, /판단에 사용/);
  assert.equal(shell.byId("judgment-intent").hidden, true);
  await next.onclick();
  assert.equal(next.textContent, "대기 · 4 할 일");
  assert.equal(next.disabled, true);
  assert.equal(shell.byId("judgment-intent").hidden, false);

  shell.pressKey("ArrowRight");
  payload = rationale;
  detail = { ...episode, status: "judged" };
  await shell.runTimer(1000);
  assert.equal(shell.byId("reason-layout").dataset.stage, "intent");
  await next.onclick();
  assert.equal(shell.byId("reason-layout").dataset.stage, "tasks");
  assert.match(shell.byId("stage-beat").textContent, /할 일 4/);
});

test("an out-of-order burst waits for extraction and then preserves every live beat", async (t) => {
  const { episode, rationale, card } = birthday();
  const id = episode.episode_id;
  const detail = Promise.withResolvers();
  const shell = await openShell(t, `?episode=${id}&auto=1`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, household_id: "h_042" });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(id)) return detail.promise;
    return new Response(null, { status: 404 });
  });
  const stage = () => shell.byId("reason-layout").dataset.stage;
  assert.equal(stage(), "share");
  assert.ok(shell.byId("stage-steps").children.every((step) => !step.classList.contains("done")));
  await shell.runTimer(3000);
  assert.match(shell.byId("stage-beat").textContent, /추출을 기다려요/);
  detail.resolve(Response.json(episode));
  await settle();
  for (const [dwell, expected] of [[120, "extract"], [2200, "context"], [1600, "context"],
    [1600, "context"], [1600, "intent"], [1600, "intent"], [1600, "tasks"]]) {
    await shell.runTimer(dwell);
    assert.equal(stage(), expected);
  }
  assert.match(shell.byId("phone-content").innerHTML, /준비 카드 열기|준비 카드 알림/);
});

test("a new live share clears old data and records arrivals across a 503 and a timeout", async (t) => {
  const previous = birthday();
  const nextId = "ep_9150";
  const episode = fixture(nextId, "episode");
  const rationale = fixture(nextId, "rationale");
  const { episode_id: oldId } = previous.episode;
  let reads = 0;
  const shell = await openShell(t, `?episode=${oldId}&auto=0`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, household_id: "h_042" });
    if (path === "/demo/api/order") return Response.json({ episode_id: nextId, status: "received" }, { status: 202 });
    if (path.endsWith(oldId)) return Response.json(previous.episode);
    if (path.endsWith(`${oldId}/rationale`)) return Response.json(previous.rationale);
    if (path.includes("/cards")) return Response.json({ cards: [previous.card] });
    if (path.endsWith(nextId)) return Response.json(episode);
    if (path.endsWith(`${nextId}/rationale`)) {
      if (++reads === 1) return new Response(null, { status: 503 });
      if (reads === 2) throw new DOMException("timeout", "TimeoutError");
      return Response.json(rationale);
    }
    return new Response(null, { status: 404 });
  });
  assert.match(shell.byId("phone-content").innerHTML, /케이크 토퍼/);
  shell.byId("files").onchange({ target: { files: [new File(["order image"], "order.png", { type: "image/png" })] } });
  await settle();
  shell.byId("next").onclick();
  assert.match(shell.byId("stage-beat").textContent, /맥락을 기다려요 · 0초.*연결을 다시 확인해요/);
  assert.doesNotMatch(shell.byId("phone-content").innerHTML, /케이크 토퍼/);
  assert.equal(shell.byId("judgment-calendar").hidden, true);
  await shell.runTimer(1000);
  assert.match(shell.byId("stage-beat").textContent, /맥락을 기다려요 · 1초/);
  await shell.runTimer(1000);
  assert.equal(reads, 3);
  shell.byId("next").onclick();
  assert.equal(shell.byId("reason-layout").dataset.stage, "context");
  const run = [...shell.recordings.values()].find((entries) => entries.some(({ kind }) => kind === "share"));
  assert.equal(run[0].data.episode_id, nextId);
  assert.ok(run.every(({ arrived_at, story_at }) => Date.parse(arrived_at) && Date.parse(story_at)));
  assert.ok(run.some(({ kind, data }) => kind === "rationale" && data.episode_id === nextId));
  assert.ok(run.filter(({ kind }) => kind === "cards").every(({ data }) => !data.cards.length));
});

test("the h_051 held recording reaches its card with no rationale available", async (t) => {
  const id = "ep_9120";
  const card = fixture(id, "card.held");
  const plan = fixture(id, "plan.v1");
  const episode = { episode_id: id, household_id: "h_051", shared_at: plan.sent_at, status: "held",
    items: [], item_count: 0, masked_count: 0, item_tasks: [], card_ids: [card.card_id] };
  const shell = await openShell(t, `?episode=${id}&replay=1&auto=1`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, fixture: true, household_id: "h_051" });
    if (path.includes("/households/h_051/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  await shell.runTimer(3000);
  assert.match(shell.byId("judgment-items-heading").textContent, /저장된 판단 근거가 없어요/);
  assert.equal(shell.byId("stage-beat").textContent, "");
  await shell.runTimer(2200);
  assert.equal(shell.byId("reason-layout").dataset.stage, "plan");
  assert.match(shell.byId("stage-copy").innerHTML, /손님 오기 전 거실 청소/);
  assert.match(shell.byId("stage-copy").innerHTML, /시간을 기다리는 중/);
});

test("the phone shows a line-on conflict and Stop waits for the card poll", async (t) => {
  const { episode, rationale, card } = birthday();
  const clean = card.lines[0];
  clean.state = "off";
  clean.checked = false;
  card.notify = false;
  episode.status = "notified";
  rationale.executions = [];
  const stopPoll = Promise.withResolvers();
  const lineConflict = Promise.withResolvers();
  const reactions = [];
  let stopped = false;
  const shell = await openShell(t, `?episode=${episode.episode_id}&step=5`, (path, options) => {
    if (path === "/demo/api/config") return Response.json({ server: true, household_id: "h_042" });
    if (path === "/demo/api/reaction") {
      const request = JSON.parse(options.body);
      reactions.push(request);
      if (request.reaction === "line_on") return lineConflict.promise;
      stopped = true;
      return Response.json({ ...card, stopped });
    }
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return stopped ? stopPoll.promise : Response.json({ cards: [card] });
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const tap = (reaction, task) => shell.byId("phone-content").onclick({
    target: { closest: () => ({ dataset: { card: card.card_id, reaction, task } }) },
  });
  const phone = () => shell.byId("phone-content").innerHTML;
  assert.match(phone(), /data-reaction="line_on"/);
  const turningOn = tap("line_on", clean.task_id);
  assert.match(phone(), /확인 중/);
  lineConflict.resolve(Response.json({ code: "line_started" }, { status: 409 }));
  await turningOn;
  assert.match(phone(), /이미 시작된 항목은 켤 수 없어요/);
  assert.doesNotMatch(phone(), /data-reaction="line_on"/);
  await tap("line_on", clean.task_id);
  assert.equal(reactions.length, 1);

  const stopping = tap("stop");
  await settle();
  assert.deepEqual(reactions[1], { card_id: card.card_id, reaction: "stop" });
  assert.match(phone(), /중지 확인 중/);
  stopPoll.resolve(Response.json({ cards: [{ ...card, stopped, buttons: [], updated_at: "2026-10-17T14:00:00+09:00" }] }));
  await stopping;
  assert.doesNotMatch(phone(), /data-reaction="stop"/);
});

test("the fixture fast-forwards the quiet window once for the active shared order", async (t) => {
  const { episode } = birthday();
  episode.status = "reading";
  const { episode_id: id } = episode;
  const quietEnd = new Date(Date.parse(episode.shared_at) + 600000).toISOString();
  const clock = { version: 1, real_at: episode.shared_at, story_at: episode.shared_at, rate: 1 };
  t.mock.method(Date, "now", () => Date.parse(episode.shared_at));
  const advances = [];
  const shell = await openShell(t, `?episode=${id}&auto=0`, (path, options) => {
    if (path === "/demo/api/config") return Response.json({ server: true, fixture: true, household_id: "h_042" });
    if (path.endsWith("/demo/clock")) return Response.json(clock);
    if (path.endsWith("/demo/moments")) return Response.json([
      { episode_id: id, kind: "time", event: "judgment.quiet_end", at: quietEnd },
    ]);
    if (path === "/demo/api/clock") {
      advances.push(JSON.parse(options.body));
      return Response.json(clock);
    }
    if (path.includes("/cards")) return Response.json({ cards: [] });
    if (path.endsWith(id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  await shell.runTimer(1000);
  await shell.runTimer(1000);
  assert.deepEqual(advances, [{ advance_to: quietEnd, over_seconds: 4 }]);
});

for (const missing of [404, 405, 501]) {
  test(`the shell stops reading the clock after HTTP ${missing} and retries transient errors`, async (t) => {
    let reads = 0;
    const frame = {
      version: 1, story_at: "2026-10-17T05:00:00Z", real_at: new Date().toISOString(), rate: 1,
    };
    const shell = await openShell(t, "?step=2", (path) => {
      if (path === "/demo/api/config") return Response.json({ server: true, fixture: false });
      if (path === "/demo/api/server/v1/demo/moments") return Response.json([]);
      assert.equal(path, "/demo/api/server/v1/demo/clock");
      switch (++reads) {
        case 1: return new Response(null, { status: 503 });
        case 2: throw new Error("404");
        case 3: return Response.json(frame);
        default: return new Response(null, { status: missing });
      }
    });
    assert.equal(reads, 1);
    for (let expected = 2; expected <= 4; expected++) {
      await shell.runTimer(800);
      assert.equal(reads, expected);
    }
    await shell.runTimer(800);
    assert.equal(reads, 4);
    assert.equal(shell.byId("clock-unavailable").hidden, false);
    assert.equal(shell.byId("presenter-clock").hidden, true);
  });
}

test("the live server advances its published moment through the next route", async (t) => {
  const { episode, rationale, card } = birthday();
  const { episode_id: id } = episode;
  const clock = { version: 1, real_at: episode.shared_at, story_at: episode.shared_at, rate: 1 };
  const moment = { episode_id: id, id: "guest-window", kind: "time", at: card.starts_at };
  const writes = [];
  t.mock.method(Date, "now", () => Date.parse(episode.shared_at));
  const shell = await openShell(t, `?episode=${id}&page=house&auto=0`, (path, options) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json({ ledger: [receipt(episode)] });
    if (path === "/demo/api/server/v1/demo/clock") return Response.json(clock);
    if (path.startsWith("/demo/api/server/v1/demo/moments")) return Response.json([moment]);
    if (options?.method === "POST") {
      writes.push([path, JSON.parse(options.body)]);
      return Response.json(moment);
    }
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  assert.equal(shell.byId("presenter-clock").hidden, false);
  assert.equal(shell.byId("clock-unavailable").hidden, true);
  shell.byId("presenter-controls").onclick({ target: { closest: () => ({ dataset: { presenter: "clock" } }) } });
  await settle();
  assert.deepEqual(writes, [[`/demo/api/clock/next?episode_id=${id}`, { over_seconds: 4 }]]);
});

test("clock advances visit and record timed moments when Hub read-backs arrive", async (t) => {
  const { episode, rationale, hub, facts, viewer, devices, relations } = sceneFixture();
  const { episode_id: id } = episode;
  const { card } = birthday();
  const delivered = facts.find(({ event }) => event === "package.brought_in");
  const clean = relations["t_clean#1"];
  const safe = relations["t_safe#2"];
  const safetyReadBack = safe.observed;
  safe.observed = [];
  relations["t_oven#4"].observed = [];
  const moments = [clean, safe].map(({ trigger }) => ({ at: trigger.time, kind: "time" }));
  const start = delivered.at;
  let clock = { version: 1, real_at: start, story_at: start, rate: 1 };
  t.mock.method(Date, "now", () => Date.parse(start));
  const writes = [];
  const visible = [];
  const shell = await openShell(t, `?episode=${id}&page=house&auto=0`, (path, options) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, fixture: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path === "/demo/api/sim/viewer") return new Response(viewer(visible));
    if (path === "/demo/api/sim/snapshot") return Response.json({ devices });
    if (path.endsWith("/demo/clock")) return Response.json(clock);
    if (path.endsWith("/demo/moments")) return Response.json(moments);
    if (path === "/demo/api/clock") {
      const { advance_to } = JSON.parse(options.body);
      writes.push(advance_to);
      clock = { ...clock, version: clock.version + 1, story_at: advance_to };
      return Response.json(clock);
    }
    if (path === "/demo/api/home/delivery") {
      visible.push(delivered);
      return Response.json({ occurred_at: delivered.at });
    }
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  }, true);
  const press = (presenter, event) => shell.byId("presenter-controls").onclick({
    target: { closest: () => ({ dataset: { presenter, event } }) },
  });
  press("delivery", delivered.event);
  await settle();
  assert.equal(shell.byId("home-title").textContent, "택배 들여옴");

  const advance = async (at) => {
    press("clock");
    await settle();
    assert.equal(writes.at(-1), new Date(Date.parse(at) - 5000).toISOString());
    await shell.runTimer(4300);
    clock = { ...clock, story_at: new Date(Date.parse(at) + 10000).toISOString() };
    await shell.runTimer(800);
  };
  await advance(clean.trigger.time);
  assert.equal(shell.byId("home-title").textContent, "택배 들여옴");
  assert.match(shell.byId("timeline").innerHTML, /12:30<\/time>\s*<span>[^<]+<\/span><small>대기/);
  clean.observed = [{
    device: "cleaner_01", cmd: "clean", at: "2026-10-17T12:30:00.038918+09:00",
    values: { job_status: "running" }, revisions: { job_status: "1" },
  }];
  await shell.runTimer(800);
  assert.equal(shell.byId("home-time").textContent, "토 12:30");
  assert.doesNotMatch(shell.byId("timeline").innerHTML, /12:30<\/time>\s*<span>[^<]+<\/span><small>대기/);

  await advance(safe.trigger.time);
  assert.equal(shell.byId("home-time").textContent, "토 12:30");
  safe.observed = safetyReadBack;
  await shell.runTimer(800);
  assert.equal(shell.byId("home-time").textContent, "토 13:30");
  assert.doesNotMatch(shell.byId("timeline").innerHTML, /13:30<\/time>\s*<span>[^<]+<\/span><small>대기/);
  await shell.runTimer(800);
  const recorded = [...shell.recordings.values()][0];
  assert.deepEqual(recorded.filter(({ kind }) => kind === "house").map(({ data }) => data.moment.id),
    ["plan", `event:${delivered.event}:${Date.parse(delivered.at)}`, "line:t_clean#1", "line:t_safe#2"]);
  assert.deepEqual(shell.drawn.slice(-2).map(({ moment }) => moment), ["line:t_clean#1", "line:t_safe#2"]);
});

function birthdayCues() {
  const input = sceneFixture();
  const { episode, rationale, ledger, actions, relations } = input;
  const { card } = birthday();
  const chain = buildChain({ episode, rationale, card, hubLedger: ledger, hubPlan: actions });
  const timeline = buildMoments({ chain, wording, relations, actions });
  const guestWindows = { "t_mood#3": relations["t_mood#3"].trigger.window };
  const published = [...input.facts.map(({ event, at }) => ({ event, at })),
    { kind: "time", event: "judgment.quiet_end", at: "2026-10-15T21:10:08+09:00" },
    { kind: "time", at: "2026-10-17T13:40:00+09:00" }];
  return { ...input, card, chain, timeline, guestWindows, published };
}

test("the birthday cues use the card and Hub plan and skip clock stops without scenes", () => {
  const cues = buildPresenterCues({ ...birthdayCues(), path: "house", clock: true });
  assert.deepEqual(cues.map(({ label }) => label), [
    "공유", "준비 카드", "우리 집", "택배 들이기", "12:30", "13:30", "손님 맞이", "14:00", "17:50 일정 끝내기", "7 기록",
  ]);
});

test("without a clock, timed cues are absent and the schedule end still gates the event", () => {
  const cues = buildPresenterCues({ ...birthdayCues(), path: "house", clock: false });
  assert.deepEqual(cues.map(({ label }) => label), [
    "공유", "준비 카드", "우리 집", "택배 들이기", "손님 맞이", "일정 끝내기", "7 기록",
  ]);
  assert.equal(cues.find(({ id }) => id === "event_end").target, Date.parse("2026-10-17T17:00:00+09:00"));
});

test("cue keys send once, wait for observations and reach the scheduled time before ending", async (t) => {
  const { episode, rationale, card, hub, facts, viewer, devices, relations, published } = birthdayCues();
  const { episode_id: id } = episode;
  const start = episode.shared_at;
  let clock = { version: 1, real_at: start, story_at: start, rate: 1 };
  t.mock.method(Date, "now", () => Date.parse(start));
  const commands = [];
  const visible = [];
  const delivery = Promise.withResolvers();
  const [delivered, guests, , end] = facts;
  const observations = Object.fromEntries(Object.entries(relations).map(([id, line]) => [id, line.observed]));
  observations["t_clean#1"] = [{
    device: "cleaner_01", cmd: "clean", at: relations["t_clean#1"].trigger.time,
    values: { job_status: "running" }, revisions: { job_status: "1" },
  }];
  for (const id of ["t_clean#1", "t_safe#2", "t_mood#3", "t_oven#4"]) relations[id].observed = [];
  const shell = await openShell(t, `?episode=${id}&page=house&auto=0`, (path, options) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, fixture: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path === "/demo/api/sim/viewer") return new Response(viewer(visible));
    if (path === "/demo/api/sim/snapshot") return Response.json({ devices });
    if (path.endsWith("/demo/clock")) return Response.json(clock);
    if (path.endsWith("/demo/moments")) return Response.json(published);
    if (path === "/demo/api/clock") {
      const { advance_to } = JSON.parse(options.body);
      commands.push(advance_to);
      clock = { ...clock, version: clock.version + 1, story_at: advance_to };
      return Response.json(clock);
    }
    if (path.startsWith("/demo/api/home/")) {
      commands.push(path.split("/").at(-1));
      if (path.endsWith("/delivery")) return delivery.promise;
      const fact = path.endsWith("/event_end") ? end : guests;
      assert.ok(Date.parse(clock.story_at) >= Date.parse(fact.at));
      visible.push(fact);
      return Response.json({ occurred_at: fact.at });
    }
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const cue = shell.byId("next-cue");
  await shell.runTimer(800);
  assert.equal(cue.textContent, "다음: 택배 들이기");
  shell.pressKey(" ");
  shell.pressKey("ArrowRight");
  await settle();
  assert.match(cue.textContent, /대기 · 택배 들이기 결과/);
  assert.equal(cue.disabled, true);
  delivery.resolve(Response.json({ applied: true }));
  await settle();
  shell.pressKey("ArrowRight");
  await settle();
  assert.deepEqual(commands, ["delivery"]);
  visible.push(delivered);
  await shell.runTimer(800);

  async function cueAt(label, at) {
    assert.equal(cue.textContent, `다음: ${label}`);
    shell.pressKey("ArrowRight");
    await settle();
    assert.equal(commands.at(-1), new Date(at).toISOString());
    assert.equal(cue.disabled, true);
    await shell.runTimer(4300);
  }
  async function timedLine(label, id) {
    const { trigger } = relations[id];
    await cueAt(label, trigger.time);
    assert.equal(cue.textContent, `대기 · ${label} 기기 상태`);
    const count = commands.length;
    shell.pressKey(" ");
    await settle();
    assert.equal(commands.length, count);
    relations[id].observed = observations[id];
    await shell.runTimer(800);
  }
  await timedLine("12:30", "t_clean#1");
  await timedLine("13:30", "t_safe#2");
  await cueAt("손님 맞이", guests.at);
  assert.equal(commands.at(-1), "guests_arrive");
  assert.equal(cue.disabled, true);
  relations["t_mood#3"].observed = observations["t_mood#3"];
  await shell.runTimer(800);
  await timedLine("14:00", "t_oven#4");
  // The party scene is still on the TV, so the end waits for the restore.
  const tv = observations["t_mood#3"].find(({ cmd }) => cmd === "play_mood");
  const display = devices.find(({ logical_id }) => logical_id === tv.device);
  display.values = { ...tv.values };
  await cueAt("17:50 일정 끝내기", end.at);
  assert.equal(cue.textContent, "대기 · 17:50 일정 끝내기 결과");
  display.values = { play_mood: null };
  await shell.runTimer(800);
  assert.deepEqual(commands, [
    "delivery", ...["t_clean#1", "t_safe#2"].map((id) => new Date(relations[id].trigger.time).toISOString()),
    new Date(guests.at).toISOString(), "guests_arrive", new Date(relations["t_oven#4"].trigger.time).toISOString(),
    new Date(end.at).toISOString(), "event_end",
  ]);
  assert.equal(cue.textContent, "다음: 7 기록");
  shell.pressKey("ArrowLeft");
  assert.equal(cue.textContent, "다음: 17:50 일정 끝내기");
  await cue.onclick();
  assert.equal(cue.textContent, "다음: 7 기록");
  assert.equal(commands.filter((command) => command === "event_end").length, 1);
  await cue.onclick();
  assert.match(cue.textContent, /대기 · 관찰 결과와 이 집의 기억/);
  assert.equal(cue.disabled, true);
  await settle();
});

test("the next cue shares once, opens the card and enters the observed house", async (t) => {
  const { episode, rationale, card, hub, viewer, devices } = birthdayCues();
  const share = Promise.withResolvers();
  let shares = 0;
  const shell = await openShell(t, "", (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, fixture: true, household_id: "h_042" });
    if (path === "/demo/api/order") {
      shares++;
      return share.promise;
    }
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path === "/demo/api/sim/viewer") return new Response(viewer([]));
    if (path === "/demo/api/sim/snapshot") return Response.json({ devices });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const cue = shell.byId("next-cue");
  assert.equal(cue.textContent, "다음: 공유");
  const started = cue.onclick();
  shell.pressKey(" ");
  assert.equal(cue.textContent, "대기 · 주문 접수");
  share.resolve(Response.json({ episode_id: episode.episode_id }));
  await started;
  await settle();
  assert.equal(shares, 1);
  const stage = () => shell.byId("reason-layout").dataset.stage;
  assert.equal(cue.disabled, false);
  assert.equal(cue.textContent, "다음: 1 추출");
  await shell.advanceTime(15000);
  assert.equal(stage(), "share");
  assert.equal(cue.textContent, "다음: 1 추출");

  const progression = [
    ["1 추출", "extract", /물건 9종 읽음/],
    ["2 맥락", "context", /평소와 다른 물건/],
    ["2 맥락", "context", /일정/],
    ["2 맥락", "context", /비슷한 다른 집 주문/],
    ["3 의도", "intent", /상황/],
    ["3 의도", "intent", /의도/],
    ["4 할 일", "tasks", /할 일 4개/],
  ];
  for (const [i, [label, step, beat]] of progression.entries()) {
    assert.equal(cue.textContent, `다음: ${label}`);
    if (i % 3 === 0) shell.pressKey("ArrowRight");
    else if (i % 3 === 1) shell.pressKey(" ");
    else await cue.onclick();
    assert.equal(stage(), step);
    assert.match(shell.byId("stage-beat").textContent, beat);
  }
  assert.equal(cue.textContent, "다음: 준비 카드");
  await cue.onclick();
  assert.equal(stage(), "plan");
  assert.match(shell.byId("phone-content").innerHTML, /손님 오기 전 거실 청소/);
  await shell.advanceTime(5000);
  assert.equal(stage(), "plan");
  assert.equal(shell.byId("home").hidden, true);
  assert.equal(cue.textContent, "다음: 우리 집");
  shell.pressKey("ArrowRight");
  await settle();
  assert.equal(shell.byId("home").hidden, false);
  assert.equal(shell.byId("clock-unavailable").hidden, false);
  assert.equal(cue.textContent, "다음: 택배 들이기");
});

test("read-only rehearsal crosses the observed house moments without posting actions", async (t) => {
  const { episode, rationale, card, hub, viewer } = sceneFixture();
  const { episode_id: id } = episode;
  const writes = [];
  const shell = await openShell(t, `?episode=${id}&replay=1&auto=1`, (path, options) => {
    if (options?.method === "POST") writes.push(path);
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path === "/demo/api/sim/viewer") return new Response(viewer());
    if (path.endsWith("/memory")) return Response.json(fixture("ep_9031", "memory"));
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const progression = [
    [3000, "extract"], [2200, "context"], [1600, "context"], [1600, "context"],
    [1600, "intent"], [1600, "intent"], [1600, "tasks"], [3000, "plan"],
  ];
  for (const [dwell, scene] of progression) {
    await shell.runTimer(dwell);
    assert.equal(shell.byId("reason-layout").dataset.stage, scene);
  }
  assert.doesNotMatch(shell.byId("phone-content").innerHTML, /data-reaction|준비 카드 알림/);
  shell.byId("next").onclick();
  await settle();
  assert.equal(shell.byId("home").hidden, false);
  assert.match(shell.byId("timeline").innerHTML, /<small>꺼짐<\/small>/);
  for (const title of ["택배 들여옴", "인덕션 · 스마트 플러그", "손님 도착",
    "TV · 조명", "오븐", "사람의 조작", "일정 종료"]) {
    shell.byId("next").onclick();
    await settle();
    assert.equal(shell.byId("home-title").textContent, title);
  }
  shell.byId("next").onclick();
  await settle();
  assert.equal(shell.byId("home").hidden, true);
  assert.equal(shell.byId("reason-layout").dataset.stage, "record");
  assert.match(shell.byId("stage-copy").innerHTML, /일정 시작 후 70분/);
  assert.match(shell.byId("stage-copy").innerHTML, /2027-04-14까지/);
  assert.deepEqual(writes, []);
});

test("a live guest moment follows the verified mood change without a room-button press", async (t) => {
  const input = sceneFixture();
  const { episode, rationale, card, hub, facts, viewer, devices, relations } = input;
  const guest = facts.find(({ event }) => event === "guest_arrived");
  const moodLine = relations["t_mood#3"];
  const readBack = moodLine.observed;
  moodLine.observed = [];
  const visible = [];
  const shell = await openShell(t, `?episode=${episode.episode_id}&page=house&auto=0`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path === "/demo/api/sim/viewer") return new Response(viewer(visible));
    if (path === "/demo/api/sim/snapshot") return Response.json({ devices });
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    if (path === "/demo/api/home/guests_arrive") {
      visible.push(guest);
      return Response.json({ applied: true, occurred_at: guest.at });
    }
    return new Response(null, { status: 404 });
  }, true);
  shell.byId("presenter-controls").onclick({ target: { closest: () => ({
    dataset: { presenter: "guests_arrive", event: "guest_arrived" },
  }) } });
  await settle();
  assert.equal(shell.byId("home-title").textContent, "손님 도착");
  assert.deepEqual(shell.cameraMoves.at(-1), HOUSE_ROOM_VIEWS.entrance);
  await shell.runTimer(800);
  assert.equal(shell.byId("home-title").textContent, "손님 도착");

  moodLine.observed = readBack.slice(0, 1);
  await shell.runTimer(800);
  const chain = buildChain({ ...input, hubLedger: input.ledger });
  const moment = buildMoments({ ...input, chain, wording }).find(({ id }) => id === "line:t_mood#3");
  assert.equal(shell.byId("home-title").textContent, moment.title);
  assert.match(moment.title, /^TV · .*조명$/);
  assert.equal(shell.byId("view").getAttribute("data-closeup"), "");
  assert.deepEqual(shell.cameraMoves.at(-1), closeView(moment, chain.devices));
  const moves = shell.cameraMoves.length;
  moodLine.observed = readBack;
  await shell.runTimer(800);
  assert.equal(shell.cameraMoves.length, moves);

  shell.byId("previous").onclick();
  await shell.runTimer(800);
  assert.equal(shell.byId("home-title").textContent, "손님 도착");
  assert.deepEqual(shell.cameraMoves.at(-1), HOUSE_ROOM_VIEWS.entrance);
});

test("the presenter alone contacts the operator and each scene sent is recorded", async (t) => {
  const { episode, rationale, card, hub, facts, viewer, devices, relations } = sceneFixture();
  const delivered = facts.find(({ event }) => event === "package.brought_in");
  const fridge = devices.find(({ logical_id }) => logical_id === "fridge_01");
  const notice = relations["t_fridge#5"].observed[0];
  const visible = [];
  const writes = [];
  const shell = await openShell(t, `?episode=${episode.episode_id}&step=5&page=house`, (path, options) => {
    if (options?.method === "POST") writes.push(path);
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path === "/demo/api/sim/viewer") return new Response(viewer(visible).replace(/<\/div>$/,
      `<div data-device="fridge_01" data-values='${JSON.stringify(fridge.values)}'></div></div>`));
    if (path === "/demo/api/sim/snapshot") return Response.json({ devices });
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    const event = {
      "/demo/api/home/delivery": "package.brought_in", "/demo/api/home/guests_arrive": "guest_arrived",
      "/demo/api/person/mom_light": "person", "/demo/api/home/event_end": "event_end",
    }[path];
    if (event) {
      const fact = facts.find((row) => row.event === event);
      visible.push(fact);
      if (event === "package.brought_in") Object.assign(fridge, { values: notice.values, revisions: notice.revisions });
      return Response.json({ applied: true, ...(event !== "person" ? { occurred_at: fact.at } : {}) });
    }
    return new Response(null, { status: 404 });
  }, true);

  assert.ok(!shell.byId("presenter-controls").hidden);
  assert.deepEqual(shell.drawn, []);
  assert.match(shell.byId("timeline").innerHTML, /택배 들여옴<\/span><small>대기/);
  const navigate = () => shell.byId("next").onclick();
  navigate();
  assert.deepEqual(writes, []);
  assert.ok(shell.drawn.every(({ slots }) => slots.length === 0));
  const presenter = (presenter, event) => shell.byId("presenter-controls").onclick({
    target: { closest: () => ({ dataset: { presenter, event } }) },
  });
  presenter("delivery", "package.brought_in");
  await settle();
  assert.equal(shell.byId("home-title").textContent, "택배 들여옴");
  assert.match(shell.byId("home-time").textContent, /18:05/);
  const scene = shell.drawn.at(-1);
  assert.ok(scene.moment.endsWith(String(Date.parse(delivered.at))));
  assert.deepEqual(scene.slots.map(({ slot }) => slot), ["strawberry", "cream", "balloon", "balloon", "cake_topper", "party_hat"]);
  assert.match(scene.artwork.fridge_panel, /^data:image\/svg\+xml,/);
  for (const [name, event] of [["guests_arrive", "guest_arrived"], ["mom_light"], ["event_end", "event_end"]]) {
    presenter(name, event);
    await settle();
  }
  shell.byId("previous").onclick();
  navigate();
  await settle();
  assert.deepEqual(writes, ["/demo/api/home/delivery", "/demo/api/home/guests_arrive",
    "/demo/api/person/mom_light", "/demo/api/home/event_end"]);
  const recorded = [...shell.recordings.values()][0];
  const sceneEntries = recorded.filter(({ kind }) => kind === "scene").map(({ data }) => data);
  assert.ok(sceneEntries.every(({ scene }) => !scene.artwork));
  assert.deepEqual(sceneEntries.find(({ artwork }) => artwork).artwork, { fridge_panel: fridgeValues("strawberry") });
  assert.deepEqual(sceneEntries.map(({ scene, artwork }) => withSceneArtwork(scene, artwork)), shell.drawn);
});

test("each shell room button selects its Simulator camera and holds it through observation polls", async (t) => {
  const { episode, rationale, card, hub, viewer, devices } = sceneFixture();
  const shell = await openShell(t, `?episode=${episode.episode_id}&page=house&auto=0`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path === "/demo/api/sim/viewer") return new Response(viewer());
    if (path === "/demo/api/sim/snapshot") return Response.json({ devices });
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  }, true);
  shell.byId("next").onclick();
  assert.equal(shell.byId("view").getAttribute("data-closeup"), "");
  assert.deepEqual(shell.roomButtons.map(({ textContent }) => textContent), ["현관", "거실", "주방"]);
  for (const button of shell.roomButtons) {
    button.onclick();
    assert.deepEqual(shell.cameraMoves.at(-1), HOUSE_ROOM_VIEWS[button.dataset.room]);
    assert.equal(button.getAttribute("aria-pressed"), "true");
    assert.equal(shell.byId("view").getAttribute("data-closeup"), undefined);
  }
  const moves = shell.cameraMoves.length;
  await shell.runTimer(800);
  assert.equal(shell.cameraMoves.length, moves);
  shell.byId("next").onclick();
  assert.equal(shell.byId("view").getAttribute("data-closeup"), "");
});

test("a saved run replays the judgment, scene snapshots and ending with upstream fetch blocked", async (t) => {
  const { episode, rationale, card, hubPlan } = birthday();
  const recording = "e".repeat(32);
  const task = rationale.tasks[0];
  const tags = { data: [{ kind: "line", ref: task.task_id, text: task.line, tag: { short: "거실 청소", action: "clean" } }] };
  const requests = [];
  const story_at = "2026-10-17T05:00:20Z";
  const entry = (kind, data) => ({ kind, data, story_at, arrived_at: "2026-11-25T01:22:33Z" });
  const scenes = ["plan", "delivery", "guests", "end"].map((kind) =>
    ({ id: kind, kind, title: wording[kind].title, room: "overview", focusDevices: [] }));
  const artwork = { tv: tvValues("kids_party", { palette: "ocean_blue", motif: { center: "crown" } }) };
  const savedScenes = [
    { scene: { moment: "delivery", slots: [{ slot: "strawberry", params: { placement: "counter" }, anchor: "kitchen" }] } },
    { scene: { moment: "guests", slots: [], artwork: { tv: "data:image/svg+xml;base64,PHN2Zy8+" } } },
    { scene: { moment: "guests", slots: [] }, artwork },
  ];
  const entries = [
    entry("rationale", { ...rationale, observations: [] }),
    entry("cards", { cards: [card] }),
    entry("episode", episode),
    entry("hub", { ledger: [{ kind: "plan", plan_id: episode.episode_id, at: hubPlan.sent_at }] }),
    ...scenes.flatMap((scene) => [
      entry("house", { moment: scene }),
      entry("snapshot", { devices: [], scene: scene.id }),
      entry("viewer", `<div id="viewer-markers"><p>${scene.id}</p></div>`),
      ...savedScenes.filter((input) => input.scene.moment === scene.id).map((input) =>
        entry("scene", { moment: scene, ...input })),
    ]),
    entry("rationale", rationale),
    entry("memory", fixture("ep_9031", "memory")),
    entry("finish", { stage: "record" }),
  ];
  const shell = await openShell(t, `?recording=${recording}`, (path) => {
    requests.push(path);
    if (path === `/demo/api/recordings/${recording}`) {
      return Response.json({ episode_id: episode.episode_id, household_id: "h_042", entries, tags, demo_path: "house" });
    }
    throw new Error(`Unexpected upstream fetch: ${path}`);
  }, true);
  const stage = () => shell.byId("reason-layout").dataset.stage;
  assert.equal(stage(), "extract");
  for (const [dwell, expected] of [[3000, "context"], [1000, "context"], [1000, "context"],
    [1000, "intent"], [1500, "intent"], [1500, "tasks"], [3000, "plan"]]) {
    await shell.runTimer(dwell);
    assert.equal(stage(), expected);
    if (expected === "tasks" || expected === "plan") {
      assert.match(shell.byId("stage-copy").innerHTML, /data-action="clean"/);
    }
  }
  await shell.runTimer(3000);
  assert.equal(shell.byId("home").hidden, false);
  assert.match(shell.byId("viewer-markers").markup, /<p>plan<\/p>/);
  for (const scene of scenes.slice(1)) {
    await shell.runTimer(6500);
    assert.match(shell.byId("viewer-markers").markup, new RegExp(`<p>${scene.id}</p>`));
    assert.equal(shell.byId("view").getAttribute("data-observed"), "");
  }
  assert.equal(shell.byId("home").hidden, false);
  await shell.runTimer(6500);
  assert.equal(stage(), "record");
  assert.match(shell.byId("stage-copy").innerHTML, /2027-04-14까지/);
  assert.deepEqual(shell.drawn, savedScenes.map(({ scene, artwork }) => withSceneArtwork(scene, artwork)));
  assert.deepEqual(requests, [`/demo/api/recordings/${recording}`]);
});

test("groceries progress from the case evidence to the no-intent verdict and item notices", async (t) => {
  const id = "ep_9150";
  const episode = fixture(id, "episode");
  const rationale = fixture(id, "rationale");
  const shell = await openShell(t, `?episode=${id}&auto=0&replay=1`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, household_id: "h_042" });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [] });
    if (path.endsWith(id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const next = shell.byId("next");
  for (let i = 0; i < 4; i++) next.onclick();
  assert.equal(shell.byId("judgment-intent").hidden, true);
  next.onclick();
  assert.equal(shell.byId("judgment-slots").hidden, true);
  assert.match(shell.byId("judgment-intent").innerHTML, /의도 없음[\s\S]*준비와 따로 본 물건/);
  next.onclick();
  assert.match(shell.byId("stage-copy").innerHTML, /집 준비 0개 · 냉장고 안내 2개/);
});

test("an item-only replay ends at the plan with its Hub receipt", async (t) => {
  const id = "ep_91502";
  const episode = { ...fixture("ep_9150", "episode"), episode_id: id };
  const rationale = { ...fixture("ep_9150", "rationale"), episode_id: id };
  const hub = { ledger: [{ kind: "plan", plan_id: id, what: "계획 받음", at: episode.shared_at }] };
  const shell = await openShell(t, `?episode=${id}&step=6&replay=1`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.endsWith("/cards")) return Response.json({ cards: [] });
    if (path.endsWith(id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  assert.equal(shell.byId("home").hidden, true);
  assert.equal(shell.byId("reason").hidden, false);
  assert.equal(shell.byId("next").disabled, true);
  assert.equal(shell.byId("phone-map").disabled, true);
  assert.ok(shell.byId("stage-steps").children[5].classList.contains("done"));
  assert.match(shell.byId("stage-copy").innerHTML, /계획 받음/);
});

test("house card reads update the phone without the Hub and ignore an older response", async (t) => {
  const { episode, rationale, card } = birthday();
  const updated = structuredClone(card);
  updated.updated_at = "2026-10-17T14:20:00+09:00";
  updated.lines[3].state = "off";
  updated.lines[3].checked = false;
  updated.lines[3].end_state = "restored";
  const initialRead = Promise.withResolvers();
  const shell = await openShell(t, `?episode=${episode.episode_id}&step=5&page=house`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: false, household_id: "h_042" });
    if (path.includes("/cards?")) return Response.json({ cards: [updated] });
    if (path.endsWith("/cards")) return initialRead.promise;
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const phone = shell.byId("phone-content");
  assert.match(phone.innerHTML, /꺼짐 · 원래대로 돌렸어요/);
  initialRead.resolve(Response.json({ cards: [card] }));
  await settle();
  assert.match(phone.innerHTML, /꺼짐 · 원래대로 돌렸어요/);
});

test("the oven switch uses the App route and leaves the selected World moment in view", async (t) => {
  const { episode, rationale, card, hub } = sceneFixture();
  episode.status = "notified";
  rationale.observations = [];
  const oven = card.lines.find(({ task_id }) => task_id.startsWith("t_oven#"));
  oven.checked = true;
  oven.state = "done";
  oven.end_state = null;
  const writes = [];
  let ignoreReaction = true;
  const shell = await openShell(t, `?episode=${episode.episode_id}&step=5&page=house`, (path, options) => {
    if (options?.method === "POST") writes.push([path, JSON.parse(options.body)]);
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json(hub);
    if (path === "/demo/api/reaction") {
      if (ignoreReaction) return Response.json({ ...card, stopped: true });
      oven.state = "off";
      oven.checked = false;
      oven.end_state = "restored";
      return Response.json(card);
    }
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const next = () => shell.byId("next").onclick();
  next();
  next();
  assert.equal(shell.byId("home-title").textContent, "오븐");
  assert.deepEqual(writes, []);
  const switchOven = () => shell.byId("phone-content").onclick({
    target: { closest: () => ({ dataset: { card: card.card_id, task: oven.task_id, reaction: "line_off" } }) },
  });
  await switchOven();
  assert.match(shell.byId("phone-content").innerHTML, /꺼짐 상태를 확인하지 못했어요/);
  ignoreReaction = false;
  await switchOven();
  assert.deepEqual(writes, Array.from({ length: 2 }, () =>
    ["/demo/api/reaction", { card_id: card.card_id, task_id: oven.task_id, reaction: "line_off" }]));
  assert.equal(shell.byId("home-title").textContent, "오븐");
  assert.match(shell.byId("phone-content").innerHTML, /꺼짐 · 원래대로 돌렸어요/);
});

for (const status of [200, 503]) {
  test(`the replay record distinguishes a ${status} memory response from loading`, async (t) => {
    const { episode, rationale, card } = birthday();
    const memory = Promise.withResolvers();
    const shell = await openShell(t, `?episode=${episode.episode_id}&step=7&replay=1`, (path) => {
      if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
      if (path === "/demo/api/hub") return Response.json({ ledger: [receipt(episode)] });
    if (path === "/demo/api/sim/viewer") return new Response(sceneFixture().viewer());
      if (path.endsWith("/memory")) return memory.promise;
      if (path.endsWith("/rationale")) return Response.json(rationale);
      if (path.endsWith("/cards")) return Response.json({ cards: [card] });
      if (path.endsWith(episode.episode_id)) return Response.json(episode);
      return new Response(null, { status: 404 });
    });
    const copy = shell.byId("phone-content");
    assert.match(copy.innerHTML, /기억을 불러오는 중이에요/);
    assert.match(shell.byId("stage-beat").textContent, /관찰 결과를 기다려요/);
    assert.equal(shell.byId("reason").hidden, true);
    memory.resolve(Response.json({ household_id: "h_042", intents: [] }, { status }));
    await settle();
    assert.match(copy.innerHTML, status === 200 ? /저장된 기억이 없어요/ : /기억을 불러오지 못했어요/);
    assert.doesNotMatch(copy.innerHTML, /기억을 불러오는 중이에요/);
    assert.equal(shell.byId("reason").hidden, status !== 200);
  });
}

test("the house phone shows item guidance separately through waiting, release and closure", async (t) => {
  const { episode, rationale, card } = birthday();
  episode.status = "notified";
  const notice = episode.item_tasks[0];
  episode.item_tasks = [notice];
  notice.state = "scheduled";
  const shell = await openShell(t, `?episode=${episode.episode_id}&step=5&page=house`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json({ ledger: [receipt(episode)] });
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const markup = () => shell.byId("phone-content").innerHTML;
  assert.match(markup(), /준비 카드[\s\S]*<section class="app-card notice-card"><h3>냉장고 안내/);
  assert.match(markup(), /택배를 집 안으로 들이면 안내를 볼 수 있어요/);
  assert.ok(!markup().includes(notice.text));

  notice.state = "done";
  for (let i = 0; i < 4; i++) await shell.runTimer(800);
  assert.ok(markup().includes(notice.text));
  assert.match(markup(), /<small>완료<\/small>/);

  episode.status = "closed";
  for (let i = 0; i < 4; i++) await shell.runTimer(800);
  assert.match(markup(), /품목 안내가 종료됐어요/);
  assert.ok(!markup().includes(notice.text));
});

test("the record shows both card observations in card order", async (t) => {
  const { episode, rationale, card } = birthday();
  const second = { ...card, card_id: "nc_332", text: "두 번째 준비",
    lines: [{ ...card.lines[0], task_id: "t_second#7", text: "두 번째 할 일" }] };
  episode.card_ids.push(second.card_id);
  rationale.observations.unshift({ card_id: second.card_id, verdict: "stopped", task_feedback: [
    { task_id: "t_second#7", user: "off", when: "during_run", actions: [] },
  ] });
  const shell = await openShell(t, `?episode=${episode.episode_id}&step=7`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json({ ledger: [receipt(episode)] });
    if (path === "/demo/api/sim/viewer") return new Response(sceneFixture().viewer());
    if (path.endsWith("/memory")) return Response.json({ household_id: "h_042", intents: [] });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.endsWith("/cards")) return Response.json({ cards: [card, second] });
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const markup = shell.byId("phone-content").innerHTML;
  assert.match(markup, /판단은 맞았고[\s\S]*손님 오기 전 거실 청소[\s\S]*두 번째 준비[\s\S]*이 준비를 중지하셨어요[\s\S]*두 번째 할 일[\s\S]*실행 중에 끄셨어요/);
  assert.match(markup, /아이 안전 모드[^<]*그대로 쓰셨어요/);
});

test("the right area waits for verdicts and a fresh memory read before opening the record", async (t) => {
  const { episode, rationale, card } = birthday();
  const observation = rationale.observations[0];
  rationale.observations = [];
  let memory = { household_id: "h_042", intents: [] };
  const shell = await openShell(t, `?episode=${episode.episode_id}&step=7`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json({ ledger: [receipt(episode)] });
    if (path === "/demo/api/sim/viewer") return new Response(sceneFixture().viewer());
    if (path.endsWith("/memory")) return Response.json(memory);
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const copy = shell.byId("phone-content");
  assert.match(copy.innerHTML, /파티가 끝나면 판단 확인이 와요/);
  assert.equal(shell.byId("reason").hidden, true);
  assert.match(shell.byId("stage-beat").textContent, /관찰 결과를 기다려요/);
  rationale.observations = [observation];
  memory = fixture("ep_9031", "memory");
  for (let i = 0; i < 4; i++) await shell.runTimer(800);
  assert.match(copy.innerHTML, /판단은 맞았고/);
  assert.match(copy.innerHTML, /다음에는 빼 둘 줄/);
  assert.equal(shell.byId("home").hidden, true);
  assert.equal(shell.byId("stage-steps").children[6].getAttribute("aria-current"), "step");
  assert.match(shell.byId("stage-copy").innerHTML, /판단은 맞았고[\s\S]*2027-04-14까지/);
});

test("birthday evidence can be followed from a topper to the light and back", () => {
  const input = birthday();
  const events = fixture("ep_9031", "events").filter(({ source }) => source === "hub");
  const hubLedger = [
    { kind: "plan", plan_id: input.hubPlan.plan_id, at: input.hubPlan.sent_at },
    ...events.map(({ at, type }) => ({ kind: "event", at, event_type: type })),
  ];
  const observed = { power: true, color: { kelvin: 3000 } };
  const snapshot = { devices: [{ logical_id: "light_01", values: observed, available: true }] };
  const chain = buildChain({ ...input, hubLedger, snapshot });

  assert.equal(chain.devices.length, 9);
  for (const [id, room] of [["purifier_01", "living_room"], ["styler_01", "entrance"]]) {
    const device = chain.devices.find(({ logicalId }) => logicalId === id);
    assert.equal(device.room, room);
    assert.equal(device.chosen, false);
    assert.deepEqual(device.traces, []);
  }
  assert.deepEqual(chain.items.filter(({ unbundled }) => unbundled).map(({ id }) => id), input.rationale.unbundled);
  assert.deepEqual(chain.evidence.kbCounts, input.rationale.evidence.kb_counts);
  assert.deepEqual(chain.evidence.kbExamples, input.rationale.evidence.kb_examples);
  assert.deepEqual(chain.evidence.unusual, input.rationale.evidence.unusual_items);
  assert.equal(chain.evidence.calendar.find(({ id }) => id === chain.intent.calendarEvent).start, "14:00");
  assert.deepEqual(chain.slots.find(({ key }) => key === "event").basis, ["c1", "케이크 토퍼"]);
  assert.deepEqual(chain.slots.find(({ key }) => key === "guests").basis, ["고깔모자", "가구 유형"]);

  const topper = chain.items.find(({ id }) => id === "케이크 토퍼");
  const theme = chain.slots.find(({ key, basis }) => key === "theme" && basis.includes(topper.id));
  assert.equal(theme.value, "디즈니 공주");
  const intent = chain.intents.find(({ slotIds }) => slotIds.includes(theme.id));
  assert.equal(intent.id, "kid_birthday_party");
  const mood = chain.tasks.find(({ intentId, devices }) => intentId === intent.id && devices.includes("light_01"));
  assert.ok(chain.needs.some(({ text, taskIds }) => text === mood.need && taskIds.includes(mood.id)));
  assert.equal(mood.time.story, "손님이 오면");
  assert.equal(mood.values.find(({ device }) => device === "light_01").value.hue, 330);

  const light = chain.devices.find(({ logicalId }) => logicalId === "light_01");
  assert.equal(light.chosen, true);
  assert.deepEqual(light.state, observed);
  assert.deepEqual(light.traces, [mood.id]);
  assert.equal(chain.tasks.find(({ id }) => id === light.traces[0]).intentId, intent.id);
  assert.equal(chain.items.find(({ id }) => id === theme.basis[0]), topper);
  assert.equal(chain.devices.find(({ logicalId }) => logicalId === "fridge_01").chosen, false);
  assert.equal(chain.cards[0].lines[1].time.story, "토 13:30");
  assert.equal(chain.cards[0].lines[3].time.story, "토 14:00");
});

test("groceries retain the item notices with an empty preparation chain", () => {
  const episode = fixture("ep_9150", "episode");
  const rationale = fixture("ep_9150", "rationale");
  const plan = fixture("ep_9150", "plan.v1");
  const hubPlan = Object.fromEntries(plan.tasks.map(({ task_id, actions }) => [task_id, actions]));
  const hubLedger = [{ kind: "plan", plan_id: plan.plan_id, at: plan.sent_at }];
  const chain = buildChain({ episode, rationale, hubPlan, hubLedger });

  assert.equal(chain.intent, null);
  assert.deepEqual(chain.none, { reason: rationale.none_reason });
  assert.deepEqual(chain.slots, []);
  assert.deepEqual(chain.needs, []);
  assert.deepEqual(chain.tasks, []);
  assert.deepEqual(chain.item_tasks, episode.item_tasks);
  assert.ok(chain.items.every(({ unbundled }) => unbundled));
  assert.equal(chain.devices.length, 9);
  assert.ok(chain.devices.every(({ chosen, traces }) => !chosen && traces.length === 0));
  assert.equal(chain.cardReady, true);
});

test("house annotations use only the moment name alongside the Simulator values", () => {
  const input = birthday();
  const observed = { show_notice: input.rationale.item_tasks[0].text };
  const snapshot = { devices: [{ logical_id: "fridge_01", values: observed }] };
  const chain = buildChain({ ...input, snapshot, hubLedger: [receipt(input.episode)] });
  const focusDevices = ["fridge_01"];
  const { title } = wording.delivery;
  const house = houseDevicePresentation(chain, focusDevices, title);
  assert.deepEqual(house.get("fridge_01"), { focused: true, resting: true, moment: "택배 들여옴" });
  assert.deepEqual(chain.devices.find(({ logicalId }) => logicalId === "fridge_01").state, observed);
  for (const [device, { moment }] of house) {
    if (device !== "fridge_01") assert.equal(moment, "");
  }
  const chainScript = readFileSync(new URL("../ui/chain.js", import.meta.url), "utf8");
  const shellScript = readFileSync(new URL("../ui/demo.js", import.meta.url), "utf8");
  assert.doesNotMatch(chainScript, /traceLabel|←/);
  assert.match(shellScript, /annotation.textContent = moment/);
  assert.doesNotMatch(shellScript, /marker-trace/);
});

test("the grocery house rests all nine devices even with an observed item notice", () => {
  const episode = fixture("ep_9150", "episode");
  const rationale = fixture("ep_9150", "rationale");
  const hubPlan = fixture("ep_9150", "plan.v1");
  const snapshot = { devices: [{ logical_id: "fridge_01", values: { show_notice: rationale.item_tasks[0].text } }] };
  const house = houseDevicePresentation(buildChain({ episode, rationale, hubPlan, snapshot, hubLedger: [receipt(episode)] }));
  assert.equal(house.size, 9);
  for (const presentation of house.values()) {
    assert.deepEqual(presentation, { focused: false, resting: true, moment: "" });
  }
});

const HOUSE_SCREENS = [[1920, 1080], [1600, 1000], [1440, 900]];

function assertNoLabelOverlap(labels, width, height, scale = 1) {
  const pixels = (position) => Math.round(position * scale);
  for (const [index, label] of labels.entries()) {
    assert.ok(label.left >= 8 && label.right <= width - 8, label.id);
    assert.ok(label.top >= 46 && label.top + label.height <= height - 44, label.id);
    for (const other of labels.slice(index + 1)) {
      assert.ok(pixels(label.right) <= pixels(other.left) || pixels(other.right) <= pixels(label.left) ||
        pixels(label.top + label.height) <= pixels(other.top) || pixels(other.top + other.height) <= pixels(label.top),
      `${label.id} overlaps ${other.id}`);
    }
  }
}

test("focused demo labels reserve space and colliding resting tags drop at all three screen sizes", () => {
  // Exercise the collision rules with several oversized, overlapping labels.
  const width = 1256, height = 653;
  const markers = [
    { id: "display_01", focused: true, x: 410, y: 300, width: 570, height: 58 },
    { id: "light_01", focused: true, x: 530, y: 300, width: 570, height: 58 },
    { id: "cleaner_01", x: 290, y: 291, width: 65, height: 17 },
    { id: "fridge_01", required: true, x: 1100, y: 600, width: 164, height: 32 },
    { id: "cooktop_01", required: true, x: 880, y: 580, width: 124, height: 32 },
    { id: "plug_kettle", x: 887, y: 573, width: 82, height: 17 },
    { id: "oven_01", required: true, x: 1000, y: 374, width: 152, height: 32 },
  ];
  const labels = layoutHouseLabels(markers, width, height);
  assert.deepEqual(labels.map(({ id }) => id), ["display_01", "light_01", "oven_01", "cooktop_01", "fridge_01"]);
  for (const [screenWidth, screenHeight] of HOUSE_SCREENS) {
    assertNoLabelOverlap(labels, width, height, Math.min(screenWidth / 1920, screenHeight / 1080));
  }
});

test("mood-line labels leave the TV, pendant and lit floor clear in the living-room view", () => {
  const width = 1040, height = 630;
  const input = sceneFixture();
  const chain = buildChain({ ...input, hubLedger: input.ledger });
  const mood = buildMoments({ ...input, chain, wording }).find(({ id }) => id === "line:t_mood#3");
  const { eye, aim, zoom } = cameras.living_room;
  const camera = new OrthographicCamera();
  orientHouseCamera(camera, new Vector3(...eye), new Vector3(...aim), zoom, width / height);
  const { anchors, ...clearance } = projectHouseLabels(camera, width, height);
  // Label dimensions in the demo's fixed stage before scaling to the viewport.
  const sizes = {
    entrance: [133, 28], display_01: [300, 54], light_01: [300, 54], cleaner_01: [112, 28],
    cooktop_01: [92, 28], oven_01: [208, 27], fridge_01: [208, 28], plug_kettle: [137, 28],
    purifier_01: [77, 17], styler_01: [57, 17],
  };
  const markers = Object.entries(sizes).map(([id, [width, height]]) => ({
    id, ...anchors[id], width, height, focused: mood.focusDevices.includes(id),
    required: !["purifier_01", "styler_01"].includes(id),
  }));
  const labels = layoutHouseLabels(markers, width, height, clearance);
  for (const marker of markers.filter(({ required }) => required)) {
    assert.ok(labels.some(({ id }) => id === marker.id), `${marker.id} was not placed`);
  }
  for (const [screenWidth, screenHeight] of [[1920, 1080], [1440, 900]]) {
    const scale = Math.min(screenWidth / 1920, screenHeight / 1080);
    const px = (position) => Math.round(position * scale);
    assertNoLabelOverlap(labels, width, height, scale);
    for (const label of labels) {
      for (const [name, region] of Object.entries(clearance)) {
        assert.ok(px(label.right) <= px(region.left) || px(region.right) <= px(label.left) ||
          px(label.bottom) <= px(region.top) || px(region.bottom) <= px(label.top),
        `${label.id} overlaps the ${name} at ${screenWidth}×${screenHeight}`);
      }
    }
  }
});

test("the rebased card preserves its supplied times and story-time labels", () => {
  const input = birthday();
  const card = structuredClone(input.card);
  card.starts_at = "2026-11-20T11:42:11+09:00";
  card.lines[0].when.time = "2026-11-20T11:39:11+09:00";
  card.lines[1].when.time = "2026-11-20T11:41:11+09:00";
  const scheduled = card.lines[0].when.time;
  const storyTime = {
    timing: {
      before_start_default_min: { normal: 90, demo: 3 },
      guest_window_before_min: { normal: 30, demo: 1 },
      end_fallback_min: { normal: 180, demo: 10 },
    },
    guestWindows: { "t_mood#3": { to: "2026-11-20T11:42:41+09:00" } },
  };
  const hubLedger = [
    receipt(input.episode),
    { kind: "event", event_type: "guest_arrived", at: "2026-11-20T11:41:41+09:00" },
  ];
  const chain = buildChain({ ...input, card: [card], hubLedger, storyTime });

  assert.equal(chain.cards[0].lines[0].time.story, "토 12:30");
  assert.equal(chain.tasks[0].time.derivation, "토 14:00 일정 → 90분 전 → 토 12:30");
  assert.equal(chain.cards[0].lines[0].when.time, scheduled);
  assert.equal(chain.cards[0].lines[1].time.story, "토 13:30");
});

test("the plan receipt uses only this episode and the selected story clock", () => {
  const birthdayOrder = birthday();
  const groceries = {
    episode: fixture("ep_9150", "episode"),
    rationale: fixture("ep_9150", "rationale"),
    hubPlan: fixture("ep_9150", "plan.v1"),
  };
  const storyTime = {
    timing: {
      before_start_default_min: { normal: 90, demo: 3 },
      guest_window_before_min: { normal: 30, demo: 1 },
      end_fallback_min: { normal: 180, demo: 10 },
    },

  };
  const shared = "2026-11-20T11:41:00+09:00";
  const received = "2026-11-20T11:41:31+09:00";
  const delivered = "2026-11-20T11:41:41+09:00";
  const packageEvent = "package.brought_in";
  for (const [input, episodeId, expectedPlan] of [
    [birthdayOrder, "ep_9031", "토 13:59 · 계획 받음"],
    [groceries, "ep_91502", "금 11:41 · 계획 받음"],
  ]) {
    const episode = { ...input.episode, episode_id: episodeId, shared_at: shared };
    const card = input.card && {
      ...input.card, starts_at: "2026-11-20T11:42:11+09:00",
      lines: input.card.lines.map((line, index) => index < 2 ? {
        ...line, when: { ...line.when, time: index === 0 ? "2026-11-20T11:39:11+09:00" : "2026-11-20T11:41:11+09:00" },
      } : line),
    };
    const hubLedger = [
      { kind: "plan", plan_id: episodeId, plan_version: 1, at: received },
      ...(card ? [{ kind: "plan", plan_id: episodeId, plan_version: 2, at: received }] : []),
      { kind: "event", event_type: packageEvent, at: delivered },
      { kind: "plan", plan_id: episodeId, plan_version: card ? 3 : 2, at: delivered, timing: { event: packageEvent } },
      { kind: "run", device: "fridge_01", at: delivered, timing: { plan_id: episodeId, event: packageEvent } },
    ];
    const chain = buildChain({ ...input, episode, card, hubLedger, storyTime });
    assert.equal(chain.receipt.at, received);
    assert.equal(chain.receiptStory, expectedPlan);
    const unknownOrderTime = buildChain({ ...input, episode: { ...episode, shared_at: undefined }, card, hubLedger, storyTime });
    assert.equal(unknownOrderTime.ready.hub, false);
    assert.equal(unknownOrderTime.receiptStory, "");
  }
});

test("pending judgment, cardless intents and missing Hub plans preserve distinct evidence", () => {
  const { episode, rationale } = birthday();
  const pending = buildChain({ episode });
  assert.equal(pending.none, undefined);
  assert.equal(pending.hasRationale, false);
  assert.deepEqual(pending.item_tasks, episode.item_tasks);

  const first = rationale.intents[0];
  const judgment = { ...rationale, intents: [first, { ...first, card_id: null }] };
  const chain = buildChain({ episode, rationale: judgment });
  assert.equal(chain.intents.length, 2);
  assert.equal(new Set(chain.slots.map(({ id }) => id)).size, 8);
  assert.ok(chain.tasks.every(({ intentId, values }) => intentId === chain.intent.id && values.length === 0));
  assert.equal(chain.cardReady, false);
});

test("each reason stage waits for its result", () => {
  const { episode, rationale, card, hubPlan } = birthday();
  const { tasks, item_tasks, intents, ...evidence } = rationale;
  const staged = { ...episode, status: "reading", card_ids: [], item_tasks: [] };
  const ready = (input) => Object.entries(buildChain(input).ready).filter(([, value]) => value).map(([id]) => id);
  assert.deepEqual(ready({ episode: { ...staged, status: "received", items: [] } }), []);
  assert.deepEqual(ready({ episode: staged }), ["extract"]);

  const context = { episode: staged, rationale: { ...evidence, intents: [], tasks: [], item_tasks: [], unbundled: [] } };
  assert.deepEqual(ready(context), ["extract", "context"]);
  assert.equal(buildChain(context).none, undefined);
  const intent = { ...context, rationale: { ...context.rationale, intents } };
  assert.deepEqual(ready(intent), ["extract", "context", "intent"]);

  const judged = { ...staged, status: "judged", item_tasks };
  const planned = { episode: judged, rationale: { ...rationale, tasks } };
  assert.deepEqual(ready(planned), ["extract", "context", "intent", "tasks"]);
  const notified = { ...planned, episode: { ...judged, status: "notified", card_ids: episode.card_ids }, card };
  assert.deepEqual(ready({ ...notified, hubPlan }), ["extract", "context", "intent", "tasks", "plan"]);
  const hubLedger = [{ kind: "plan", plan_id: "ep_9150", at: hubPlan.sent_at }];
  assert.deepEqual(ready({ ...notified, hubLedger }), ["extract", "context", "intent", "tasks", "plan"]);
  hubLedger.push({ kind: "plan", plan_id: episode.episode_id, at: hubPlan.sent_at });
  assert.deepEqual(ready({ ...notified, hubLedger }), ["extract", "context", "intent", "tasks", "plan", "hub"]);
});

test("a recorded no-intent result and a judgment with no tasks can advance", () => {
  const episode = fixture("ep_9150", "episode");
  const rationale = fixture("ep_9150", "rationale");
  const { item_tasks } = rationale;
  const intent = buildChain({
    episode: { ...episode, status: "reading", item_tasks: [] },
    rationale: { ...rationale, item_tasks: [] },
  });
  assert.equal(intent.ready.intent, true);
  assert.equal(intent.ready.tasks, false);
  assert.equal(intent.ready.plan, false);

  const noTasks = buildChain({ episode: { ...episode, item_tasks: [] }, rationale: { ...rationale, item_tasks: [] } });
  assert.equal(noTasks.ready.tasks, true);
  assert.equal(noTasks.ready.plan, true);
  assert.equal(noTasks.ready.hub, false);

  const groceries = buildChain({ episode, rationale });
  assert.equal(groceries.ready.tasks, true);
  assert.equal(groceries.ready.plan, false);
  assert.deepEqual(groceries.item_tasks, item_tasks);
  const hubLedger = [{ kind: "plan", plan_id: episode.episode_id, at: episode.shared_at }];
  const received = buildChain({ episode, rationale, hubLedger });
  assert.equal(received.ready.plan, true);
  assert.equal(received.ready.hub, true);
});

test("a house link waits for this run's receipt and for Simulator observations", async (t) => {
  const { episode, rationale, card, hubPlan } = birthday();
  let received = false;
  let simulatorUp = false;
  let houseReads = 0;
  const shell = await openShell(t, `?episode=${episode.episode_id}&page=house&auto=0`, (path) => {
    if (path === "/demo/api/config") return Response.json({ server: true, hub: true, household_id: "h_042" });
    if (path === "/demo/api/hub") return Response.json({ ledger: [
      receipt(episode, new Date(Date.parse(episode.shared_at) - 1000).toISOString()),
      ...(received ? [receipt(episode, hubPlan.sent_at)] : []),
    ] });
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    if (path.startsWith("/demo/api/sim/")) {
      ++houseReads;
      if (!simulatorUp) return new Response(null, { status: 502 });
      return path.endsWith("/snapshot") ? Response.json({ devices: [] })
        : new Response('<div id="viewer-markers"></div>');
    }
    return new Response(null, { status: 404 });
  });
  const ready = () => shell.byId("stage-steps").children[5].classList.contains("done");
  assert.equal(ready(), false);
  assert.equal(shell.byId("home").hidden, true);
  assert.equal(houseReads, 0);
  received = true;
  await shell.runTimer(800);
  assert.equal(ready(), true);
  assert.equal(shell.byId("home").hidden, false);
  assert.equal(shell.byId("house-waiting").hidden, false);
  assert.equal(shell.byId("view").getAttribute("data-observed"), undefined);
  simulatorUp = true;
  await shell.runTimer(800);
  assert.equal(shell.byId("house-waiting").hidden, true);
  assert.equal(shell.byId("view").getAttribute("data-observed"), "");
});

for (const choice of ["plan", "house"]) {
  test(`the presenter choice ${choice} controls the path independently of intent`, async (t) => {
    const { episode, rationale, card } = birthday();
    if (choice === "house") rationale.intents[0].intent_id = "other_intent";
    const shell = await openShell(t, "?auto=0", (path) => {
      if (path === "/demo/api/config") return Response.json({ server: true, hub: true, fixture: true, household_id: "h_042" });
      if (path === "/demo/api/order") return Response.json({ episode_id: episode.episode_id, status: "received" });
      if (path === "/demo/api/hub") return Response.json({ ledger: [receipt(episode)] });
      if (path.endsWith("/rationale")) return Response.json(rationale);
      if (path.includes("/cards")) return Response.json({ cards: [card] });
      if (path.endsWith(episode.episode_id)) return Response.json(episode);
      return new Response(null, { status: 404 });
    });
    const control = shell.byId("demo-path");
    assert.equal(control.value, "house");
    control.onchange({ target: { value: choice } });
    await shell.byId("sample").onclick();
    await shell.runTimer(800);
    for (let i = 0; i < 8; ++i) shell.byId("next").onclick();
    shell.byId("card-notification").onclick();
    await settle();
    assert.equal(shell.byId("reason-layout").dataset.stage, "plan");
    assert.deepEqual([...shell.recordingPaths.values()], [choice]);
    assert.equal(shell.byId("phone-map").disabled, choice === "plan");
    shell.pageButtons[1].onclick();
    assert.equal(shell.byId("home").hidden, choice === "plan");
  });
}

test("source text and default icon show before tags independently swap into judgment and plan", async (t) => {
  const { episode, rationale, card } = birthday();
  const result = Promise.withResolvers();
  const task = rationale.tasks[1];
  const intent = rationale.intents[0];
  const tags = [
    { kind: "line", ref: task.task_id, text: task.line, tag: {
      short: "아이 안전 모드", action: "safety_lock", devices: ["cooktop_01"],
    } },
    { kind: "slot", ref: "theme", text: intent.situation.theme, tag: {
      highlights: [intent.situation.theme], palette: "princess_pink",
    } },
    { kind: "intent", ref: intent.intent_id, text: intent.intent_text, tag: { highlights: ["아이 생일 파티"] } },
  ];
  const shell = await openShell(t, `?episode=${episode.episode_id}&step=3&auto=0`, (path, options) => {
    if (path === "/demo/api/config") return Response.json({ server: true, tagger: true, household_id: "h_042" });
    if (path === "/demo/tags?episode=ep_9031") {
      assert.match(options.headers["X-SPIRA-Demo-Run"], /^[0-9a-f]{32}$/);
      return result.promise;
    }
    if (path.endsWith("/rationale")) return Response.json(rationale);
    if (path.includes("/cards")) return Response.json({ cards: [card] });
    if (path.endsWith(episode.episode_id)) return Response.json(episode);
    return new Response(null, { status: 404 });
  });
  const intentMarkup = () => shell.byId("judgment-intent").innerHTML;
  const markup = () => shell.byId("stage-copy").innerHTML;
  const next = shell.byId("next");
  next.onclick();
  assert.match(intentMarkup(), new RegExp(intent.intent_text));
  assert.doesNotMatch(intentMarkup(), /tag-highlight/);
  next.onclick();
  assert.ok(markup().includes(task.line));
  assert.match(markup(), /data-action="other"/);
  assert.match(markup(), /스마트 플러그/);
  result.resolve(Response.json({ ready: true, tags }));
  await settle();
  assert.match(markup(), /data-action="safety_lock"/);
  assert.ok(markup().includes(`title="${task.line}"`));
  assert.match(markup(), />아이 안전 모드<\/span>/);
  assert.doesNotMatch(markup(), /스마트 플러그|princess_pink/);
  shell.byId("previous").onclick();
  assert.match(intentMarkup(), /<strong class="tag-highlight">아이 생일 파티<\/strong>/);
  assert.match(shell.byId("judgment-slots").innerHTML, /<strong class="tag-highlight">디즈니 공주<\/strong>/);
  next.onclick();
  shell.byId("card-notification").onclick();
  assert.equal(shell.byId("reason-layout").dataset.stage, "plan");
  assert.match(markup(), /data-action="safety_lock"/);
  assert.doesNotMatch(markup(), /스마트 플러그/);
});


test("item icons and storage come from the prepared type table", async () => {
  const { quantityCards } = await import("../ui/judgment-view.js");
  const items = [
    { id: "딸기", name: "알 수 없는 물건", sourceId: "known" },
    { id: "새 품목", name: "설향 딸기", sourceId: "unknown" },
  ];
  const markup = quantityCards(items, itemTypes);
  assert.match(markup, /data-item="known"[^>]*>\s*<span[^>]*data-icon="strawberry"/);
  assert.match(markup, /data-item="unknown"[^>]*>\s*<span[^>]*data-icon="generic"/);
  assert.equal(itemTypes["딸기"].storage, "냉장");
  assert.equal(itemTypes.generic.storage, "미확인");
});
