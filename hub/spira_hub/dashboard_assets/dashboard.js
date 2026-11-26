document.querySelector('meta[name="theme-color"]').content =
  getComputedStyle(document.documentElement).getPropertyValue("--paper").trim();

const regions = ["ledger-summary", "ledger", "device-list", "detail-content"].map((id) => document.getElementById(id));
const ledger = document.getElementById("ledger");
ledger.addEventListener("click", (event) => {
  if (event.target.closest("details[data-newest] > summary")) event.preventDefault();
});
ledger.addEventListener("toggle", (event) => {
  if (event.target.matches("details[data-newest]")) event.target.open = true;
}, true);

function refreshLedger(region, next) {
  const groups = new Map(Array.from(region.querySelectorAll("details"), (group) => [group.dataset.group, group]));
  let focusedSummary;
  for (const group of next.querySelectorAll("details")) {
    const previous = groups.get(group.dataset.group);
    if (!previous) continue;
    if (!previous.hasAttribute("data-newest") && !group.hasAttribute("data-newest")) group.open = previous.open;
    if (previous.firstElementChild === document.activeElement) focusedSummary = group.firstElementChild;
  }
  if (region.isEqualNode(next)) return;
  region.replaceChildren(...next.childNodes);
  focusedSummary?.focus({ preventScroll: true });
}

async function refresh() {
  try {
    const response = await fetch(location.pathname, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    if (!response.ok) return;

    const page = new DOMParser().parseFromString(await response.text(), "text/html");
    for (const region of regions) {
      const next = page.getElementById(region.id);
      if (!next) continue;
      if (region.id === "ledger") refreshLedger(region, next);
      else if (!region.isEqualNode(next)) region.replaceChildren(...next.childNodes);
    }
  } catch {
    // Preserve the last view on a failed read.
  } finally {
    setTimeout(refresh, 5000);
  }
}

setTimeout(refresh, 5000);
