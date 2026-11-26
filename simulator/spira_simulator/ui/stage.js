const world = document.getElementById("viewer-world");
const liveRegions = new Map(Array.from(document.querySelectorAll("[data-live]"),
  (node) => [node.id, node.outerHTML]));
let house;
let replaceMarkers;
let entrancePresentation;
let roomViews;
let previousChanges;

function selectRoom() {
  let selected;
  for (const room of document.querySelectorAll(".viewer-room")) {
    const current = location.hash === `#${room.id}`;
    room.toggleAttribute("data-selected", current);
    if (current) selected = room.dataset.room;
  }
  for (const link of document.querySelectorAll(".room-key a")) {
    if (link.hash === location.hash) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
  return selected;
}

function renderHouse() {
  if (!house) return;
  const markers = document.getElementById("viewer-markers");
  const devices = [...markers.querySelectorAll("[data-device]")];
  const signals = Array.from(markers.querySelectorAll("[data-signal]"), (node) => node.dataset.signal);
  const presentation = new Map(devices.map((node) => [node.dataset.device, {
    resting: node.hasAttribute("data-resting"),
  }]));

  house.setEntrance(entrancePresentation(signals));
  house.setPresentation(presentation);
  house.setMarkers(markers, { placeDevices: false });
  const changes = new Map(devices.filter(({ dataset }) => dataset.changeAt)
    .map(({ dataset }) => [dataset.device, JSON.stringify([dataset.changeAt, dataset.values])]));
  if (previousChanges) {
    const changed = [...changes].filter(([id, observation]) => observation !== previousChanges.get(id))
      .map(([id]) => id);
    if (changed.length) house.showChangeMarkers(changed);
    for (const [id, observation] of changes) previousChanges.set(id, observation);
  } else {
    previousChanges = changes;
    house.showChangeMarkers(devices.filter(({ dataset }) => JSON.parse(dataset.values).job_status === "running")
      .map(({ dataset }) => dataset.device));
  }
}

async function openHouse() {
  const view = document.getElementById("viewer-house");
  try {
    const { createHouse, personActionClient, replaceHouseMarkers, entrancePresentation: describeEntrance, HOUSE_ROOM_VIEWS } =
      await import("/sim/assets/house/house.js");
    replaceMarkers = replaceHouseMarkers;
    entrancePresentation = describeEntrance;
    roomViews = HOUSE_ROOM_VIEWS;
    house = createHouse(world, { viewer: true });
    house.setPersonActionClient(personActionClient("/operator/person", async () => {
      const response = await fetch("/sim/snapshot", { signal: AbortSignal.timeout(8000) });
      if (!response.ok) throw new Error(response.status);
      return response.json();
    }));
    house.focus(roomViews[selectRoom()], { instant: true });
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
        selectRoom();
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
window.addEventListener("hashchange", () => {
  const room = selectRoom();
  house?.focus(roomViews[room]);
  document.querySelector(".viewer-room[data-selected]")?.scrollIntoView({ block: "nearest" });
});
window.setTimeout(refresh, 1000);
