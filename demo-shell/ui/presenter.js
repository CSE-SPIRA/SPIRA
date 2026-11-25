import { rehearsalControls } from "./wire.js";

export function createPresenter(context, ui) {
  const { state, observe, api, RECORDING, QUIET_END, notice, exchange, sleep, $, REPLAY, MANUAL, PHONE_CLOCK } = context;

  // The Hub and Simulator follow the Server's story clock independently.
  const FIXTURE_LEAD_MS = 5000;
  const RAMP_SECONDS = 4;
  let clockRead;

  function markClockMissing(status) {
    if (![404, 405, 501].includes(status)) return;
    state.clockMissing = true;
    state.clock = null;
    renderControls();
  }

  // The rehearsal clock is optional. Stop polling it when the peer says it is unavailable.
  function readClock() {
    if (!state.config.server || state.clockMissing) return null;
    const { reader } = state;
    if (clockRead && clockRead.reader === reader) return clockRead.pending;
    const pending = observe("clock", "/demo/api/server/v1/demo/clock", { signal: AbortSignal.timeout(2500) })
      .then(async (clock) => {
        if (!state.clockMoments) {
          const moments = await api("/demo/api/server/v1/demo/moments", { signal: AbortSignal.timeout(2500) });
          if (!Array.isArray(moments) || state.reader !== reader) return null;
          state.clockMoments = true;
        }
        if (state.reader === reader && !(clock.version < state.clock?.version)) {
          state.clock = clock;
          renderControls();
        }
        return state.clock;
      })
      .catch(({ status }) => {
        if (state.reader === reader) markClockMissing(status);
        return state.clock;
      })
      .finally(() => { if (clockRead?.pending === pending) clockRead = null; });
    clockRead = { reader, pending };
    return pending;
  }

  function clockNow() {
    if (RECORDING) return state.replayTime ?? null;
    const clock = state.clock;
    if (!clock) return null;
    const real = Date.now();
    const anchor = Date.parse(clock.real_at);
    const story = Date.parse(clock.story_at);
    const until = clock.ramp_until ? Date.parse(clock.ramp_until) : null;
    if (until !== null && real > until) return story + (until - anchor) * clock.rate + (real - until);
    return story + (real - anchor) * clock.rate;
  }

  async function moveClockTo(scene, { episodeId, signal } = {}) {
    if (!await readClock() || signal?.aborted) return;
    const reader = state.reader;
    const episode = new URLSearchParams({ episode_id: episodeId });
    const momentsPath = "/demo/api/server/v1/demo/moments" + (state.config.fixture ? "" : `?${episode}`);
    const moments = await observe("moments", momentsPath, { signal: AbortSignal.timeout(2500) },
      { transform: (data) => data.filter((entry) => !entry.episode_id || entry.episode_id === episodeId) }).catch((error) => {
      if (state.reader === reader) markClockMissing(error.status);
      if (state.clockMissing) return [];
      throw error;
    });
    if (state.clockMissing) return;
    if (state.reader !== reader) return;
    const forQuiet = scene === QUIET_END;
    const moment = forQuiet ? moments.find(({ event }) => event === scene.event)
      : moments.filter(({ at, event }) => event !== QUIET_END.event && Date.parse(at) > clockNow() + 1000)
        .sort((a, b) => Date.parse(a.at) - Date.parse(b.at))[0];
    if (!moment) {
      if (!forQuiet) notice("앞으로 남은 시연 시각이 없어요.");
      return;
    }
    const now = clockNow();
    if (now === null || signal?.aborted) return;
    const target = Date.parse(moment.at) -
      (state.config.fixture && !forQuiet && moment.kind === "time" ? FIXTURE_LEAD_MS : 0);
    if (forQuiet) {
      state.quietEnd = target;
      if (state.quietRamped.has(episodeId) || target <= now) return;
      state.quietRamped.add(episodeId);
      if (state.page === "reason") ui.reasoning.renderReason();
    } else if (target <= now + 1000) {
      return;
    }
    const clockLines = forQuiet ? [] : ui.house.timeline().filter(({ ready, at, lines }) =>
      !ready && lines?.some(({ when }) => when.time) && Date.parse(at) <= Date.parse(moment.at));
    const message = forQuiet ? "주문을 기다리는 시간을 앞당겨요." : "다음 시연 시각으로 시간을 보내요.";
    notice(message);
    try {
      const timeout = AbortSignal.timeout(12000);
      const options = {
        method: "POST", headers: { "Content-Type": "application/json" },
        signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      };
      if (forQuiet || state.config.fixture) {
        const clock = await observe("clock", "/demo/api/clock", {
          ...options, body: JSON.stringify({ advance_to: new Date(target).toISOString(), over_seconds: RAMP_SECONDS }),
        });
        if (state.reader === reader && !state.clockMissing) state.clock = clock;
      } else {
        const result = await exchange(`/demo/api/clock/next?${episode}`, {
          ...options, body: JSON.stringify({ over_seconds: RAMP_SECONDS }),
        });
        if (state.reader !== reader) return;
        if (!result.ok) {
          if (result.status === 404 && result.body?.message === "No story moments remain") {
            notice("앞으로 남은 시연 시각이 없어요.");
            return;
          }
          markClockMissing(result.status);
          if (state.clockMissing) return;
          throw new Error(result.status);
        }
        ui.recording.log("presenter", { action: "clock", status: result.status, result: result.body });
        await readClock();
      }
      if (state.reader === reader) {
        for (const { id } of clockLines) state.pendingClockLines.add(id);
      }
      await sleep(RAMP_SECONDS * 1000 + 300);
    } finally {
      if ($("notice").textContent === message && !signal?.aborted) notice();
    }
  }

  async function presenterAction({ name, event }) {
    if (REPLAY || state.homeBusy || !ui.house.canEnterHouse()) return;
    state.homeBusy = true;
    renderControls();
    const { reader } = state;
    const before = new Set(state.facts.keys());
    let focus;
    try {
      if (name === "clock") {
        await moveClockTo(null, { episodeId: state.episodeId, signal: reader.signal });
      } else {
        state.pendingClockLines.clear();
        const path = event ? "/demo/api/home/" : "/demo/api/person/";
        const result = await exchange(path + name, { method: "POST", signal: AbortSignal.timeout(8000) });
        if (state.reader !== reader) return;
        ui.recording.log("presenter", { action: name, status: result.status, result: result.body });
        if (!result.ok) throw new Error(result.status);
        if (event && result.body?.occurred_at) ui.house.rememberFacts([{ event, at: result.body.occurred_at }]);
        await Promise.allSettled([ui.surface.refreshSnapshot(), ui.surface.refreshHouseMarkers()]);
        focus = [...state.facts].find(([key, fact]) => !before.has(key) && fact.event === (event ?? "person"))?.[1];
      }
    } catch (error) {
      if (state.reader === reader) notice(`집에서 확인하지 못했어요. (${error.message})`);
    } finally {
      if (state.reader === reader) {
        state.homeBusy = false;
        const index = focus ? ui.house.timeline().findIndex((moment) => moment.ready && moment.event === focus.event &&
          Date.parse(moment.at) === Date.parse(focus.at) && (!focus.device || moment.focusDevices.includes(focus.device)))
          : -1;
        if (!ui.house.goHouse(index, { followGuest: event === "guest_arrived" })) ui.house.renderTimeline();
      }
    }
  }

  function showPage(page) {
    if (page === "house" && !ui.house.canEnterHouse()) return;
    const focusedPanel = (page === "reason" ? $("home") : $("reason")).contains(document.activeElement);
    state.page = page;
    $("reason").hidden = page !== "reason";
    $("home").hidden = page !== "house";
    $("orders").hidden = page !== "reason" || !state.config.fixture;
    if (page === "house") state.auto = null;
    else state.mapOpen = state.recordOpen = state.recordVisible = false;
    document.querySelectorAll("[data-page]").forEach((button) =>
      button.setAttribute("aria-pressed", String(button.dataset.page === page)));
    if (page === "house") {
      ui.house.openHouseView();
      ui.reasoning.renderStageIndicator();
    } else {
      ui.reasoning.renderReason();
      if (state.episodeId) ui.reasoning.autoAdvance();
    }
    if (focusedPanel) (document.querySelector(`[data-page="${page}"]`)).focus({ preventScroll: true });
  }

  function enterHouse() {
    if (!ui.house.canEnterHouse()) return;
    if (RECORDING) {
      ui.recording.playReplayVisit();
      showPage("house");
      if (!MANUAL) void ui.recording.playRecordedHouse();
      return;
    }
    ui.recording.log("house", { moment: ui.recording.recordedMoment(ui.house.currentMoment()) });
    showPage("house");
    void Promise.allSettled([ui.surface.refreshSnapshot(), ui.surface.refreshHouseMarkers()]);
  }

  const STORY_CLOCK = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });

  function tickClock() {
    const now = clockNow();
    $("story-clock").hidden = now === null;
    if (now !== null) {
      $("story-clock").textContent = STORY_CLOCK.format(now);
      $("phone-time").textContent = PHONE_CLOCK.format(now);
    }
    const second = Math.floor(performance.now() / 1000);
    if ((state.waiting || state.retryUntil > 0) && second !== state.indicatorSecond) {
      state.indicatorSecond = second;
      ui.reasoning.renderStageIndicator();
    }
    requestAnimationFrame(tickClock);
  }

  function canUsePhoneMap() {
    return ui.house.canEnterHouse() && !state.draft && (state.page === "house" || state.step >= ui.reasoning.reasonStep("plan"));
  }

  function renderControls() {
    const inHouse = state.page === "house";
    const blocked = state.sharing || state.homeBusy;
    $("phone-map").disabled = blocked || !canUsePhoneMap();
    const moments = ui.house.timeline();
    const index = RECORDING ? state.replayStep : moments.indexOf(ui.house.currentMoment(moments));
    const previous = moments.slice(0, index).some(({ ready }) => ready);
    const next = moments.slice(index + 1).some(({ ready }) => ready);
    $("previous").disabled = blocked || (inHouse ? !previous && !state.recordRequested : state.step === 0);
    const needsShare = !inHouse && !state.episodeId;
    const waiting = !inHouse && state.episodeId && (!ui.reasoning.canMoveReasonForward() || state.draft);
    const atEnd = inHouse && (state.recordRequested || !next && !ui.house.houseEnded(moments));
    $("presenter-controls").hidden = !inHouse || REPLAY || state.recordVisible;
    const clock = rehearsalControls(state.clock, state.clockMoments, state.clockMissing, REPLAY);
    $("presenter-clock").hidden = !clock.advance;
    $("clock-unavailable").hidden = !clock.unavailable;
    for (const button of $("presenter-controls").querySelectorAll("button")) button.disabled = blocked;
    $("next").disabled = blocked || atEnd || waiting || needsShare;
    $("next-share").hidden = !needsShare || state.sharing;
    $("path-control").hidden = inHouse || REPLAY || Boolean(state.episodeId && !state.draft);
    $("demo-path").value = ui.phone.draftPath();
    $("demo-path").disabled = blocked || !state.config.server;
    document.querySelectorAll("[data-order]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.order === state.order));
      button.disabled = blocked || !state.config.server || REPLAY || Boolean(state.reactionPending);
    });
    for (const id of ["sample", "files"]) {
      if ($(id)) $(id).disabled = blocked || !state.config.server;
    }
    document.querySelectorAll("[data-page]").forEach((button) => {
      button.disabled = blocked || (button.dataset.page === "house" && !canUsePhoneMap());
    });
  }

  function move(delta) {
    if (state.sharing || state.homeBusy) return;
    if (delta > 0 && state.page === "reason" && (!state.episodeId || !ui.reasoning.canMoveReasonForward() || state.draft)) return;
    state.auto = null;
    if (state.page === "house" && state.recordRequested) {
      if (delta < 0) {
        state.recordOpen = state.recordRequested = false;
        ui.house.renderTimeline();
      }
    } else if (state.page === "house") {
      const moments = ui.house.timeline();
      const index = RECORDING ? state.replayStep : moments.indexOf(ui.house.currentMoment(moments));
      const next = delta < 0 ? moments.findLastIndex(({ ready }, i) => ready && i < index)
        : moments.findIndex(({ ready }, i) => ready && i > index);
      if (next >= 0) ui.house.goHouse(next);
      else if (delta > 0 && ui.house.houseEnded(moments)) {
        if (RECORDING) ui.recording.applyReplayFrame(state.replay.house.at(-1).frame);
        ui.house.openRecord();
      }
    } else if (state.scenes.reason[state.step].id === "plan" && delta > 0) {
      enterHouse();
    } else {
      if (delta > 0) ui.reasoning.setStep(ui.reasoning.nextReasonStep());
      else {
        const previous = state.scenes.reason.slice(0, state.step).findLastIndex(({ beat }, index) =>
          !beat || ui.reasoning.reasonReady(index));
        ui.reasoning.setStep(previous);
      }
      if (delta > 0) ui.reasoning.autoAdvance();
    }
  }

  function fit() {
    const frame = $("frame");
    state.scale = Math.min(innerWidth / frame.offsetWidth, innerHeight / frame.offsetHeight);
    frame.style.setProperty("--scale", state.scale);
    state.house?.resize();
  }

  function resolveHouseLink() {
    if (!state.houseLink || !state.chain.ready.plan) return;
    const { record } = state.houseLink;
    if (state.runPath === "house" && !ui.house.canEnterHouse()) return;
    state.houseLink = null;
    if (!ui.house.canEnterHouse()) return;
    state.recordLink = record;
    enterHouse();
  }

  function bindControls() {
    $("orders").hidden = !state.config.fixture;
    $("demo-path").onchange = (event) => {
      if (!state.sharing) state.draftPath = event.target.value;
    };
    $("orders").addEventListener("click", (event) => {
      const button = event.target.closest("[data-order]");
      if (button) ui.phone.chooseOrder(button.dataset.order);
    });
    document.querySelectorAll("[data-page]").forEach((button) => {
      button.onclick = () => {
        notice();
        if (button.dataset.page === "house" && state.page === "reason") {
          if (canUsePhoneMap()) enterHouse();
        }
        else showPage(button.dataset.page);
      };
    });
    $("timeline").addEventListener("click", (event) => {
      const button = event.target.closest("[data-step]");
      if (button) ui.house.goHouse(Number(button.dataset.step));
    });
    $("presenter-controls").addEventListener("click", (event) => {
      const button = event.target.closest("[data-presenter]");
      if (button) void presenterAction({ name: button.dataset.presenter, event: button.dataset.event });
    });
    $("phone-map").onclick = () => {
      if (state.sharing || state.homeBusy || !canUsePhoneMap()) return;
      state.mapOpen = true;
      $("phone-content").scrollTop = 0;
      document.querySelectorAll(".flight").forEach((clone) => clone.remove());
      if (state.page === "reason") return enterHouse();
      ui.phone.renderPhone();
    };
    $("phone-order").onclick = () => {
      state.mapOpen = false;
      state.recordOpen = false;
      state.draft = false;
      $("phone-content").scrollTop = 0;
      ui.phone.renderPhone();
      renderControls();
    };
    $("phone-content").onclick = (event) => {
      const button = event.target.closest("button[data-reaction]");
      if (button?.dataset.reaction) return ui.phone.react(button.dataset.card, button.dataset.task, button.dataset.reaction);
    };
    $("previous").onclick = () => move(-1);
    $("next").onclick = () => move(1);
    document.addEventListener("keydown", (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.repeat ||
        event.target.closest("input, textarea, select")) return;
      if (event.key.toLowerCase() === "r") {
        location.href = "/demo?recordings";
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        move(event.key === "ArrowRight" ? 1 : -1);
      }
    });
    window.addEventListener("resize", fit);
    fit();
  }

  return {
    clockNow, renderControls, enterHouse, canUsePhoneMap, resolveHouseLink, readClock, moveClockTo,
    bindControls, tickClock,
  };
}
