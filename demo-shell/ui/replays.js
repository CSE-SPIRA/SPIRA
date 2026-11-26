// Server replay (server/spec.md 12.5): keep a finished live run, list kept runs, and play one back by trace `at`.

export const SPEEDS = [1, 2, 4];

export function replayFromQuery(query) {
  const episode = query.get("replay_episode");
  if (!/^ep_[A-Za-z0-9_]+$/.test(episode ?? "")) return null;
  const speed = Number(query.get("speed"));
  return { episode, speed: SPEEDS.includes(speed) ? speed : 1, startedAt: null };
}

// Seconds of the original run shown now; the clock starts on the first trace read.
export function replayAt(replay, now) {
  if (replay.startedAt === null) replay.startedAt = now;
  return ((now - replay.startedAt) / 1000) * replay.speed;
}

export function replayHref(episode, speed) {
  return `/demo?replay_episode=${encodeURIComponent(episode)}&speed=${speed}`;
}

const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

export function startedLabel(iso) {
  const at = iso ? new Date(iso) : null;
  if (!at || Number.isNaN(at.getTime())) return "";
  const two = (n) => String(n).padStart(2, "0");
  return `${two(at.getMonth() + 1)}-${two(at.getDate())} ${two(at.getHours())}:${two(at.getMinutes())}`;
}

export function replayMenu(replays, speed, { live = false } = {}) {
  const speeds = SPEEDS.map((value) =>
    `<button type="button" data-speed="${value}" aria-pressed="${value === speed}">${value}×</button>`).join("");
  const rows = replays === null ? '<p class="replay-empty">불러오는 중…</p>'
    : replays.length === 0 ? '<p class="replay-empty">보관한 실행이 없어요. 라이브 실행이 끝나면 로그 위의 ‘재현용 보관’을 누르세요.</p>'
    : replays.map((r) => `<button type="button" class="replay-row" data-replay="${esc(r.episode_id)}">
        <b>${esc(startedLabel(r.started_at))}</b><span>${esc(r.episode_id)}</span>
        <span>${esc(r.intents.join(", ") || "의도 없음")} · 물건 ${r.items}개${r.duration_s == null ? "" : ` · ${r.duration_s.toFixed(1)}s`}</span>
      </button>`).join("");
  return `<div class="replay-speeds" role="group" aria-label="재현 속도">${speeds}</div>
    <div class="replay-list">${rows}</div>${live ? '<a class="replay-live" href="/demo">라이브로 돌아가기</a>' : ""}`;
}

export function createReplays(context, ui) {
  const { state, $, api, notice } = context;
  let replays = null;
  let speed = state.serverReplay?.speed ?? 1;

  function available() {
    return Boolean(state.config?.server && !state.config.fixture);
  }

  function render() {
    const menu = $("replay-menu");
    menu.innerHTML = replayMenu(replays, speed, { live: Boolean(state.serverReplay) });
  }

  async function load() {
    replays = null;
    render();
    try {
      const body = await api(`/demo/api/server/v1/demo/households/${encodeURIComponent(state.config.household_id)}/replays`);
      replays = body.replays ?? [];
    } catch {
      replays = [];
      notice("보관한 실행 목록을 읽지 못했어요.");
    }
    render();
  }

  function bind() {
    const button = $("replay-top");
    const menu = $("replay-menu");
    button.hidden = !available();
    if (state.serverReplay) button.textContent = `재현 중 · ${state.serverReplay.speed}×`;
    button.onclick = () => {
      menu.hidden = !menu.hidden;
      button.setAttribute("aria-expanded", String(!menu.hidden));
      if (!menu.hidden) void load();
    };
    menu.onclick = (event) => {
      const choice = event.target?.closest?.("[data-speed]");
      if (choice) {
        speed = Number(choice.dataset.speed);
        return render();
      }
      const row = event.target?.closest?.("[data-replay]");
      if (row) location.href = replayHref(row.dataset.replay, speed);
    };
  }

  async function keep(episodeId) {
    if (state.kept.has(episodeId) || state.keeping) return;
    state.keeping = true;
    try {
      const response = await fetch(`/demo/api/keep/${encodeURIComponent(episodeId)}`, { method: "POST" });
      if (!response.ok) throw new Error(String(response.status));
      state.kept.add(episodeId);
    } catch {
      notice("재현용으로 보관하지 못했어요.");
    } finally {
      state.keeping = false;
      ui.reasoning.renderReason();
    }
  }

  return { bind, keep, available };
}
