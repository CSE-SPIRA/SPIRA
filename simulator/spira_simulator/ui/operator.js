const byId = (id) => document.getElementById(id);
const label = (value) => value.replaceAll("_", " ");
const homeLabels = {
  delivery: "Bring package inside", guests_arrive: "Guests arrive", event_end: "Event ends",
};

async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(typeof error.detail === "string" ? error.detail : `Request failed (${response.status})`);
  }
  return response.json();
}

async function report(action) {
  try {
    await action();
    byId("notice").textContent = "Operator action recorded";
  } catch (error) {
    byId("notice").textContent = error.message;
  }
}

function button(text, action) {
  const control = document.createElement("button");
  control.textContent = text;
  control.addEventListener("click", () => report(action));
  return control;
}

const personSelected = () => ["resident", "child", "guest"].includes(byId("actor").value);

function write(values, start = false) {
  const action = { target: byId("device").value, actor: byId("actor").value, values, start };
  if (personSelected()) {
    action.actor_name = byId("actor-name").value.trim() || null;
    action.action_path = byId("action-path").value;
  }
  return request("/operator/device", action);
}

async function evidence(path, output = "evidence", body) {
  byId(output).textContent = "";
  const facts = await request(path, body);
  byId(output).textContent = JSON.stringify(facts, null, 2);
}

async function init() {
  const options = await request("/operator/options");
  for (const action of options.home_actions) {
    byId("home-actions").append(button(homeLabels[action] || label(action), () => request("/operator/home", { action })));
  }
  for (const actor of options.actors) byId("actor").add(new Option(label(actor), actor));
  byId("actor").value = "resident";
  byId("actor").addEventListener("change", () => {
    byId("person-action").hidden = !personSelected();
  });
  for (const device of options.devices) {
    const title = device.label || label(device.device_type);
    for (const id of ["device", "fault-device"]) byId(id).add(new Option(title, device.target));
  }
  const light = options.devices.find((device) => device.device_type === "light");
  if (light) byId("device").value = light.target;

  const updateDevice = () => {
    const device = options.devices.find((entry) => entry.target === byId("device").value);
    const actions = byId("quick-actions");
    actions.replaceChildren();
    byId("editable").textContent = device?.editable.map(label).join(", ") || "";
    if (device?.device_type === "light" && device.editable.includes("color")) {
      actions.append(button("Set warm white", () => write({ color: { kelvin: 2700 } })));
    }
    if (device?.start) actions.append(button(device.device_type === "oven" ? "Start oven" : "Start job", () => write({}, true)));
    if (device?.editable.includes("door_open")) {
      actions.append(button("Open fridge door", () => write({ door_open: true })));
    }
  };
  updateDevice();
  byId("device").addEventListener("change", updateDevice);
  byId("write").addEventListener("click", () => report(() => write(JSON.parse(byId("values").value))));
  byId("fault").addEventListener("click", () => report(() => {
    const [fault, mode] = byId("mode").value.split(":");
    return request("/operator/fault", { target: byId("fault-device").value, fault, mode });
  }));
  byId("journal").addEventListener("click", () => report(() => evidence("/operator/truth")));
  byId("operator-snapshot").addEventListener("click", () => report(() => evidence("/operator/snapshot")));
  byId("judge").addEventListener("click", () => report(() => evidence("/operator/judge")));
  byId("command-marker").addEventListener("click", () => report(
    () => evidence("/operator/judge/marker", "command-evidence", {}),
  ));
  byId("count-commands").addEventListener("click", () => report(() => {
    const range = new URLSearchParams();
    for (const key of ["start", "end"]) {
      const value = byId(`command-${key}`).value.trim();
      if (value) range.set(key, value);
    }
    return evidence(`/operator/judge/commands?${range}`, "command-evidence");
  }));
}

init().catch((error) => { byId("notice").textContent = error.message; });
