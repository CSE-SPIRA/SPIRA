import { sendScene } from "./scene-rules.js";

export function createRecordingPlayback(context, ui) {
  const { state, DWELL_MS, sleep } = context;

  function stamp(story = ui.presenter.clockNow() ?? (state.config?.fixture ? null : Date.now())) {
    return [new Date().toISOString(), Number.isFinite(story) ? new Date(story).toISOString() : null];
  }

  function log(kind, data, at = stamp()) {
    state.record?.(kind, data, ...at);
  }

  function recordedMoment({ id, kind, at, story, title, lead, room, signal, focusDevices, lines }) {
    return { id, kind, at, story, title, lead, room, signal, focusDevices,
      lines: lines?.map(({ observed }) => ({ observed: observed.map(({ device }) => ({ device })) })) };
  }

  function applyReplayFrame(frame) {
    if (!frame) return;
    state.episode = frame.episode ?? null;
    state.rationale = frame.rationale ?? null;
    state.rationaleMissing = Boolean(frame.rationaleMissing);
    state.readProblems = frame.readProblems ?? {};
    state.cardsRead = Boolean(frame.cards);
    state.cards = frame.cards ?? [];
    state.hub = frame.hub ?? null;
    state.snapshot = frame.snapshot ?? null;
    state.memory = frame.memory;
    state.finalMemory = Boolean(frame.finalMemory && frame.memory);
    state.replayTime = frame.storyAt;
    ui.reasoning.refreshChain();
    ui.surface.applyHouseMarkers(frame.viewer);
    ui.surface.revealHouseState();
  }

  function flushReplayScenes() {
    if (!state.house || !state.replayPending?.length) return;
    for (const { frame, scene, moment } of state.replayPending.splice(0)) {
      applyReplayFrame(frame);
      if (scene) sendScene(state.house, state.validateScene, scene);
      else state.house.clearScene();
      if (moment) {
        ui.house.updateHousePresentation(moment);
        ui.house.directHouse(moment);
      }
    }
  }

  function playReplayVisit() {
    const visit = state.replay.house[state.replayStep];
    clearTimeout(state.replaySceneTimer);
    state.replayPending ??= [];
    const previous = state.replayVisit;
    if (previous) state.replayPending.push(...previous.scenes.slice(state.replaySceneIndex));
    state.replayVisit = visit;
    state.replaySceneIndex = 0;
    applyReplayFrame(visit.scenes[0]?.frame ?? visit.frame);

    const dwell = DWELL_MS ?? 6500;
    const showNext = () => {
      const next = visit.scenes[state.replaySceneIndex++];
      state.replayPending.push(next ?? { frame: visit.frame, moment: visit.moment });
      flushReplayScenes();
      if (state.replaySceneIndex < visit.scenes.length) {
        state.replaySceneTimer = setTimeout(showNext, dwell / visit.scenes.length);
      }
    };
    showNext();
    if (state.page === "house") ui.house.renderTimeline();
  }

  async function playRecordedHouse() {
    const playback = {};
    state.auto = playback;
    while (state.auto === playback && state.page === "house" && !state.recordRequested) {
      await sleep(DWELL_MS ?? 6500);
      if (state.auto !== playback || state.page !== "house") return;
      if (state.replayStep < ui.house.timeline().length - 1) ui.house.goHouse(state.replayStep + 1);
      else {
        if (ui.house.houseEnded(ui.house.timeline())) {
          applyReplayFrame(state.replay.house.at(-1).frame);
          ui.house.openRecord();
        }
        break;
      }
    }
    if (state.auto === playback) state.auto = null;
  }

  return {
    log, stamp, recordedMoment, playReplayVisit, playRecordedHouse, applyReplayFrame, flushReplayScenes,
  };
}
