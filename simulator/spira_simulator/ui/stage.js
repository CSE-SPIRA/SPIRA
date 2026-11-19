const byId = (id) => document.getElementById(id);
const label = (value) => String(value).replaceAll("_", " ");
const time = (value) => value.replace("T", " ").replace(/\.\d+/, "");
const titleCase = (value) => value.charAt(0).toUpperCase() + value.slice(1);
let lastSnapshot;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function display(value) {
  if (value === null) return "None";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") {
    return Object.entries(value).map(([key, entry]) => `${label(key)} ${display(entry)}`).join(" · ");
  }
  return String(value);
}

function lightSample(color) {
  const sample = node("span", undefined, "color-sample");
  sample.setAttribute("aria-hidden", "true");
  if ([color.hue, color.saturation, color.brightness].every(Number.isFinite)) {
    sample.style.backgroundColor = `hsl(${color.hue} ${color.saturation}% ${color.brightness / 2}%)`;
  } else if (Number.isFinite(color.kelvin)) {
    sample.style.backgroundColor = color.kelvin < 4000 ? "#ffe4a6" : "#f1f6ff";
  }
  return sample;
}

function tile(device, disconnected) {
  const card = node("article", undefined, "device");
  const status = disconnected && device.observation === "current" ? "stale" : device.observation;
  card.dataset.status = status;
  const title = node("div", undefined, "device-heading");
  title.append(node("h3", device.label || titleCase(label(device.device_type))));
  if (status === "current" && device.device_type === "light" && device.values.color) {
    title.append(lightSample(device.values.color));
  }
  card.append(title);
  const qualifier = `${device.logical_id} · ${device.substrate === "virtual" ? "virtual simulation" : "physical · unqualified"}`;
  card.append(node("p", qualifier, "metadata"));
  if (device.local_operation_reporting) {
    card.append(node("p", `Class A assumption · ${device.assumption}`, "metadata"));
  } else {
    card.append(node("p", "Class B · local operation unreported", "metadata"));
  }
  const statuses = {
    current: "Observed", stale: "Stale · last observation", missing: "Readback missing",
    unavailable: "Readback unavailable",
  };
  card.append(node("p", `${statuses[status]} · ${time(device.observed_at)}`, status === "current" ? "metadata" : "stale"));
  const facts = node("dl");
  for (const [key, value] of Object.entries(device.values)) {
    facts.append(node("dt", label(key)), node("dd", display(value)));
  }
  if (device.job_id) facts.append(node("dt", "Job"), node("dd", device.job_id));
  if (facts.children.length) card.append(facts);
  return card;
}

function renderWorld(snapshot, disconnected) {
  const groups = new Map();
  for (const device of snapshot.devices) {
    if (!groups.has(device.room)) groups.set(device.room, []);
    groups.get(device.room).push(device);
  }
  const rooms = [...groups].map(([room, devices]) => {
    const section = node("section", undefined, "room");
    const title = label(room);
    section.append(node("h2", titleCase(title)));
    const list = node("div", undefined, "devices");
    list.append(...devices.map((device) => tile(device, disconnected)));
    section.append(list);
    return section;
  });
  byId("rooms").replaceChildren(...rooms);
}

function fillList(id, rows, format, empty) {
  byId(id).replaceChildren(...(rows.length ? rows.map((row) => node("li", format(row))) : [node("li", empty)]));
}

function renderOverlay(overlay) {
  const pending = (row) => {
    const value = row.target_value === null ? "" : ` · ${display(row.target_value)}`;
    return `${row.device} · ${label(row.command)}${value} · ${label(row.wait)}`;
  };
  fillList("preparation", overlay.preparation, pending, "No planned household preparation");
  fillList("notices", overlay.item_notices, pending, "No pending item notices");
  fillList("restores", overlay.restores, (row) =>
    `${row.device} · ${label(row.status)} · ${row.substrate || "substrate unknown"} · ${label(row.qualification || "qualification unknown")} · ${time(row.at)}`,
    "No restore reports");
  byId("plan-status").textContent = overlay.errors.join(" · ");
}

async function get(path) {
  const response = await fetch(path, { signal: AbortSignal.timeout(4000) });
  if (!response.ok) throw new Error(response.status);
  return response.json();
}

async function refresh() {
  const [snapshot, health, overlay] = await Promise.allSettled([
    get("/sim/snapshot"), get("/health"), get("/sim/overlay"),
  ]);
  if (snapshot.status === "fulfilled") {
    lastSnapshot = snapshot.value;
    renderWorld(lastSnapshot, false);
    const mqtt = health.value?.mqtt;
    const gap = mqtt?.last_gap_at ? ` · last MQTT gap ${time(mqtt.last_gap_at)}` : "";
    byId("connection").textContent = `${lastSnapshot.household_id} · MQTT ${mqtt?.connected ? "online" : "offline"}${gap}`;
  } else {
    byId("connection").textContent = "World disconnected · observations unavailable";
    if (lastSnapshot) renderWorld(lastSnapshot, true);
  }
  if (overlay.status === "fulfilled") {
    renderOverlay(overlay.value);
  } else {
    byId("plan-status").textContent = "Overlay disconnected · last available view";
  }
  window.setTimeout(refresh, 1000);
}

refresh();
