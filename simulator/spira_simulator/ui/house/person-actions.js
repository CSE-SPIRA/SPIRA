export function personActionClient(endpoint, readWorld) {
  return async ({ target, person, control }) => {
    const url = new URL(endpoint, window.location.href);
    url.searchParams.set("target", target);
    const response = await fetch(url, {
      method: "POST",
      headers: { Accept: "application/json" },
      body: new URLSearchParams({ person, control }),
      credentials: "include",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok || !(await response.json()).applied) throw new Error("Person action failed");
    return readWorld();
  };
}

export function optimisticReading(current, { values, start }) {
  const next = { ...current, ...values };
  if (start || values.clean) {
    next.in_use = true;
    next.job_status = "running";
  } else if (values.clean === null && current.in_use) {
    next.in_use = false;
    next.job_status = "stopped";
  }
  return next;
}

export function keepSpaceForButton(event) {
  if (event.key === " ") event.stopPropagation();
}

export function createPersonPanel(stage, act) {
  const doc = stage.ownerDocument;
  const panel = doc.createElement("section");
  panel.className = "house-person-panel";
  const who = doc.createElement("label");
  who.textContent = "누가";
  const select = doc.createElement("select");
  who.append(select);
  const buttons = doc.createElement("div");
  buttons.className = "house-person-buttons";
  buttons.setAttribute("aria-label", "기기 조작");
  buttons.setAttribute("role", "group");
  const status = doc.createElement("p");
  status.className = "house-person-status";
  status.setAttribute("role", "status");
  panel.append(who, buttons, status);
  panel.hidden = true;
  stage.append(panel);
  let people, person, selection;

  function sync({ pending = false, message = "" } = {}) {
    panel.setAttribute("data-pending", String(pending));
    for (const button of buttons.children) button.setAttribute("aria-disabled", String(pending));
    status.textContent = message || (buttons.children.length ? "" : "사용할 수 있는 조작이 없어요.");
  }

  select.addEventListener("change", () => {
    person = select.value;
    try { localStorage.setItem("spira.house.person", person); } catch {}
  });

  function open(id, name, names, actions) {
    panel.hidden = false;
    panel.setAttribute("aria-label", `${name} · 사람 조작`);
    if (people !== JSON.stringify(names)) {
      people = JSON.stringify(names);
      select.replaceChildren(...names.map(name => {
        const option = doc.createElement("option");
        option.value = option.textContent = name;
        return option;
      }));
      try { person ??= localStorage.getItem("spira.house.person"); } catch {}
      person = names.includes(person) ? person : names.includes("엄마") ? "엄마" : names[0];
      select.value = person;
    }
    const next = JSON.stringify([id, actions]);
    if (selection === next) return;
    selection = next;
    buttons.replaceChildren(...actions.map(action => {
      const button = doc.createElement("button");
      button.type = "button";
      button.textContent = action.label;
      button.addEventListener("keydown", keepSpaceForButton);
      button.addEventListener("click", () => {
        if (button.getAttribute("aria-disabled") !== "true") void act(id, person, action);
      });
      return button;
    }));
  }

  function close() {
    panel.hidden = true;
  }

  function place(anchor, width, height) {
    if (panel.hidden) return;
    const gap = 12;
    const left = anchor.x * width + gap;
    const maxLeft = width - panel.offsetWidth - gap;
    const beside = left <= maxLeft ? left : anchor.x * width - panel.offsetWidth - gap;
    panel.style.left = `${Math.max(gap, Math.min(beside, maxLeft))}px`;
    panel.style.top = `${Math.max(gap, Math.min(anchor.y * height - 12,
      height - panel.offsetHeight - gap))}px`;
  }

  return { open, close, sync, place, focus: () => select.focus({ preventScroll: true }) };
}
