// The Server flow strip on page 1. This file is the place for staging and animation:
// the shell only calls createFlow() once and setStage(n) whenever the step changes.
// Keep the two exported names and their arguments; everything inside may change.

export function createFlow(root, nodes) {
  root.innerHTML = "";
  const els = [];
  const edges = [];
  nodes.forEach((node, i) => {
    if (i > 0) {
      const edge = document.createElement("div");
      edge.className = "flow-edge";
      root.appendChild(edge);
      edges.push(edge);
    }
    const el = document.createElement("div");
    el.className = "flow-node";
    el.innerHTML = `<b>${node.title}</b><small>${node.sub}</small>`;
    root.appendChild(el);
    els.push(el);
  });

  return {
    // n: index of the active node (0..nodes.length-1). Called on every step.
    setStage(n) {
      els.forEach((el, i) => {
        el.classList.toggle("on", i === n);
        el.classList.toggle("done", i < n);
      });
      edges.forEach((edge, i) => edge.classList.toggle("done", i < n));
    },
  };
}
