// The App in the phone (README: App in the phone): the App's own web build runs inside the phone frame and calls
// the Server through /demo/app-api/. The right panel follows any new order of the demo household, whether it came
// from this phone or from a real phone, by watching the household's order list.

export const APP_STORE_PREFIX = "flutter.spira.";
const FOLLOW_MS = 1500;

// Orders not in the first list are new; the newest new one is followed (null when none).
export function newestNew(episodes, known, following) {
  const fresh = episodes.filter(({ episode_id }) => !known.has(episode_id));
  for (const { episode_id } of episodes) known.add(episode_id);
  const newest = fresh[0]?.episode_id ?? null;
  return newest && newest !== following ? newest : null;
}

export function clearAppStore(storage) {
  const keys = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key?.startsWith(APP_STORE_PREFIX)) keys.push(key);
  }
  for (const key of keys) storage.removeItem(key);
  return keys.length;
}

export function createAppPhone(context, ui) {
  const { state, $, api } = context;
  let known = null;
  let timer = null;
  let mounted = false;

  function enabled() {
    return Boolean(state.config?.app && !state.serverReplay);
  }

  function mount() {
    if (!enabled() || mounted) return;
    mounted = true;
    const frame = document.createElement("iframe");
    frame.id = "phone-app";
    frame.title = "SPIRA 앱";
    frame.src = "/demo/app/";
    frame.setAttribute("allow", "clipboard-read; clipboard-write");
    document.querySelector("#phone-dock .phone-screen").append(frame);
    $("frame").classList.toggle("app-phone", true);
  }

  function follow(id) {
    state.sharedEpisode = id;
    state.recordOpen = state.draft = state.cardOpen = state.mapOpen = false;
    state.draftPath = null;
    ui.episode.readEpisode(id, { data: { episode_id: id, from: "app" }, at: ui.recording.stamp(), demoPath: "house" });
    ui.reasoning.setStep(0);
    ui.reasoning.autoAdvance();
  }

  async function poll() {
    try {
      const path = `/demo/api/server/v1/households/${encodeURIComponent(state.config.household_id)}/episodes?limit=5`;
      const { episodes = [] } = await api(path);
      if (known === null) {
        known = new Set(episodes.map(({ episode_id }) => episode_id));
      } else {
        const next = newestNew(episodes, known, state.episodeId);
        if (next && !state.resetting) follow(next);
      }
    } catch {
      // The next tick tries again; the log shows the Server state.
    }
  }

  // Watch the household's orders while the page is up (server mode, not a replay, no fixed ?episode=).
  function watch(fixedEpisode) {
    if (!state.config?.server || state.config.fixture || state.serverReplay || fixedEpisode || timer) return;
    timer = true;
    const tick = async () => {
      await poll();
      setTimeout(tick, FOLLOW_MS);
    };
    void tick();
  }

  function clearStore() {
    try {
      return clearAppStore(window.localStorage);
    } catch {
      return 0;
    }
  }

  return { mount, watch, clearStore, enabled };
}
