import { rehearsalControls } from "./wire.js";
import { buildPresenterCues, canObserveLine } from "./presenter-cues.js";

export function createPresenter(context, ui) {
  const { state, observe, RECORDING, QUIET_END, notice, exchange, sleep, $, REPLAY, MANUAL, PHONE_CLOCK } = context;

  // The Hub and Simulator follow the Server's story clock independently.
  const FIXTURE_LEAD_MS = 5000;
  const RAMP_SECONDS = 4;
  let clockRead;
  let momentRead;
  let pendingCue;

  const missingRoute = (status) => [404, 405, 501].includes(status);

  function markClockMissing(status) {
    if (!missingRoute(status)) return;
    state.clockMissing = true;
    state.clock = null;
    renderControls();
  }

  function momentsPath(episodeId) {
    const query = episodeId && !state.config.fixture ? `?${new URLSearchParams({ episode_id: episodeId })}` : "";
    return "/demo/api/server/v1/demo/moments" + query;
  }

  function readMoments(episodeId) {
    return observe("moments", momentsPath(episodeId), { signal: AbortSignal.timeout(2500) },
      { transform: (data) => data.filter((entry) => !entry.episode_id || entry.episode_id === episodeId) });
  }

  // The rehearsal clock is optional. Stop polling it when the peer says it is unavailable.
  function readClock() {
    if (!state.config.server || state.clockMissing) return null;
    const { reader } = state;
    if (clockRead && clockRead.reader === reader) return clockRead.pending;
    const pending = observe("clock", "/demo/api/server/v1/demo/clock", { signal: AbortSignal.timeout(2500) })
      .then(async (clock) => {
        if (state.reader !== reader) return null;
        if (!(clock.version < state.clock?.version)) state.clock = clock;
        const ready = state.chain.ready.hub;
        if (!momentRead || momentRead.reader !== reader || momentRead.ready !== ready) {
          try {
            const moments = await readMoments(state.episodeId);
            if (state.reader !== reader) return null;
            state.publishedMoments = moments;
            state.clockMoments = true;
            momentRead = { reader, ready };
          } catch ({ status }) {
            if (state.reader !== reader) return null;
            if (missingRoute(status)) momentRead = { reader, ready };
          }
        }
        renderControls();
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

  function clockOptions(signal) {
    const timeout = AbortSignal.timeout(12000);
    return {
      method: "POST", headers: { "Content-Type": "application/json" },
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    };
  }

  async function postClock(target, options, reader) {
    const clock = await observe("clock", "/demo/api/clock", {
      ...options, body: JSON.stringify({ advance_to: new Date(target).toISOString(), over_seconds: RAMP_SECONDS }),
    });
    if (state.reader === reader && !state.clockMissing && !(clock.version < state.clock?.version)) state.clock = clock;
    return clock;
  }

  async function moveClockTo(scene, { episodeId, signal } = {}) {
    if (state.resetting || !await readClock() || signal?.aborted) return;
    const reader = state.reader;
    const episode = new URLSearchParams({ episode_id: episodeId });
    const moments = await readMoments(episodeId).catch((error) => {
      if (missingRoute(error.status)) return [];
      throw error;
    });
    if (state.clockMissing) return;
    if (state.resetting || state.reader !== reader) return;
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
      const options = clockOptions(signal);
      if (forQuiet || state.config.fixture) {
        await postClock(target, options, reader);
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
    if (REPLAY || state.homeBusy || !ui.house.canEnterHouse()) return false;
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
        if (state.reader !== reader) return false;
        ui.recording.log("presenter", { action: name, status: result.status, result: result.body });
        if (!result.ok) throw Object.assign(new Error(result.status), { status: result.status });
        if (event && result.body?.occurred_at) ui.house.rememberFacts([{ event, at: result.body.occurred_at }]);
        await Promise.allSettled([ui.surface.refreshSnapshot(), ui.surface.refreshHouseMarkers()]);
        focus = [...state.facts].find(([key, fact]) => !before.has(key) && fact.event === (event ?? "person"))?.[1];
      }
      return true;
    } catch (error) {
      if (state.reader === reader) notice(`집에서 확인하지 못했어요. (${error.message})`);
      // A timeout or proxy error may follow a World write. Keep waiting for its observation.
      if (error.status >= 400 && error.status < 500 && error.status !== 408) return false;
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

  const inTimeCue = (cue, { id, at }) => cue.momentIds.includes(id) && Date.parse(at) === cue.target;
  const waitingForTimeCue = (cue, moments) => moments.some((moment) =>
    inTimeCue(cue, moment) && !moment.ready && moment.lines.some(canObserveLine));

  function cueMomentIndex(cue, moments) {
    if (cue.kind === "time") {
      return waitingForTimeCue(cue, moments) ? -1
        : moments.findLastIndex((moment) => moment.ready && inTimeCue(cue, moment));
    }
    const index = moments.findLastIndex(({ event, ready }) => ready && event === cue.event);
    if (index < 0 || cue.event !== "guest_arrived") return index;
    const device = moments.findIndex(({ follows, ready }) => ready && follows === moments[index].id);
    const waiting = moments.some(({ event, follows, ready, lines }) => !ready &&
      (event === cue.event || follows === moments[index].id) && lines.some(canObserveLine));
    return device >= 0 ? device : waiting ? -1 : index;
  }

  function nextCue(moments, current) {
    const clock = Boolean(state.clock && !state.cueClockMissing);
    const relations = state.hub?.plan_lines?.[state.episodeId] ?? {};
    const guestWindows = Object.fromEntries(Object.entries(relations).flatMap(([id, { trigger }]) =>
      trigger?.event === "guest_arrived" && trigger.window ? [[id, trigger.window]] : []));
    const cues = buildPresenterCues({
      path: state.draft || !state.episodeId ? ui.phone.draftPath() : state.runPath, chain: state.chain, timeline: moments,
      published: momentRead?.reader === state.reader ? state.publishedMoments : undefined,
      guestWindows: { ...guestWindows, ...state.hub?.guest_windows?.[state.episodeId] }, clock,
    });
    const named = (id) => cues.find((cue) => cue.id === id);
    if (state.sharing) return { wait: "주문 접수" };
    if (!state.episodeId || state.draft) return state.config.server ? named("share") : { wait: "서버 연결" };
    if (state.page === "reason") {
      if (state.step >= ui.reasoning.reasonStep("plan") && (state.cardOpen || !state.cards.length)) {
        if (named("house")) return canUsePhoneMap() ? named("house") : { wait: "집의 계획 수신" };
        return state.chain.cardReady || state.readProblems.cards ? {} : { wait: "준비 카드" };
      }
      if (state.cardOpen) return { wait: "준비 계획" };
      if ((state.cards.length && ui.reasoning.canPresentCard()) ||
          (MANUAL && !state.auto && ui.reasoning.canMoveReasonForward())) return named("card");
      return { wait: "준비 카드와 판단 장면" };
    }
    if (state.recordRequested) return state.recordVisible ? {} : { wait: "관찰 결과와 이 집의 기억" };
    if (!state.snapshot || !state.houseMarkup) return { wait: "집 상태" };
    if (!state.clockMissing && !state.cueClockMissing && (momentRead?.reader !== state.reader || !momentRead?.ready)) {
      return { wait: "시연 시계 확인" };
    }
    const now = clockNow() ?? Date.now();
    for (const cue of cues.filter(({ kind }) => kind)) {
      const index = cueMomentIndex(cue, moments);
      if (index >= 0 && index <= current) continue;
      const observed = index >= 0 || moments.some(({ event, ready }) => ready && event === cue.event);
      if (!observed && cue.until !== undefined && now >= cue.until) continue;
      if (!observed && !clock && cue.target > now) return { wait: cue.label + " 시각" };
      return cue;
    }
    return named("record") ?? {};
  }

  function updateCue(moments, index) {
    if (pendingCue?.reader !== state.reader) pendingCue = null;
    if (pendingCue && !pendingCue.running) {
      const { cue } = pendingCue;
      const observed = cueMomentIndex(cue, moments);
      const noTimedResult = cue.kind === "time" &&
        (state.clockMissing || state.cueClockMissing || !waitingForTimeCue(cue, moments));
      if (observed >= 0 || noTimedResult) {
        pendingCue = null;
        if (observed >= 0 && state.page === "house" && ui.house.goHouse(observed)) return;
      }
    }
    const next = REPLAY ? { id: "replay", label: "다음 →" } : pendingCue ? { wait: pendingCue.wait } : nextCue(moments, index);
    const button = $("next-cue");
    button.disabled = REPLAY ? $("next").disabled : Boolean(!next.id || state.homeBusy || state.reactionPending || state.resetting);
    const label = REPLAY ? next.label : next.label ? `다음: ${next.label}` : next.wait ? `대기 · ${next.wait}` : "시연 완료";
    if (button.textContent !== label) button.textContent = label;
  }

  async function advanceCueClock(target, reader) {
    if (!state.clock || target === undefined || clockNow() >= target) return;
    const { signal } = reader;
    const clock = await postClock(target, clockOptions(signal), reader);
    if (state.reader !== reader) return;
    ui.recording.log("presenter", { action: "clock", status: 200, result: clock });
    await sleep(RAMP_SECONDS * 1000 + 300);
    if (state.reader === reader && clockNow() < target) {
      await readClock();
      if (clockNow() < target) throw new Error("시연 시각을 확인하지 못했어요.");
    }
  }

  async function pressNext() {
    if (REPLAY) return move(1);
    if (pendingCue || state.sharing || state.homeBusy || state.reactionPending || state.resetting) return;
    const moments = ui.house.timeline();
    const cue = nextCue(moments, moments.indexOf(ui.house.currentMoment(moments)));
    if (cue.id === "share") {
      if (!state.config.fixture) return $("files")?.click();
      if (await ui.phone.shareSample()) ui.reasoning.autoAdvance({ cue: true });
      return;
    }
    if (cue.id === "card") {
      ui.phone.openCard();
      ui.reasoning.autoAdvance({ cue: true });
      return;
    }
    if (cue.id === "house") return $("phone-map").onclick();
    if (cue.id === "record") return ui.house.openRecord();
    if (!cue.kind) return;
    const observed = cueMomentIndex(cue, moments);
    if (observed >= 0) return ui.house.goHouse(observed);
    const { reader } = state;
    const waiting = cue.target > (clockNow() ?? Date.now()) ? "시각" : "결과";
    const pending = pendingCue = { reader, cue, running: true, wait: `${cue.label} ${waiting}` };
    renderControls();
    try {
      await advanceCueClock(cue.target, reader);
      if (state.reader !== reader) return;
      pending.wait = cue.kind === "time" ? cue.label + " 기기 상태" : cue.label + " 결과";
      renderControls();
      if (cue.kind === "event" && !ui.house.timeline().some(({ ready, event }) => ready && event === cue.event)) {
        if (cue.until !== undefined && (clockNow() ?? Date.now()) >= cue.until) {
          throw new Error("손님을 맞이할 시간이 지났어요.");
        }
        if (await presenterAction(cue) === false) pendingCue = null;
      }
    } catch (error) {
      if (state.reader !== reader) return;
      pendingCue = null;
      if (missingRoute(error.status)) state.cueClockMissing = true;
      else notice(error.status ? `시연 시각을 확인하지 못했어요. (${error.status})` : error.message);
    } finally {
      if (state.reader === reader) {
        pending.running = false;
        renderControls();
      }
    }
  }

  function renderControls() {
    const inHouse = state.page === "house";
    const blocked = state.sharing || state.homeBusy || state.resetting;
    for (const id of ["reset-drawer", "reset-notice"]) {
      $(id).hidden = REPLAY || !state.config.reset;
      $(id).disabled = blocked || Boolean(state.reactionPending);
    }
    $("reset-scope").hidden = $("reset-drawer").hidden || Boolean(state.config.fixture);
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
    $("clock-unavailable").hidden = !(clock.unavailable || state.cueClockMissing);
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
    updateCue(moments, index);
  }

  async function resetDemo() {
    if ($("reset-drawer").hidden || $("reset-drawer").disabled) return;
    const message = state.config.fixture
      ? "집과 판단 기록을 처음 상태로 돌려요. 녹화는 남아요."
      : "이 컴퓨터의 Hub와 집 상태를 처음으로 돌려요. 서버의 주문과 판단 기록, 녹화는 남아요.";
    if (!window.confirm(message)) return;
    state.resetting = true;
    $("phone-dock").inert = $("right-area").inert = true;
    $("reset-status").textContent = "처음 상태로 돌리는 중이에요…";
    renderControls();
    let reloading = false;
    try {
      if (state.record && !state.recordFinished) {
        ui.recording.log("presenter", { action: "reset" });
        ui.recording.log("finish", { stage: "reset" });
        state.recordFinished = true;
      }
      state.record = null;
      if (state.recordingSaved) {
        const saved = await Promise.race([state.recordingSaved().then(() => true), sleep(15000).then(() => false)]);
        if (!saved) {
          $("reset-status").textContent = "녹화를 아직 저장하지 못했어요. 다시 시도해 주세요.";
          return;
        }
      }
      const { status } = await exchange("/demo/api/reset", { method: "POST" });
      if (status === 204) {
        location.replace("/demo");
        reloading = true;
        return;
      }
      $("reset-status").textContent = status === 409
        ? "이미 처음 상태로 돌리는 중이에요."
        : "새로 시작하지 못했어요. 다시 시도해 주세요.";
    } catch {
      $("reset-status").textContent = "새로 시작하지 못했어요. 다시 시도해 주세요.";
    } finally {
      if (!reloading) {
        state.resetting = false;
        $("phone-dock").inert = $("right-area").inert = false;
        renderControls();
      }
    }
  }

  function move(delta) {
    if (state.sharing || state.homeBusy || state.resetting) return;
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
      if (!state.sharing) {
        state.draftPath = event.target.value;
        renderControls();
      }
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
    $("next-cue").onclick = pressNext;
    $("reset-drawer").onclick = $("reset-notice").onclick = resetDemo;
    document.addEventListener("keydown", (event) => {
      if (state.resetting || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.repeat ||
        event.target.closest("input, textarea, select, #reset-drawer, #reset-notice")) return;
      if (event.key.toLowerCase() === "r") {
        location.href = "/demo?recordings";
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        move(-1);
      } else if (event.key === "ArrowRight" || (event.key === " " && !event.target.closest("summary"))) {
        event.preventDefault();
        void pressNext();
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
