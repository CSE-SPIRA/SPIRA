// The reasoning strip only marks the current stage and the path to it.
export function createFlow(root, nodes) {
  const steps = nodes.map(({ title }) => {
    const node = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = title;
    node.append(label);
    return { node, label };
  });
  root.replaceChildren(...steps.map(({ node }) => node));

  return {
    setStage(n) {
      steps.forEach(({ node, label }, index) => {
        node.classList.toggle("reached", index <= n);
        if (index === n) label.setAttribute("aria-current", "step");
        else label.removeAttribute("aria-current");
      });
    },
  };
}
