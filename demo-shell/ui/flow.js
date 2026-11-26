const STAGES = [
  ["extract", "추출"], ["context", "맥락"], ["intent", "의도"],
  ["tasks", "할 일"], ["plan", "계획"], ["hub", "집"], ["record", "기록"],
];

export const STAGE_NAMES = Object.fromEntries(STAGES);
export const stageLabel = (id) => `${STAGES.findIndex(([stage]) => stage === id) + 1} ${STAGE_NAMES[id]}`;

export function createFlow(root, beatLine) {
  const steps = STAGES.map(([id], index) => {
    const node = root.ownerDocument.createElement("li");
    const status = root.ownerDocument.createElement("span");
    status.className = "stage-status";
    node.dataset.stage = id;
    node.textContent = stageLabel(id);
    node.append(status);
    return { id, index, node, status };
  });
  root.replaceChildren(...steps.map(({ node }) => node));

  return (stage, ready, beat) => {
    for (const { id, index, node, status } of steps) {
      if (id === stage) {
        node.setAttribute("aria-current", "step");
        beatLine.style.setProperty("--beat-index", index);
      } else {
        node.removeAttribute("aria-current");
      }
      node.classList.toggle("done", Boolean(ready[id]));
      const done = ready[id] ? " 완료" : "";
      if (status.textContent !== done) status.textContent = done;
    }
    if (beatLine.textContent !== beat) beatLine.textContent = beat;
  };
}
