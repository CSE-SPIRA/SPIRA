const world = document.getElementById("viewer-world");
const liveRegions = new Map(Array.from(document.querySelectorAll("[data-live]"),
  (node) => [node.id, node.outerHTML]));
let house;

function renderHouse() {
  if (!house) return;
  const devices = [...document.querySelectorAll("[data-device][data-values]")];
  const entrance = document.getElementById("entrance-observations");
  const signals = Array.from(entrance.querySelectorAll("[data-signal]"), (node) => node.dataset.signal);
  const markers = new Map(devices.map((node) => [node.dataset.device, node]));
  markers.set("entrance", entrance);
  const presentation = new Map(devices.map((node) => [node.dataset.device, {
    resting: node.hasAttribute("data-resting"),
    focused: !node.hasAttribute("data-resting") || node.firstElementChild.dataset.observation !== "current",
  }]));
  presentation.set("entrance", { focused: signals.length > 0 });

  house.update({ devices: devices.map((node) => ({
    logical_id: node.dataset.device,
    values: JSON.parse(node.dataset.values),
  })) });
  house.setEntrance({
    packagePresent: signals.includes("package"),
    signal: signals.filter((kind) => kind !== "presence").at(-1),
  });
  house.setPresentation(presentation);
  house.setMarkers(markers);
}

async function openHouse() {
  const view = document.getElementById("viewer-house");
  try {
    const { createHouse } = await import("/sim/assets/house/house.js");
    house = createHouse(world, null, view);
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
      document.getElementById(id).replaceWith(next);
      if (id === "viewer-markers") renderHouse();
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
