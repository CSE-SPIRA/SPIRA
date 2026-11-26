import { PALETTES } from "./palettes.js";
import { FRIDGE_ICONS, fridgeValues, renderFridge } from "./fridge.js";
import { TV_DEFAULTS, tvValues, renderTv } from "./tv.js";
import { svgUrl } from "./scene.js";
import { esc } from "../markup.js";

const VARIANTS = [
  { center: "crown", side: "hearts", ambient: "confetti" },
  { center: "cake", side: "flowers", ambient: "hearts" },
  { center: "moon", side: "waves", ambient: "stars" },
  { center: "film", side: "candles", ambient: "balloons" },
];
const NOTICES = {
  strawberry: "딸기는 씻지 않은 채로 냉장 보관해 주세요.",
  cream: "크림은 사용 직전까지 냉장고 안쪽에 두세요.",
  milk: "우유는 뚜껑을 닫아서 보관해 주세요.",
  egg: "계란은 포장째 냉장 보관해 주세요.",
  fruit: "자른 과일은 밀폐 용기에 담아 주세요.",
  vegetable: "채소는 물기를 닦아서 보관해 주세요.",
  generic: "개봉한 식품은 밀폐 용기에 담아 주세요.",
};

function card({ template, palette, motifs }, picture) {
  const labels = Object.entries(motifs).map(([slot, motif]) =>
    `<span>${slot} <strong>${motif}</strong></span>`).join("");
  return `<figure>${picture}<figcaption><div class="values"><strong>${template}</strong><span>${palette}</span></div>
    <div class="motifs">${labels}</div></figcaption></figure>`;
}

const tvCard = values => card(values,
  `<img alt="" width="1280" height="720" src="${svgUrl(renderTv(values))}">`);

function fridgeCanvas(values, svg, notice) {
  const label = esc(notice);
  return `<canvas class="notice" width="360" height="420" role="img" aria-label="${label}" data-notice="${label}"
    data-art="${svgUrl(svg)}">${label}</canvas>`;
}

export function previewGallery(fridgePicture = fridgeCanvas) {
  const defaults = Object.keys(TV_DEFAULTS).map(template => tvCard(tvValues(template)));
  const combinations = Object.keys(TV_DEFAULTS).flatMap(template =>
    Object.keys(PALETTES).filter(palette => palette !== TV_DEFAULTS[template].palette)
      .map(palette => tvCard(tvValues(template, { palette }))));
  const variations = VARIANTS.map(motif => tvCard(tvValues("kids_party", { motif })));
  const fridge = FRIDGE_ICONS.map(icon => {
    const values = fridgeValues(icon);
    return card(values, fridgePicture(values, renderFridge(values), NOTICES[icon]));
  });
  return `
    <section aria-label="TV 장면과 팔레트">
      <h2>TV 장면과 팔레트</h2>
      <h3>기본 화면</h3><div class="grid examples">${defaults.join("")}</div>
      <h3>다른 팔레트</h3><div class="grid examples">${combinations.join("")}</div>
    </section>
    <section aria-label="어린이 파티 모티프">
      <h2>어린이 파티 모티프</h2><div class="grid examples">${variations.join("")}</div>
    </section>
    <section aria-label="냉장고 안내">
      <h2>냉장고 안내</h2><div class="grid examples fridge">${fridge.join("")}</div>
    </section>`;
}
