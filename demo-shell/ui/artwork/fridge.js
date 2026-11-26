import { PALETTES } from "./palettes.js";

const FRIDGE_MOTIFS = {
  strawberry: { palette: "festive_red", draw: p => `
    <path d="M13 34Q15 16 36 20Q50 24 63 20Q88 17 91 38Q91 57 68 80Q53 94 42 86Q16 67 13 42Z" fill="url(#fruit)"/>
    <path d="M43 23Q30 22 22 15Q36 13 47 19Q45 11 52 5Q58 11 56 18Q69 11 81 15Q76 23 61 27Q52 31 43 23Z" fill="#4e795c"/>
    <path d="M22 36Q23 27 33 27" fill="none" stroke="${p.haze}" stroke-width="3" stroke-linecap="round"/>
    <path d="M35 37l-2 4m21-3-2 4m20-5-2 4M27 51l2 4m17-3-2 4m21-4-2 4m14-2-2 4M41 65l2 4m15 0-2 4m-7 2 2 4" stroke="${p.glow}" stroke-width="2.2" stroke-linecap="round"/>` },
  cream: { palette: "princess_pink", draw: p => `
    <path d="M16 63H84L77 83Q75 89 68 89H32Q25 89 23 83Z" fill="url(#fruit)"/>
    <path d="M20 63Q16 50 31 45Q23 32 43 28Q38 19 57 14Q65 12 67 7Q77 21 61 28Q78 29 77 41Q91 45 80 62Z" fill="${p.haze}" stroke="${p.accent}" stroke-width="2.7" stroke-linejoin="round"/>
    <path d="M45 29Q52 29 61 28M30 45Q58 49 77 41M23 62Q58 66 80 58" fill="none" stroke="${p.sky}" stroke-width="2.6" stroke-linecap="round"/>
    <path d="M31 72L35 82M45 72L47 84M60 72L57 84M73 72L69 82" stroke="${p.haze}" opacity=".69" stroke-width="2" stroke-linecap="round"/>` },
  milk: { palette: "ocean_blue", draw: p => `
    <path d="M27 35L37 17H67L78 34V80Q78 87 72 87H32Q27 87 27 82Z" fill="url(#fruit)"/>
    <path d="M37 17H66L57 35H27Z" fill="${p.haze}"/>
    <path d="M57 35L66 17L78 34V80Q78 87 72 87H57Z" fill="${p.shade}" opacity=".35"/>
    <rect x="37" y="11" width="32" height="7" rx="2.5" fill="${p.shade}"/>
    <path d="M42 48C51 62 54 66 47 70C40 74 32 69 35 62Z" fill="${p.haze}"/>` },
  egg: { palette: "sunny_yellow", draw: p => `
    <path d="M59 34Q72 17 82 35Q94 51 91 65Q88 80 72 81Q57 81 53 69Q48 53 59 34Z" fill="url(#fruit)"/>
    <path d="M18 46Q34 13 48 38Q62 62 58 76Q54 90 36 90Q18 90 13 78Q8 65 18 46Z" fill="${p.haze}" stroke="${p.accent}" stroke-width="2.4"/>
    <path d="M19 64Q21 50 30 43M68 36Q74 29 79 36" fill="none" stroke="${p.glow}" stroke-width="3.5" stroke-linecap="round"/>
    <path d="M29 75h.1m11 4h.1m3-24h.1m32 11h.1m-9 5h.1" fill="none" stroke="${p.accent}" stroke-width="2.5" stroke-linecap="round"/>` },
  fruit: { palette: "festive_red", draw: p => `
    <path d="M10 58Q8 32 32 34Q47 36 52 32Q75 27 82 46Q88 64 70 83Q58 89 48 83Q35 88 24 80Q15 73 10 58Z" fill="url(#fruit)"/>
    <path d="M48 38Q45 22 52 12" stroke="${p.shade}" stroke-width="4" stroke-linecap="round" fill="none"/>
    <path d="M50 30Q55 12 77 16Q74 35 50 30Z" fill="#56876d"/>
    <path d="M54 27L67 21M20 52Q21 42 32 42" fill="none" stroke="${p.haze}" stroke-width="2.8" stroke-linecap="round"/>
    <circle cx="76" cy="76" r="14" fill="#e2b877" stroke="${p.haze}" stroke-width="2"/>
    <path d="M76 65V87M65 75H87M69 68L83 83M83 68L69 83" stroke="${p.haze}" stroke-width="1.6"/>` },
  vegetable: { palette: "forest_green", draw: p => `
    <path d="M56 37Q54 17 42 11Q39 28 55 42M58 39Q54 20 65 8Q72 23 62 40M62 41Q70 24 84 24Q81 40 62 46" fill="${p.accent}"/>
    <path d="M28 53Q37 36 51 33Q63 31 70 45Q75 55 61 66L27 89Q18 94 18 84Z" fill="#d18b59" stroke="${p.shade}" stroke-width="2.4"/>
    <path d="M38 43Q32 47 28 56M47 49l7 7M31 62l7 4M25 75l5 4" stroke="${p.haze}" stroke-linecap="round" stroke-width="2.8" fill="none"/>
    <path d="M63 78Q68 63 89 65Q85 83 63 78ZM63 78Q58 74 48 77" fill="${p.accent}" stroke="${p.shade}" stroke-width="2.4" stroke-linecap="round"/>` },
  generic: { palette: "calm_neutral", draw: p => `
    <path d="M24 40H76L74 78Q74 85 66 85H34Q26 85 26 78Z" fill="url(#fruit)"/>
    <path d="M16 38L25 26H75L84 38V45H16Z" fill="${p.accent}"/>
    <rect x="20" y="33" width="60" height="6" rx="3" fill="${p.haze}"/>
    <path d="M50 52V73M41 57L59 68M59 57L41 68" stroke="${p.haze}" stroke-width="3.2" stroke-linecap="round"/>` },
};

export const FRIDGE_ICONS = Object.keys(FRIDGE_MOTIFS);
export function fridgeValues(icon, palette) {
  const center = typeof icon === "string" && Object.hasOwn(FRIDGE_MOTIFS, icon) ? icon : "generic";
  const validPalette = typeof palette === "string" && Object.hasOwn(PALETTES, palette);
  return { template: "fridge_panel", palette: validPalette ? palette : FRIDGE_MOTIFS[center].palette, motifs: { center } };
}

export function renderFridge({ palette, motifs }) {
  const values = fridgeValues(motifs?.center, palette);
  const { draw } = FRIDGE_MOTIFS[values.motifs.center];
  const p = PALETTES[values.palette];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="360" height="420" viewBox="0 0 360 420">
    <defs>
      <linearGradient id="wash" x1="0" x2="0" y1="0" y2="1"><stop offset=".42" stop-color="#fffefa"/><stop offset="1" stop-color="${p.sky}"/></linearGradient>
      <linearGradient id="fruit" x1="0" x2="1" y1="0" y2="1"><stop stop-color="${p.sky}"/><stop offset=".6" stop-color="${p.accent}"/><stop offset="1" stop-color="${p.shade}"/></linearGradient>
      <radialGradient id="shadow"><stop stop-color="${p.shade}" stop-opacity=".5"/><stop offset="1" stop-color="${p.shade}" stop-opacity="0"/></radialGradient>
    </defs>
    <rect width="360" height="420" fill="url(#wash)"/>
    <path d="M0 357Q78 332 178 347T360 352V420H0Z" fill="${p.ground}" opacity=".6"/>
    <ellipse cx="180" cy="381" rx="110" ry="20" fill="url(#shadow)"/>
    <ellipse cx="180" cy="370" rx="98" ry="13" fill="${p.haze}"/>
    <ellipse cx="180" cy="370" rx="85" ry="8" fill="none" stroke="${p.ground}" stroke-opacity=".6" stroke-width="1.5"/>
    <g transform="translate(107 229) scale(1.46)">${draw(p)}</g>
  </svg>`;
}
