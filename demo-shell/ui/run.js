import { withSceneArtwork } from "./artwork/scene.js";

export function createRecorder(api, config, episodeId, demoPath, onError) {
  const id = crypto.randomUUID().replaceAll("-", "");
  const queue = [];
  let offset = 0;
  let writing = false;
  let closed = false;
  let saved;

  async function flush() {
    if (writing || !queue.length) return;
    writing = true;
    const entries = queue.slice(0, 100);
    try {
      const body = JSON.stringify({
        episode_id: episodeId, household_id: config.household_id,
        story_timing: config.story_timing, demo_path: demoPath, offset, entries,
      });
      const result = await api(`/demo/api/recordings/${id}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body,
        keepalive: new TextEncoder().encode(body).length < 60 * 1024, signal: AbortSignal.timeout(5000),
      });
      if (result.offset !== offset + entries.length) throw new Error("Recording offset did not advance");
      offset = result.offset;
      queue.splice(0, entries.length);
      writing = false;
      if (!queue.length && saved) {
        saved.resolve();
        saved = undefined;
      }
      void flush();
    } catch {
      onError();
      setTimeout(() => {
        writing = false;
        void flush();
      }, 2000);
    }
  }

  function record(kind, data, arrivedAt, storyAt, read) {
    if (closed && !["house", "scene"].includes(kind)) return;
    closed ||= kind === "finish";
    queue.push({ kind, data, arrived_at: arrivedAt, story_at: storyAt, read });
    void flush();
  }
  function whenSaved() {
    if (!queue.length) return Promise.resolve();
    saved ??= Promise.withResolvers();
    return saved.promise;
  }

  return { id, record, whenSaved };
}

export function replayFrames(entries, wording) {
  let current = {};
  let visit;
  let judgment;
  const house = [];
  const applied = new Map();
  for (const { kind, data, story_at, read } of entries) {
    const source = kind === "read_problem" ? data.source : kind === "rationale_missing" ? "rationale" : kind;
    if (read != null) {
      if (read < (applied.get(source) ?? 0)) continue;
      applied.set(source, read);
    }
    if (kind === "presenter") visit = undefined;
    if (story_at) current = { ...current, storyAt: Date.parse(story_at) };
    if (["episode", "rationale", "cards", "memory"].includes(kind)) {
      current = { ...current, readProblems: { ...current.readProblems, [kind]: null } };
    }
    if (kind === "read_problem") {
      current = { ...current, readProblems: { ...current.readProblems, [source]: data.problem } };
    } else if (kind === "house") {
      judgment ??= { ...current };
      const legacyKind = ["plan", "delivery", "guests", "end"].includes(data.scene) ? data.scene : "line";
      const moment = data.moment ?? {
        id: data.scene, kind: legacyKind, room: "overview", story: "", focusDevices: [], ...wording?.[legacyKind],
      };
      visit = { moment: { ...moment, ready: true }, scenes: [], frame: current };
      house.push(visit);
    } else if (kind === "scene" && visit && data.scene?.moment === visit.moment.id) {
      const scene = withSceneArtwork(data.scene, data.artwork);
      visit.scenes.push({ frame: current, scene, moment: data.moment });
    } else if (kind === "finish" && data.stage === "record") {
      current = { ...current, finalMemory: true };
    } else if (kind === "rationale_missing") {
      current = { ...current, rationaleMissing: true };
    } else if (kind === "rationale") {
      current = { ...current, rationale: data, rationaleMissing: false };
    } else if (kind === "cards") {
      const cards = new Map((current.cards ?? []).map((card) => [card.card_id, card]));
      for (const card of data.cards) {
        if (!(Date.parse(card.updated_at) < Date.parse(cards.get(card.card_id)?.updated_at))) {
          cards.set(card.card_id, card);
        }
      }
      current = { ...current, cards: [...cards.values()] };
    } else if (["episode", "hub", "snapshot", "viewer", "memory"].includes(kind)) {
      current = { ...current, [kind]: data };
    }
    if (visit) visit.frame = current;
  }
  return { judgment: judgment ?? current, house };
}
