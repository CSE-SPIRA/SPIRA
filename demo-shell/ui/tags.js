import { esc } from "./markup.js";

const ITEM_ICONS = {
  strawberry: "❋", cake_mix: "▤", cream: "▣", detergent: "▥", lotion: "◒",
  balloon: "◯", cake_topper: "✧", party_hat: "△", icing_pen: "╱",
  milk: "▤", egg: "◕", fish: "◫", generic: "·",
};
const ACTION_ICONS = {
  clean: "✦", safety_lock: "▣", mood_light: "☼", tv_scene: "▱", preheat: "♨",
  cool: "❄", air: "≋", notice: "▤", other: "•",
};

export function itemIcon(types, type) {
  const { icon } = Object.hasOwn(types, type) ? types[type] : types.generic;
  return `<span class="item-icon" data-icon="${esc(icon)}" aria-hidden="true">${ITEM_ICONS[icon] ?? ITEM_ICONS.generic}</span>`;
}

export function findTag(tags, kind, ref, text) {
  return tags.find((row) => row.kind === kind && row.ref === ref && row.text === text)?.tag;
}

export function highlightsMarkup(text, tag) {
  const ranges = [];
  for (const part of tag?.highlights ?? []) {
    if (!part) continue;
    const start = text.indexOf(part);
    if (start >= 0) ranges.push([start, start + part.length]);
  }
  const merged = [];
  for (const range of ranges.sort(([a], [b]) => a - b)) {
    const previous = merged.at(-1);
    if (previous && range[0] <= previous[1]) previous[1] = Math.max(previous[1], range[1]);
    else merged.push(range);
  }
  let offset = 0;
  let markup = "";
  for (const [start, end] of merged) {
    markup += esc(text.slice(offset, start)) + `<strong class="tag-highlight">${esc(text.slice(start, end))}</strong>`;
    offset = end;
  }
  return markup + esc(text.slice(offset));
}

export function lineWithTag(text, devices, tag) {
  const action = Object.hasOwn(ACTION_ICONS, tag?.action) ? tag.action : "other";
  const label = typeof tag?.short === "string" && tag.short && text.includes(tag.short) ? tag.short : text;
  const taggedDevices = tag?.devices;
  return {
    markup: `<span class="action-icon" data-action="${action}" aria-hidden="true">${ACTION_ICONS[action]}</span>
      <span${label !== text ? ` title="${esc(text)}" aria-label="${esc(text)}"` : ""}>${esc(label)}</span>`,
    devices: Array.isArray(taggedDevices) && taggedDevices.length &&
      taggedDevices.every((id) => devices.includes(id)) ? taggedDevices : devices,
  };
}
