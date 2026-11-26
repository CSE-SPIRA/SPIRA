import { ROOM_NAMES } from "/demo/shared/vocabulary.js";
import { houseDevicePresentation } from "./chain.js";
import { esc, rows } from "./markup.js";
import { withSceneArtwork } from "./artwork/scene.js";
import { buildMoments, closeView, momentScene, sendScene } from "./scene-rules.js";

export function createHouseTimeline(context, ui) {
  const { state, RECORDING, $, notice, REPLAY, observe, sleep } = context;

  function canEnterHouse() {
    return Boolean(state.episodeId && state.runPath === "house" && state.chain.ready.hub &&
      (!RECORDING || state.replay?.house.length));
  }

  function timeline() {
    if (RECORDING) return state.replay?.house.map(({ moment }) => moment) ?? [];
    return buildMoments({
      chain: state.chain, actions: state.hub?.plan_actions?.[state.episodeId],
      relations: state.hub?.plan_lines?.[state.episodeId],
      facts: [...state.facts.values()], tags: state.tags,
      wording: state.scenes.house, since: state.episode?.shared_at,
    });
  }

  function currentMoment(scenes = timeline()) {
    return RECORDING ? scenes[state.replayStep] : scenes.find(({ id }) => id === state.homeId) ?? scenes[0];
  }

  function observedGuestLine(moment, moments) {
    return moments.find(({ follows, ready }) => ready && follows === moment.id);
  }

  function selectHouseMoment(moment) {
    state.homeId = moment.id;
    ui.recording.log("house", { moment: ui.recording.recordedMoment(moment) });
  }

  function updateHousePresentation(moment) {
    state.house?.setPresentation(houseDevicePresentation(state.chain, moment?.focusDevices, moment?.title));
  }

  function updateScene(moment, moments) {
    if (!state.house || RECORDING || state.recordVisible) return;
    const motionKey = (line) => JSON.stringify([moment.id, line]);
    const result = momentScene(moment, {
      moments, items: state.chain.items, itemTasks: state.chain.item_tasks,
      itemTypes: state.itemTypes, vocabulary: state.sceneVocabulary,
      snapshot: state.snapshot, displayReadings: state.displayReadings ?? null,
      devices: state.chain.devices, showArtwork: state.config.fixture,
      canPlay: (line) => !state.playedMotion.has(motionKey(line)),
    });
    if (!result) {
      state.house.clearScene();
      state.appliedScene = null;
      return;
    }
    const { scene, artwork, motions } = result;
    // A poll must not reset a scene or restart a motion that the audience already saw.
    const stable = JSON.stringify({ ...scene, artwork, slots: scene.slots.slice(0, scene.slots.length - motions.length) });
    if (state.appliedScene === stable && !motions.length) return;
    if (sendScene(state.house, state.validateScene, withSceneArtwork(scene, artwork), () =>
      ui.recording.log("scene", { moment: ui.recording.recordedMoment(moment), scene, artwork }))) {
      state.appliedScene = stable;
      for (const line of motions) state.playedMotion.add(motionKey(line));
    }
  }

  function renderTimeline({ instant = false, follow = true } = {}) {
    ui.phone.renderEnding();
    ui.phone.renderPhone();
    const moments = timeline();
    let current = currentMoment(moments);
    if (!current) return;
    if (follow && state.followGuest && !state.homeBusy) {
      const observed = observedGuestLine(current, moments);
      if (observed) {
        state.followGuest = false;
        selectHouseMoment(observed);
        current = observed;
      }
    }
    updateHousePresentation(current);
    updateScene(current, moments);
    directHouse(current, instant);
    $("home-time").textContent = current.story;
    $("home-title").textContent = current.title;
    $("home-caption").textContent = current.lead ?? "";
    $("home").setAttribute("aria-busy", String(state.homeBusy));
    const steps = $("timeline");
    const selected = RECORDING ? state.replayStep : moments.indexOf(current);
    const markup = rows(moments, (moment, index) => `<li><button type="button" data-step="${index}"
    ${index === selected ? 'aria-current="step"' : ""}
    ${index < selected && moment.ready ? 'class="past"' : ""}
    ${state.homeBusy || !moment.ready ? "disabled" : ""}>
    ${moment.story ? `<time>${esc(moment.story)}</time>` : ""}
    <span>${esc(moment.title)}</span>${moment.ready ? "" : `<small>${moment.state === "off" ? "꺼짐" : "대기"}</small>`}
    </button></li>`);
    if (steps.dataset.content !== markup) {
      const focused = steps.contains(document.activeElement);
      steps.dataset.content = markup;
      steps.innerHTML = markup;
      if (focused) (steps.querySelector('[aria-current="step"]:enabled') || $("next")).focus({ preventScroll: true });
    }
    ui.presenter.renderControls();
    if (state.recordLink) {
      const end = moments.findLastIndex(({ kind, ready }) => kind === "end" && ready);
      if (end >= 0) {
        state.recordLink = false;
        goHouse(end);
        openRecord();
      }
    }
  }

  const CLOSEUP_MS = 6000;
  let closeupTimer = 0;

  function roomCamera(room) {
    // Older offline recordings may have cached a renderer without room presets.
    const cameras = state.houseModule?.HOUSE_ROOM_VIEWS ?? {};
    if (Object.hasOwn(cameras, room)) return cameras[room];
    if (Object.hasOwn(state.scenes.cameras, room)) return state.scenes.cameras[room];
  }

  function selectRoomCamera(room) {
    for (const button of document.querySelectorAll(".room-key [data-room]")) {
      button.setAttribute("aria-pressed", String(button.dataset.room === room));
    }
  }

  function directHouse(moment, instant = false) {
    if (!state.house) return;
    state.house.setEntrance({ signal: moment.signal ?? "", packagePresent: moment.signal === "package" });
    if (state.roomCameraMoment === moment.id) return;
    state.roomCameraMoment = null;
    const close = closeView(moment, state.chain.devices);
    const key = JSON.stringify([moment.id, moment.room, close]);
    if (!instant && key === state.cameraMoment) return;
    state.cameraMoment = key;
    clearTimeout(closeupTimer);
    const room = roomCamera(moment.room) ?? roomCamera("overview");
    const closeup = !instant && close;
    $("view").toggleAttribute("data-closeup", Boolean(closeup));
    selectRoomCamera(closeup ? null : moment.room);
    state.house.focus(closeup || room, { instant });
    if (closeup) {
      closeupTimer = setTimeout(() => {
        if (state.cameraMoment !== key || state.page !== "house") return;
        $("view").removeAttribute("data-closeup");
        selectRoomCamera(moment.room);
        state.house.focus(room);
      }, CLOSEUP_MS);
    }
  }

  function goHouse(index, { followGuest = false } = {}) {
    const moments = timeline();
    const moment = moments[index];
    const selected = RECORDING ? state.replayStep : moments.indexOf(currentMoment(moments));
    if (!moment?.ready || state.homeBusy || index === selected) return false;
    notice();
    state.recordOpen = state.recordRequested = false;
    if (RECORDING) {
      state.replayStep = index;
      ui.recording.playReplayVisit();
      return true;
    }
    state.pendingClockLines.clear();
    state.followGuest = !REPLAY && moment.kind === "guests" && (followGuest || !observedGuestLine(moment, moments));
    selectHouseMoment(moment);
    renderTimeline({ follow: false });
    return true;
  }

  function rememberFacts(facts) {
    for (const fact of facts) {
      const key = JSON.stringify([fact.event, Date.parse(fact.at), fact.device]);
      if (!state.facts.has(key)) state.facts.set(key, fact);
    }
  }

  function acceptHub(hub) {
    state.hub = hub;
    ui.reasoning.refreshChain();
    ui.presenter.resolveHouseLink();
    if (state.page === "reason") ui.reasoning.renderReason();
    else renderTimeline();
  }

  async function refreshHub() {
    const { reader } = state;
    const hub = await observe("hub", "/demo/api/hub", { signal: AbortSignal.timeout(2500) });
    if (state.reader !== reader) return;
    acceptHub(hub);
  }

  async function pollHouse() {
    for (let tick = 0; ; tick += 1) {
      if (state.resetting) {
        await sleep(800);
        continue;
      }
      const inHouse = state.page === "house";
      if (!REPLAY && state.config.tagger && state.episodeId) void ui.episode.readTags();
      const reads = inHouse ? [ui.surface.refreshSnapshot(), ui.surface.refreshHouseMarkers()] : [];
      if ((inHouse || state.houseLink || state.chain.cardReady) && state.episodeId && tick % 4 === 0) {
        const reader = state.reader;
        reads.push(state.recordRequested ? ui.episode.refreshCards().finally(() => {
          if (state.reader === reader && !state.finalMemory) return ui.episode.refreshMemory();
        }) : ui.episode.refreshCards());
      }
      if (state.config.hub) {
        reads.push(refreshHub());
      }
      reads.push(ui.presenter.readClock());
      await Promise.allSettled(reads);
      // A timed read-back can arrive after the clock ramp. Wait for the house poll before presenting it.
      if (inHouse && state.page === "house" && !state.recordRequested && state.pendingClockLines.size) {
        const moment = timeline().find(({ id, ready }) => ready && state.pendingClockLines.has(id));
        if (moment) {
          state.pendingClockLines.delete(moment.id);
          state.followGuest = false;
          selectHouseMoment(moment);
          renderTimeline();
        }
      }
      if (inHouse) void ui.surface.loadHouse();
      await sleep(800);
    }
  }

  function openHouseView() {
    renderTimeline({ instant: true });
    state.house?.resize();
    void ui.surface.loadHouse();
  }

  function houseEnded(moments) {
    return moments.some(({ kind, ready }) => kind === "end" && ready) ||
      RECORDING && state.replay.house.at(-1)?.frame.finalMemory;
  }

  function openRecord() {
    if (!canEnterHouse()) return;
    state.recordOpen = state.recordRequested = true;
    state.mapOpen = false;
    $("phone-content").scrollTop = 0;
    renderTimeline();
    if (!RECORDING) {
      const reader = state.reader;
      void ui.episode.refreshCards().then(() => {
        if (state.reader === reader) return ui.episode.refreshMemory();
      });
    }
  }

  function bindRoomControls() {
    for (const button of document.querySelectorAll(".room-key [data-room]")) {
      const { room } = button.dataset;
      button.textContent = ROOM_NAMES[room];
      button.addEventListener("click", () => {
        const moment = currentMoment();
        if (!state.house || !moment) return;
        clearTimeout(closeupTimer);
        state.roomCameraMoment = moment.id;
        $("view").removeAttribute("data-closeup");
        selectRoomCamera(room);
        state.house.focus(roomCamera(room));
      });
    }
  }

  return {
    canEnterHouse, currentMoment, renderTimeline, timeline, rememberFacts, goHouse, openHouseView, houseEnded,
    openRecord, updateHousePresentation, directHouse, roomCamera, pollHouse, bindRoomControls,
  };
}
