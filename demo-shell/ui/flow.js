const STAGES = [
  ["extract", "주문 추출"], ["context", "맥락 검색"], ["intent", "의도 추론"],
  ["tasks", "할 일 생성"], ["plan", "계획 확정"], ["hub", "집 실행"], ["record", "기억 저장"],
];

export const STAGE_NAMES = Object.fromEntries(STAGES);

export function createFlow(root, beatLine) {
  const steps = STAGES.map(([id, title], index) => {
    const node = root.ownerDocument.createElement("li");
    const status = root.ownerDocument.createElement("span");
    status.className = "stage-status";
    const time = root.ownerDocument.createElement("small");
    time.className = "stage-time";
    node.dataset.stage = id;
    node.textContent = `${index + 1} ${title}`;
    node.append(status, time);
    return { id, index, node, status, time };
  });
  root.replaceChildren(...steps.map(({ node }) => node));

  return (stage, ready, beat, times = {}) => {
    for (const { id, index, node, status, time: timeNode } of steps) {
      if (id === stage) {
        node.setAttribute("aria-current", "step");
        beatLine.style.setProperty("--beat-index", index);
      } else {
        node.removeAttribute("aria-current");
      }
      const time = times[id];
      node.classList.toggle("done", Boolean(ready[id] || time?.done));
      const done = ready[id] || time?.done ? " 완료" : "";
      if (status.textContent !== done) status.textContent = done;
      // Server time of the stage (demo trace): how long it took, or how long it has run so far.
      const text = time?.text ?? "";
      if (timeNode.textContent !== text) timeNode.textContent = text;
    }
    if (beatLine.textContent !== beat) beatLine.textContent = beat;
  };
}
