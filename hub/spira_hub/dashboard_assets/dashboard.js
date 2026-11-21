document.querySelector('meta[name="theme-color"]').content =
  getComputedStyle(document.documentElement).getPropertyValue("--paper").trim();

const regions = ["ledger-summary", "ledger", "detail-content"].map((id) => document.getElementById(id));

async function refresh() {
  try {
    const response = await fetch(location.pathname, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    if (!response.ok) return;

    const page = new DOMParser().parseFromString(await response.text(), "text/html");
    for (const region of regions) {
      const next = page.getElementById(region.id);
      if (next && !region.isEqualNode(next)) region.replaceChildren(...next.childNodes);
    }
  } catch {
    // Preserve the last view on a failed read.
  } finally {
    setTimeout(refresh, 5000);
  }
}

setTimeout(refresh, 5000);
