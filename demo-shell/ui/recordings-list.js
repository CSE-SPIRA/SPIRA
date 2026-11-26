import { esc, rows } from "./markup.js";

const status = document.getElementById("status");
const list = document.getElementById("runs");
const date = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" });

async function render() {
  try {
    const response = await fetch("/demo/api/recordings");
    if (!response.ok) throw new Error(response.status);
    const runs = await response.json();
    status.textContent = runs.length ? "" : "저장된 녹화가 없어요.";
    list.innerHTML = rows(runs, (run) => `<li>
      <a href="/demo?recording=${encodeURIComponent(run.id)}">${esc(run.name || run.episode_id)}</a>
      <small>${esc(date.format(new Date(run.created_at)))} · ${run.complete ? "완료" : "진행 중 또는 중단"}</small>
      <form data-id="${esc(run.id)}">
        <input type="text" name="name" maxlength="100" aria-label="녹화 이름" value="${esc(run.name)}">
        <label><input type="checkbox" name="starred"${run.starred ? " checked" : ""}>별표</label>
        <button>저장</button>
      </form></li>`);
  } catch {
    status.textContent = "녹화 목록을 불러오지 못했어요.";
  }
}

list.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch(`/demo/api/recordings/${encodeURIComponent(form.dataset.id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: data.get("name"), starred: data.has("starred") }),
    });
    if (!response.ok) throw new Error(response.status);
    await render();
  } catch {
    status.textContent = "녹화 이름이나 별표를 저장하지 못했어요.";
    button.disabled = false;
  }
});

void render();
