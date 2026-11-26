export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[character]);
export const rows = (items, render) => items.map(render).join("");

export function setMarkup(node, markup) {
  if (node.dataset.content !== markup) {
    node.dataset.content = markup;
    node.innerHTML = markup;
  }
}

export function skeletonBars(count) {
  return '<span class="skeleton-bar" aria-hidden="true"></span>'.repeat(count);
}
