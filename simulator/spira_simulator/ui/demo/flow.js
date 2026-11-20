// Each count appears below its stage label once that stage is reached.
export function createFlow(root, nodes) {
  const steps = nodes.map(({ title }) => {
    const node = document.createElement("li");
    const label = document.createElement("span");
    const count = document.createElement("small");
    label.textContent = title;
    node.append(label, count);
    return { node, label, count };
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
    setCounts(counts) {
      steps.forEach(({ count }, index) => {
        const text = counts[index] ?? "";
        if (count.textContent !== text) count.textContent = text;
      });
    },
  };
}
