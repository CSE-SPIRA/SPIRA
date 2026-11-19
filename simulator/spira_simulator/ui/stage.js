// Refresh observations without replacing the appliance controls or the household links.
async function refresh() {
  const warning = document.getElementById("connection-lost");
  const url = new URL(window.location.href);
  if (url.pathname === "/sim/viewer") url.searchParams.set("fragment", "true");
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(8000) });
    if (!response.ok) throw new Error(response.status);
    const update = new DOMParser().parseFromString(await response.text(), "text/html");
    for (const current of document.querySelectorAll("[data-live]")) {
      const next = update.getElementById(current.id);
      if (next) current.replaceWith(next);
    }
    document.body.classList.remove("disconnected");
    warning.hidden = true;
  } catch {
    document.body.classList.add("disconnected");
    warning.hidden = false;
  } finally {
    window.setTimeout(refresh, 1000);
  }
}

window.setTimeout(refresh, 1000);
