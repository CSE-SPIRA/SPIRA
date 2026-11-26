import { readFileSync } from "node:fs";

export function fixture(episode, name) {
  return JSON.parse(readFileSync(new URL(`../../contracts/fixtures/${episode}/${name}.json`, import.meta.url)));
}

// The fixture supplies the schedule, World event times and the observed execution values.
export function sceneFixture() {
  const episode = fixture("ep_9031", "episode");
  const plan = fixture("ep_9031", "plan.v1");
  const card = fixture("ep_9031", "card.final");
  const rationale = fixture("ep_9031", "rationale");
  const profile = JSON.parse(readFileSync(new URL(
    "../../simulator/spira_simulator/profiles/ep_9031.json", import.meta.url)));
  const devices = profile.devices.map(({ logical_id, device_type, room, label }) =>
    ({ logical_id, device_type, room, label, observation: "current", values: {}, revisions: {} }));
  const events = fixture("ep_9031", "events");
  const executions = fixture("ep_9031", "executions");
  const ledger = [{ kind: "plan", plan_id: episode.episode_id, at: plan.sent_at }];
  const actions = Object.fromEntries(plan.tasks.map(({ task_id, actions }) => [task_id, actions]));
  const facts = events.filter(({ source, type }) => source === "hub" ||
    type === "light.changed" && source === "light_01").flatMap(({ source, type, payload, at }) => {
    if (source === "hub") return [{ event: type, at }];
    return payload.by === "user" ? [{ event: "person", device: source, at }] : [];
  });
  const properties = { show_notice: "show_notice", play_mood: "play_mood", color: "color",
    child_lock: "child_lock", off: "power", set_cook_standby: "preset" };
  const relations = Object.fromEntries(plan.tasks.map(({ task_id, trigger }) => {
    const event = facts.find(({ event }) => event === trigger.event);
    const observed = executions.filter((row) => row.task_id === task_id && row.cmd).map((row, index) => {
      const property = properties[row.cmd];
      const value = { show_notice: row.observed?.notice, child_lock: row.observed?.child_lock, off: false }[row.cmd]
        ?? row.observed;
      return { device: row.device, cmd: row.cmd, at: row.at, values: { [property]: value },
        revisions: { [property]: `${task_id}/${index}` } };
    });
    return [task_id, { trigger, match: event && { at: event.at, event_type: event.event }, observed }];
  }));
  const viewer = (selected = facts) => {
    const signals = { "package.brought_in": "package", guest_arrived: "presence", event_end: "empty" };
    return `<div id="viewer-markers">${selected.map(({ event, at, device }) => device
      ? `<div data-device="${device}" data-person-at="${at}"></div>`
      : `<li data-signal="${signals[event]}"><time datetime="${at}"></time></li>`).join("")}</div>`;
  };
  const hub = { ledger, plan_actions: { [episode.episode_id]: actions },
    plan_lines: { [episode.episode_id]: relations } };
  return { episode, plan, card, rationale, devices, facts, ledger, actions, relations, viewer, hub };
}
