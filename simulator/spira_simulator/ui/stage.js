const world = document.getElementById("viewer-world");
const liveRegions = new Map(Array.from(document.querySelectorAll("[data-live]"),
  (node) => [node.id, node.outerHTML]));
let house;
let replaceMarkers;

function renderHouse() {
  if (!house) return;
  const markers = document.getElementById("viewer-markers");
  const devices = [...markers.querySelectorAll("[data-device]")];
  const signals = Array.from(markers.querySelectorAll("[data-signal]"), (node) => node.dataset.signal);
  const presentation = new Map(devices.map((node) => [node.dataset.device, {
    resting: node.hasAttribute("data-resting"),
  }]));

  house.setEntrance({
    packagePresent: signals.includes("package"),
    signal: signals.find((kind) => kind !== "presence"),
  });
  house.setPresentation(presentation);
  house.setMarkers(markers);
}

async function openHouse() {
  const view = document.getElementById("viewer-house");
  try {
    const { createHouse, replaceHouseMarkers } = await import("/sim/assets/house/house.js");
    replaceMarkers = replaceHouseMarkers;
    house = createHouse(world, view);
    house.focus();
    renderHouse();
    view.classList.add("ready");
  } catch (error) {
    view.hidden = true;
    document.getElementById("world-unavailable").hidden = false;
    console.error(error);
  }
}

// Keep the canvas and the appliance controls mounted while refreshing observations.
async function refresh() {
  const warning = document.getElementById("connection-lost");
  const url = new URL(window.location.href);
  if (world) url.searchParams.set("fragment", "true");
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(8000) });
    if (!response.ok) throw new Error(response.status);
    const update = new DOMParser().parseFromString(await response.text(), "text/html");
    for (const [id, previous] of liveRegions) {
      const next = update.getElementById(id);
      if (!next) throw new Error("Missing observations");
      if (next.outerHTML === previous) continue;
      liveRegions.set(id, next.outerHTML);
      const current = document.getElementById(id);
      if (id === "viewer-markers" && replaceMarkers) {
        replaceMarkers(current, next);
        renderHouse();
      } else {
        current.replaceWith(next);
      }
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

if (world) openHouse();
window.setTimeout(refresh, 1000);
