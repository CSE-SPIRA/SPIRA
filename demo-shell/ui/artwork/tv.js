import { MOTIFS } from "./motifs.js";
import { PALETTES } from "./palettes.js";

export const TV_DEFAULTS = {
  kids_party: { palette: "princess_pink", center: "castle", side: "balloons", ambient: "stars" },
  party: { palette: "festive_red", center: "cake", side: "candles", ambient: "confetti" },
  calm: { palette: "forest_green", center: "moon", side: "waves", ambient: "stars" },
  cinema: { palette: "calm_neutral", center: "film", side: "popcorn", ambient: "stars" },
};
export const MOTIF_SLOTS = ["center", "side", "ambient"];

export function tvValues(template, tag) {
  if (typeof template !== "string" || !Object.hasOwn(TV_DEFAULTS, template)) return;
  const defaults = TV_DEFAULTS[template];
  const palette = typeof tag?.palette === "string" && Object.hasOwn(PALETTES, tag.palette) ? tag.palette : defaults.palette;
  const motifs = Object.fromEntries(MOTIF_SLOTS.map(slot => {
    const motif = tag?.motif?.[slot];
    const allowed = typeof motif === "string" && Object.hasOwn(MOTIFS, motif) &&
      (template !== "cinema" || (motif !== "candles" && motif !== "cake"));
    return [slot, allowed ? motif : defaults[slot]];
  }));
  return { template, palette, motifs };
}

const horizontal = "x1=\"0\" x2=\"1\" y1=\"0\" y2=\"0\"";
const vertical = "x1=\"0\" x2=\"0\" y1=\"0\" y2=\"1\"";

function backdrop({ sky, haze, ground, accent, shade, glow }, dark) {
  return `<defs>
    <linearGradient id="sky" ${vertical}><stop stop-color="${dark ? shade : sky}"/><stop offset="1" stop-color="${dark ? accent : haze}"/></linearGradient>
    <linearGradient id="floor" ${vertical}><stop stop-color="${dark ? shade : haze}"/><stop offset="1" stop-color="${dark ? "#292833" : ground}"/></linearGradient>
    <linearGradient id="arch" ${vertical}><stop stop-color="${haze}"/><stop offset="1" stop-color="${sky}"/></linearGradient>
    <linearGradient id="plinth" ${horizontal}><stop stop-color="${accent}"/><stop offset=".32" stop-color="${sky}"/><stop offset="1" stop-color="${shade}"/></linearGradient>
    <linearGradient id="glaze" ${vertical}><stop stop-color="${haze}"/><stop offset=".52" stop-color="${sky}"/><stop offset="1" stop-color="${accent}"/></linearGradient>
    <radialGradient id="light"><stop stop-color="${glow}" stop-opacity=".8"/><stop offset="1" stop-color="${glow}" stop-opacity="0"/></radialGradient>
    <radialGradient id="shadow"><stop stop-color="${shade}" stop-opacity=".48"/><stop offset="1" stop-color="${shade}" stop-opacity="0"/></radialGradient>
  </defs>
  <rect width="1280" height="720" fill="url(#sky)"/>`;
}

function shadow(x, y, width, height) {
  return `<ellipse cx="${x}" cy="${y}" rx="${width}" ry="${height}" fill="url(#shadow)"/>`;
}

function stage(x, y, width, height, { glow, haze }) {
  return `${shadow(x, y + height + 19, width + 45, 40)}
    <path d="M${x - width} ${y}h${2 * width}v${height}a${width} 25 0 0 1 ${-2 * width} 0Z" fill="url(#plinth)"/>
    <ellipse cx="${x}" cy="${y}" rx="${width}" ry="25" fill="${haze}"/>
    <ellipse cx="${x}" cy="${y + 1}" rx="${width - 9}" ry="20" fill="none" stroke="${glow}" stroke-width="2"/>`;
}

function place(content, x, y, size, opacity = 1, mirror = false) {
  return `<g transform="translate(${x} ${y}) scale(${mirror ? -size / 100 : size / 100} ${size / 100})" opacity="${opacity}">${content}</g>`;
}

function layout(motifs, { center: [x, y, size], side: [left, sideY, sideSize], sky }) {
  return {
    center: place(motifs.center, x, y, size),
    side: place(motifs.side, left, sideY, sideSize) + place(motifs.side, 1280 - left, sideY, sideSize, 1, true),
    ambient: sky.map(([x, y, size, alpha]) => place(motifs.ambient, x, y, size, alpha)).join(""),
  };
}

const TEMPLATES = {
  kids_party(p, motifs) {
    const art = layout(motifs, { center: [418, 179, 444], side: [132, 326, 238],
      sky: [[95, 197, 71, .82], [255, 107, 95, .9], [613, 76, 53, .69], [930, 126, 82, .9], [1089, 228, 62, .66]] });
    return `
      <ellipse cx="660" cy="305" rx="500" ry="314" fill="url(#light)"/>
      <path d="M0 442Q108 347 252 398Q380 440 460 437H850Q1020 336 1280 427V720H0Z" fill="${p.ground}" opacity=".62"/>
      <path d="M0 497Q221 390 445 501T907 500Q1090 430 1280 488V720H0Z" fill="${p.haze}" opacity=".65"/>
      <path id="kids-party-dome" d="M397 514V331C397 175 497 118 640 118S883 175 883 331V514Z" fill="url(#arch)" stroke="${p.haze}" stroke-width="9"/>
      <path d="M419 500V335C419 191 510 141 640 141S861 191 861 335V500" fill="none" stroke="${p.glow}" stroke-width="3" opacity=".77"/>
      ${art.ambient}
      <path d="M0 523Q319 487 640 505T1280 517V720H0Z" fill="url(#floor)"/>
      <path d="M0 658Q270 571 635 626T1280 649" fill="none" stroke="${p.haze}" stroke-width="3" opacity=".38"/>
      ${shadow(251, 547, 114, 26)}${shadow(1029, 547, 114, 26)}
      ${stage(640, 563, 216, 44, p)}
      ${shadow(640, 558, 168, 20)}${art.side}${art.center}`;
  },
  party(p, motifs) {
    const art = layout(motifs, { center: [416, 178, 448], side: [116, 318, 242],
      sky: [[89, 214, 94, .88], [292, 167, 104, .8], [830, 165, 108, .82], [1068, 205, 100, .9]] });
    const flags = [[67, 67, 23], [149, 98, 17], [234, 119, 10], [319, 129, 2], [406, 125, -6],
      [492, 112, -13], [578, 88, -19], [702, 88, 19], [788, 112, 13], [874, 125, 6],
      [961, 129, -2], [1046, 119, -10], [1131, 98, -17], [1213, 67, -23]];
    const flagColors = [p.glow, p.accent, p.haze, p.shade];
    return `
      <ellipse cx="640" cy="308" rx="435" ry="275" fill="url(#light)"/>
      <path d="M116 0L213 0L590 563H21ZM1067 0H1164L1259 563H690Z" fill="${p.haze}" opacity=".21"/>
      <g id="party-garlands">
        <path d="M0 37Q307 205 640 65Q973 205 1280 37" fill="none" stroke="${p.shade}" stroke-width="3"/>
        ${flags.map(([x, y, rotation], index) => `<path d="M-24 0H24L4 52Q0 60 -4 52Z"
          transform="translate(${x} ${y}) rotate(${rotation})" fill="${flagColors[index % flagColors.length]}"/>`).join("")}
      </g>
      ${art.ambient}
      <path d="M0 512Q330 468 640 491T1280 503V720H0Z" fill="url(#floor)"/>
      <path d="M0 606Q299 537 538 579M742 579Q981 537 1280 606M0 674Q299 605 538 647M742 647Q981 605 1280 674" fill="none" stroke="${p.haze}" stroke-width="3" opacity=".3"/>
      ${shadow(241, 532, 113, 22)}${shadow(1039, 532, 113, 22)}
      ${stage(640, 601, 282, 27, p)}${stage(640, 555, 239, 46, p)}
      ${shadow(640, 553, 185, 23)}${art.side}${art.center}`;
  },
  calm(p, motifs) {
    const art = layout(motifs, { center: [498, 105, 284], side: [206, 388, 173],
      sky: [[234, 183, 49, .64], [434, 146, 57, .61], [808, 153, 68, .69], [987, 207, 49, .69]] });
    return `
      <defs><clipPath id="window-view"><rect x="168" y="100" width="944" height="479" rx="6"/></clipPath></defs>
      <rect width="1280" height="720" fill="${p.ground}"/>
      <rect x="139" y="70" width="1002" height="534" rx="15" fill="${p.shade}"/>
      <g clip-path="url(#window-view)">
        <rect x="168" y="100" width="944" height="479" fill="url(#sky)"/>
        <ellipse cx="640" cy="272" rx="380" ry="253" fill="url(#light)"/>
        ${art.ambient}${art.center}
        <path d="M140 429Q213 391 311 324Q351 296 408 339L521 424Q555 443 595 418L742 317Q794 275 849 315L973 408Q1022 430 1140 365V580H140Z" fill="${p.accent}" opacity=".56"/>
        <path d="M140 402Q249 380 369 439Q466 476 583 461Q741 428 817 437Q995 445 1140 391V580H140Z" fill="${p.shade}" opacity=".7"/>
        <path d="M140 490Q332 462 568 474T1140 474V580H140Z" fill="url(#floor)"/>
        <path d="M489 492Q640 483 791 492M458 522Q640 507 822 522M480 556Q640 543 800 556" fill="none" stroke="${p.haze}" stroke-width="4" stroke-linecap="round" opacity=".67"/>
        ${art.side}
      </g>
      <rect x="155" y="86" width="970" height="503" rx="9" fill="none" stroke="${p.haze}" stroke-width="12"/>
      <path d="M382 100V579M898 100V579" stroke="${p.shade}" stroke-width="18"/>
      <path d="M379 100V579M895 100V579" stroke="${p.haze}" stroke-width="8"/>
      <path d="M105 596H1175L1202 622H78Z" fill="${p.haze}"/>
      <rect x="78" y="622" width="1124" height="15" rx="4" fill="url(#plinth)"/>`;
  },
  cinema(p, motifs) {
    const art = layout(motifs, { center: [450, 136, 380], side: [99, 432, 176],
      sky: [[351, 243, 53, .57], [445, 160, 54, .65], [819, 156, 56, .65], [882, 243, 53, .57]] });
    const curtain = `
      <path d="M0 0H260Q239 177 145 325Q119 381 179 518L0 554Z" fill="url(#plinth)"/>
      <path d="M33 0Q51 207 23 486M82 0Q96 206 52 499M136 0Q132 215 85 508M188 0Q164 207 111 311M96 343Q100 427 140 508"
        fill="none" stroke="${p.shade}" stroke-width="15" opacity=".49"/>
      <path d="M48 0Q62 222 31 468M149 0Q146 204 98 312" fill="none" stroke="${p.haze}" stroke-width="5" opacity=".22"/>
      <path d="M0 337Q76 350 151 319" fill="none" stroke="${p.glow}" stroke-width="8"/>`;
    return `
      <path d="M0 467H1280V720H0Z" fill="url(#floor)"/>
      <ellipse cx="640" cy="556" rx="465" ry="96" fill="url(#light)" opacity=".45"/>
      <rect id="cinema-screen" x="257" y="100" width="766" height="428" rx="9" fill="${p.shade}" stroke="${p.glow}" stroke-opacity=".6" stroke-width="3"/>
      <rect x="274" y="116" width="732" height="396" rx="4" fill="url(#arch)"/>
      <ellipse cx="640" cy="309" rx="340" ry="192" fill="url(#light)"/>
      ${art.ambient}${art.center}
      <path d="M0 0H1280V69Q1148 123 981 66Q805 126 640 65Q474 126 299 66Q132 123 0 69Z" fill="url(#plinth)"/>
      <path d="M0 69Q132 123 299 66Q474 126 640 65Q805 126 981 66Q1148 123 1280 69" fill="none" stroke="${p.glow}" stroke-opacity=".58" stroke-width="4"/>
      ${curtain}<g transform="translate(1280 0) scale(-1 1)">${curtain}</g>
      <path d="M338 645Q640 613 942 645M417 695Q640 673 863 695" fill="none" stroke="${p.glow}" stroke-opacity=".3" stroke-width="3"/>
      ${shadow(186, 594, 88, 18)}${shadow(1094, 594, 88, 18)}${art.side}`;
  },
};

export function renderTv({ template, palette, motifs }) {
  const values = tvValues(template, { palette, motif: motifs });
  if (!values) return;
  const p = PALETTES[values.palette];
  const art = Object.fromEntries(MOTIF_SLOTS.map(slot => [slot, MOTIFS[values.motifs[slot]](p)]));
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
    ${backdrop(p, template === "cinema")}${TEMPLATES[template](p, art)}
  </svg>`;
}
