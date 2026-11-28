const STAGES = [
  ["extract", "주문 추출"], ["context", "맥락 검색"], ["intent", "의도 추론"],
  ["tasks", "할 일 생성"], ["plan", "계획 확정"], ["hub", "집 실행"], ["record", "기억 저장"],
];

export const STAGE_NAMES = Object.fromEntries(STAGES);

// Horizontal stepper (11-28): a finished stage is an amber disc with a check; the stage being analysed is an amber
// disc with its number and a spinning ring; the line up to either is amber; the stage open in the log gets a ring;
// the rest is grey.
// Each step keeps [status, time, disc] as children (time stays the second child) and its stage name as text.
export function stepState({ index, current, done, time, focus, id }) {
  // Being analysed: the Server runs it, or finished it but the screen has not shown it yet (결과 도착).
  const running = !done && /^(진행 중|결과 도착)/.test(time?.text ?? "");
  const failed = time?.text === "실패";
  return {
    done, running, failed,
    lit: focus ? focus === id : index === current,
    shown: Boolean(focus) && focus !== id && index === current,
  };
}

export function createFlow(root, beatLine) {
  const steps = STAGES.map(([id, title], index) => {
    const node = root.ownerDocument.createElement("li");
    const status = root.ownerDocument.createElement("span");
    status.className = "stage-status";
    const time = root.ownerDocument.createElement("small");
    time.className = "stage-time";
    const disc = root.ownerDocument.createElement("span");
    disc.className = "stage-disc";
    disc.setAttribute("aria-hidden", "true");
    node.dataset.stage = id;
    node.textContent = title;
    node.append(status, time, disc);
    return { id, index, node, status, time, disc };
  });
  root.replaceChildren(...steps.map(({ node }) => node));

  // `focus` = a finished stage the presenter reopened in the log (it takes the amber; the shown stage keeps a ring).
  return (stage, ready, beat, times = {}, focus = null) => {
    const current = steps.find(({ id }) => id === stage)?.index ?? -1;
    for (const { id, index, node, status, time: timeNode, disc } of steps) {
      if (id === stage) {
        node.setAttribute("aria-current", "step");
        beatLine.style.setProperty("--beat-index", index);
      } else {
        node.removeAttribute("aria-current");
      }
      const time = times[id];
      const done = Boolean(ready[id] || time?.done);
      const s = stepState({ index, current, done, time, focus, id });
      node.classList.toggle("done", done);
      node.classList.toggle("running", s.running);
      node.classList.toggle("failed", s.failed);
      node.classList.toggle("lit", s.lit);
      node.classList.toggle("shown", s.shown);
      const label = done ? " 완료" : s.running ? " 진행 중" : "";
      if (status.textContent !== label) status.textContent = label;
      const mark = done ? "✓" : s.failed ? "!" : String(index + 1);
      if (disc.textContent !== mark) disc.textContent = mark;
      // Server time of the stage (demo trace): how long it took, or how long it has run so far.
      const text = time?.text ?? (done ? "완료" : "");
      if (timeNode.textContent !== text) timeNode.textContent = text;
    }
    if (beatLine.textContent !== beat) beatLine.textContent = beat;
  };
}
