import { readProblem, reactionConfirmed, startedLines } from "./wire.js";
import { createRecorder } from "./run.js";

export function createEpisodeReader(context, ui) {
  const { state, REPLAY, defaultPath, api, $, notice, QUIET_END, sleep, observe, RECORDING } = context;

  let episodeRead = 0;
  let appliedEpisodeReads = {};

  function acceptEpisodeRead(id, read, source, { episode, rationale, rationaleMissing, cards, cursor, problem = null }) {
    if (id !== state.episodeId || read < (appliedEpisodeReads[source] ?? 0)) return;
    appliedEpisodeReads[source] = read;
    acceptReadProblem(source, problem, read);
    if (episode) state.episode = episode;
    if (rationale) state.rationale = rationale;
    if (rationaleMissing != null) state.rationaleMissing = rationaleMissing;
    if (cursor) state.cardCursor = cursor;
    if (cards) {
      state.cardsRead = true;
      const current = new Map(state.cards.map((card) => [card.card_id, card]));
      for (const card of cards) {
        if (card.episode_id !== id || Date.parse(card.updated_at) < Date.parse(current.get(card.card_id)?.updated_at)) continue;
        current.set(card.card_id, card);
        const key = JSON.stringify([card.card_id, card.updated_at]);
        if (!REPLAY && card.notify && !state.dismissed.has(key)) state.notifications.add(key);
      }
      state.cards = [...current.values()];
      const pending = state.reactionPending;
      if (pending && (state.episode?.status === "closed" || reactionConfirmed(current.get(pending.cardId), pending))) {
        state.reactionPending = null;
      }
    }
    state.started = startedLines(state.started, state.cards, state.rationale?.executions);
    ui.reasoning.refreshChain();
    ui.presenter.resolveHouseLink();
  }

  function acceptReadProblem(source, problem, read) {
    if (state.readProblems[source] === problem) return;
    if (problem) state.record?.("read_problem", { source, problem }, ...ui.recording.stamp(), read);
    state.readProblems[source] = problem;
  }

  const ARCHIVE = "1970-01-01T00:00:00Z";
  function cardsPath(since) {
    const path = `/demo/api/server/v1/households/${encodeURIComponent(state.config.household_id)}/cards`;
    return since ? `${path}?since=${encodeURIComponent(since)}` : path;
  }

  async function readEpisode(id, share) {
    state.reader?.abort();
    const controller = new AbortController();
    state.reader = controller;
    if (state.episodeId !== id || share) {
      state.episodeId = id;
      state.runPath = share?.demoPath ?? state.config.demo_path ?? (state.config.fixture || REPLAY ? defaultPath(id) : "house");
      state.tags = [];
      state.tagsReady = state.tagsRead = null;
      state.episode = state.rationale = state.hub = state.snapshot = null;
      state.houseMarkup = "";
      state.markerSignature = null;
      state.homeId = "plan";
      state.followGuest = false;
      state.facts.clear();
      state.pendingClockLines.clear();
      state.playedMotion.clear();
      state.appliedScene = state.cameraMoment = state.roomCameraMoment = state.displayReadings = null;
      state.homeBusy = false;
      state.house?.clearScene();
      ui.surface.revealHouseState();
      state.rationaleMissing = false;
      state.readProblems = {};
      state.cardsRead = false;
      state.shownAt = null;
      state.cards = [];
      state.cardCursor = null;
      state.notifications.clear();
      state.started = new Set();
      state.reactionPending = null;
      state.controlError = "";
      state.houseOnReceipt = state.memoryOpen = false;
      state.finalMemory = state.recordRequested = state.recordVisible = state.recordFinished = false;
      state.quietEnd = null;
      state.waiting = undefined;
      state.retryUntil = 0;
      if (share && state.config.fixture) {
        state.clock = null;
      }
      if (!REPLAY) {
        const recorder = createRecorder(api, state.config, id, state.runPath, () => {
          if (state.reader === controller && !$("notice").textContent) notice("녹화를 다시 저장하고 있어요.");
        });
        state.record = recorder.record;
        state.recordingSaved = recorder.whenSaved;
        state.runId = recorder.id;
        if (share) ui.recording.log("share", share.data, share.at);
      }
      if (share && state.config.fixture) void ui.presenter.readClock();
    }
    ui.reasoning.refreshChain();
    for (;;) {
      await refreshCards(state.cardCursor ?? "", 12000);
      if (controller.signal.aborted) return;
      if (state.episode?.card_ids?.some((cardId) => !state.cards.some(({ card_id }) => card_id === cardId))) {
        await readCards(id, ++episodeRead, ARCHIVE, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]),
        }).catch(() => {});
        if (controller.signal.aborted) return;
      }
      if (state.config.fixture && state.clock && !REPLAY && state.episode?.status === "reading" &&
        state.chain.ready.extract && !state.quietRamped.has(id) && state.quietEnd === null) {
        ui.presenter.moveClockTo(QUIET_END, { episodeId: id, signal: controller.signal }).catch(() => {});
      }
      if (state.episode?.status === "read_failed") return;
      if (state.episode?.status === "closed" && ui.phone.recordReady()) return;
      if (state.chain.cardReady && state.chain.hasEpisode &&
        (state.judgment.some(({ id }) => id === "tasks") || ui.reasoning.missingJudgment())) return;
      if (!state.config.fixture && state.chain.cardReady && state.readProblems.rationale) return;
      await sleep(1000);
      if (controller.signal.aborted) return;
    }
  }

  function renderArrival() {
    if (state.page === "house") ui.house.renderTimeline();
    else ui.reasoning.renderReason();
  }

  async function readCards(id, read, since, options) {
    const { reader } = state;
    let payload;
    try {
      const body = await observe("cards", cardsPath(since), options, {
        read,
        transform: (data) => ({ ...data, cards: data.cards.filter(({ episode_id }) => episode_id === id) }),
      });
      payload = { cards: body.cards, cursor: body.server_time };
    } catch (error) {
      const problem = readProblem(error.status);
      // The full read establishes whether the cards route is present. A cursor
      // or archive read must not override its result.
      if (state.config.fixture || !problem || (since && problem === "missing")) return;
      payload = { problem };
    }
    if (state.reader !== reader) return;
    acceptEpisodeRead(id, read, "cards", payload);
    renderArrival();
  }

  async function refreshCards(since = state.cardCursor ?? ARCHIVE, timeout = 4000) {
    const { episodeId, reader } = state;
    if (!episodeId || RECORDING) return;
    const read = ++episodeRead;
    const episodePath = `/demo/api/server/v1/episodes/${encodeURIComponent(episodeId)}`;
    const deadline = AbortSignal.timeout(timeout);
    const options = { signal: reader ? AbortSignal.any([reader.signal, deadline]) : deadline, headers: {
      ...(state.runId ? { "X-SPIRA-Demo-Run": state.runId } : {}),
      ...(REPLAY ? { "X-SPIRA-Demo-Replay": "1" } : {}),
    } };
    const detail = async (kind, path) => {
      let payload;
      try {
        const value = await observe(kind, path, options, { read });
        if (value.episode_id !== episodeId || (kind === "episode" && value.household_id !== state.config.household_id)) return;
        payload = { [kind]: value, ...(kind === "rationale" ? { rationaleMissing: false } : {}) };
      } catch (error) {
        if (state.reader !== reader || options.signal.aborted) return;
        if (!state.config.fixture) {
          const problem = readProblem(error.status);
          if (problem) payload = { problem };
        } else if (error.status !== 404) return;
        else if (kind === "rationale") {
          payload = { rationaleMissing: true };
          state.record?.("rationale_missing", null, ...ui.recording.stamp(), read);
        }
        else if (!state.episode && !state.sharing && state.page === "reason" && state.sharedEpisode !== episodeId) {
          notice("아직 이 주문 기록을 열 수 없어요. 예시 주문을 공유해 주세요.");
        }
      }
      if (!payload || state.reader !== reader) return;
      acceptEpisodeRead(episodeId, read, kind, payload);
      renderArrival();
    };
    await Promise.allSettled([
      detail("episode", episodePath), detail("rationale", `${episodePath}/rationale`),
      readCards(episodeId, read, since, options),
    ]);
  }

  // The house's ending hook redraws the episode and observation data just read by refreshCards.
  function refreshMemory() {
    if (state.page === "house") ui.house.renderTimeline();
  }

  async function readTags() {
    const { reader, runId, episodeId } = state;
    if (!runId || state.tagsReady || state.tagsRead === reader) return;
    state.tagsRead = reader;
    try {
      const result = await api(`/demo/tags?episode=${encodeURIComponent(episodeId)}`, {
        headers: { "X-SPIRA-Demo-Run": runId },
        signal: AbortSignal.any([reader.signal, AbortSignal.timeout(2500)]),
      });
      if (state.reader !== reader) return;
      state.tagsReady = result.ready;
      state.tags = result.tags;
      renderArrival();
    } catch {
      // The text is already on stage, and the next poll can retry.
    } finally {
      if (state.tagsRead === reader) state.tagsRead = null;
    }
  }

  return {
    readEpisode, refreshCards, readTags, refreshMemory,
  };
}
