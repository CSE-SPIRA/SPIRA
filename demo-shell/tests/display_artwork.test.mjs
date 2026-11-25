import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { TV_SCENES } from "../../simulator/spira_simulator/ui/house/house.js";
import { FRIDGE_ICONS, fridgeValues, renderFridge } from "../ui/artwork/fridge.js";
import { previewGallery } from "../ui/artwork/gallery.js";
import { MOTIFS } from "../ui/artwork/motifs.js";
import { PALETTES } from "../ui/artwork/palettes.js";
import { TV_DEFAULTS, tvValues, renderTv } from "../ui/artwork/tv.js";

const lists = JSON.parse(readFileSync(new URL("../tag-lists.json", import.meta.url)));
const itemTypes = JSON.parse(readFileSync(new URL("../ui/item-types.json", import.meta.url)));

function checkSvg(svg, viewBox) {
  assert.ok(Buffer.byteLength(svg) < 40 * 1024);
  assert.ok(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"'));
  assert.ok(svg.includes(`viewBox="${viewBox}"`));
  assert.ok(svg.endsWith("</svg>"));
  assert.equal(svg.indexOf("<svg", 1), -1);
  assert.equal(svg.indexOf("</svg>"), svg.length - 6);
  assert.doesNotMatch(svg, /<(?:script|text|image|foreignObject|style)\b|\b(?:href|src|on\w+)\s*=|url\(\s*[^#]/i);
}

test("all 52,728 TV template, palette and motif inputs produce bounded SVGs", () => {
  assert.deepEqual(Object.keys(TV_DEFAULTS), Object.keys(TV_SCENES));
  assert.deepEqual(Object.keys(PALETTES), lists.palette);
  assert.deepEqual(Object.keys(MOTIFS), lists.motif);
  for (const template of Object.keys(TV_SCENES)) {
    for (const palette of lists.palette) {
      for (const center of lists.motif) for (const side of lists.motif) for (const ambient of lists.motif) {
        const values = tvValues(template, { palette, motif: { center, side, ambient } });
        const expected = Object.fromEntries(Object.entries({ center, side, ambient }).map(([slot, motif]) => [
          slot, template === "cinema" && ["candles", "cake"].includes(motif) ? TV_DEFAULTS.cinema[slot] : motif,
        ]));
        assert.deepEqual(values, { template, palette, motifs: expected });
        checkSvg(renderTv(values), "0 0 1280 720");
      }
    }
  }
});

test("each TV composition keeps its own setting across every palette", () => {
  const settings = { kids_party: "kids-party-dome", party: "party-garlands", calm: "window-view", cinema: "cinema-screen" };
  for (const [template, setting] of Object.entries(settings)) {
    for (const palette of lists.palette) {
      const svg = renderTv(tvValues(template, { palette }));
      assert.ok(svg.includes(`id="${setting}"`));
      for (const other of Object.values(settings).filter(id => id !== setting)) assert.ok(!svg.includes(`id="${other}"`));
    }
  }
  assert.equal(tvValues("cinema").motifs.side, "popcorn");
});

test("all seven fridge motifs render text-free artwork for all six palettes", () => {
  for (const icon of FRIDGE_ICONS) {
    assert.ok(Object.values(itemTypes).some(type => type.icon === icon));
    assert.ok(lists.icon.includes(icon));
    for (const palette of lists.palette) {
      checkSvg(renderFridge(fridgeValues(icon, palette)), "0 0 360 420");
    }
  }
});

test("the presenter gallery shows the full palette grid, motif examples and fridge notices", () => {
  const [_, tv, variations, fridge] = previewGallery().split("<section ");
  assert.equal([...tv.matchAll(/<figure>/g)].length, 24);
  const defaults = tv.slice(0, tv.indexOf("<h3>다른 팔레트</h3>"));
  assert.equal([...defaults.matchAll(/<figure>/g)].length, 4);
  for (const template of Object.keys(TV_SCENES)) {
    assert.ok(defaults.includes(`<strong>${template}</strong><span>${TV_DEFAULTS[template].palette}</span>`));
    for (const palette of lists.palette) assert.ok(tv.includes(`<strong>${template}</strong><span>${palette}</span>`));
  }
  assert.equal([...variations.matchAll(/<strong>kids_party<\/strong>/g)].length, 4);
  assert.match(variations, /center <strong>crown<\/strong>/);
  assert.equal([...fridge.matchAll(/<canvas [^>]+data-notice="[^"]+"/g)].length, FRIDGE_ICONS.length);
  for (const icon of FRIDGE_ICONS) assert.ok(fridge.includes(`center <strong>${icon}</strong>`));
});
