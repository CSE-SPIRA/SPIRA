import { sendScene } from "./scene-rules.js";

export function createRecordingPlayback(context, ui) {
  const { state } = context;

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
        ui.house.directHouse(moment, true);
      }
    }
    applyReplayFrame(state.replayVisit.frame);
  }

  function playReplayVisit() {
    const visit = state.replay.house[state.replayStep];
    state.replayVisit = visit;
    state.replayPending ??= [];
    state.replayPending.push(...(visit.scenes.length ? visit.scenes : [{ frame: visit.frame, moment: visit.moment }]));
    applyReplayFrame(visit.frame);
    flushReplayScenes();
    if (state.page === "house") ui.house.renderTimeline({ instant: true });
  }

  return { log, stamp, recordedMoment, playReplayVisit, applyReplayFrame, flushReplayScenes };
}
