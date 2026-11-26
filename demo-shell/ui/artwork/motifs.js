// Silhouettes are drawn inside a 0–100 square. The parent template supplies the ceramic glaze.
const glaze = "url(#glaze)";
const star = "M50 8Q53 8 60 34Q62 39 86 42Q92 43 88 49L69 65Q66 68 72 88Q73 94 67 91L50 79Q47 78 30 91Q24 95 26 87L31 68Q32 65 12 49Q7 45 13 43L37 38Q41 37 46 13Q48 8 50 8Z";
const heart = "M50 86C42 77 12 63 12 41C12 21 37 16 50 35C63 16 88 21 88 41C88 63 58 79 50 86Z";
const flower = "M50 28C33 4 17 24 28 42C3 38 6 66 31 66C24 90 50 97 57 73C75 90 96 70 78 56C101 42 80 20 65 36C68 13 47 9 50 28Z";

export const MOTIFS = {
  castle: ({ shade, accent, glow, haze }) => `
    <rect x="13" y="48" width="74" height="40" rx="5" fill="${accent}"/>
    <path d="M33 42H67V88H33Z" fill="url(#glaze)"/>
    <path d="M34 41L49 14Q50 11 52 15L67 41Q68 45 63 45H38Q32 45 34 41Z" fill="${shade}"/>
    <path d="M14 39L23 23Q25 20 27 23L35 39V84Q35 89 30 89H19Q14 89 14 84ZM65 39L74 23Q76 20 78 23L86 39V84Q86 89 81 89H70Q65 89 65 84Z" fill="url(#glaze)"/>
    <path d="M12 42L22 23Q24 19 27 23L37 42ZM63 42L73 23Q75 19 78 23L88 42Z" fill="${shade}"/>
    <path d="M44 88V72A6 6 0 0 1 56 72V88M22 62V53A3 3 0 0 1 28 53V62M72 62V53A3 3 0 0 1 78 53V62" fill="${shade}"/>
    <path d="M47 55V51A3 3 0 0 1 53 51V55Z" fill="${haze}"/>
    <path d="M50 15V6Q60 4 66 10Q57 10 51 14" fill="${glow}"/>
    <path d="M18 46V76M37 49V64M69 46V69" stroke="${haze}" opacity=".52" stroke-width="1.6" stroke-linecap="round"/>`,
  crown: ({ glow, shade, haze }) => `
    <path d="M15 70L8 30Q7 24 13 28L31 43L46 19Q50 12 54 19L69 43L87 28Q93 24 92 30L85 70Q84 75 79 75H21Q16 75 15 70Z" fill="${shade}"/>
    <path d="M16 65L10 30L31 45L50 18L69 45L90 30L84 65Z" fill="${glaze}"/>
    <circle cx="11" cy="27" r="5" fill="${glow}"/><circle cx="50" cy="16" r="6" fill="${glow}"/><circle cx="89" cy="27" r="5" fill="${glow}"/>
    <rect x="16" y="66" width="68" height="12" rx="5" fill="${glow}"/>
    <path d="M50 41L58 51L50 61L42 51Z" fill="${haze}"/>
    <path d="M24 71H72" stroke="${haze}" opacity=".8" stroke-width="2" stroke-linecap="round"/>`,
  balloons: ({ glow, shade, haze }) => `
    <path d="M26 61Q28 77 54 90M54 48Q50 69 54 90M76 60Q69 81 54 90" fill="none" stroke="${shade}" opacity=".8" stroke-width="2"/>
    <ellipse cx="72" cy="44" rx="21" ry="23" fill="${glaze}"/><ellipse cx="30" cy="45" rx="20" ry="23" fill="${glow}"/>
    <ellipse cx="52" cy="31" rx="20" ry="24" fill="${glaze}"/>
    <path d="M46 15Q39 19 39 27M24 30Q18 34 18 40M73 30Q83 31 85 39" fill="none" stroke="${haze}" stroke-width="3" stroke-linecap="round" opacity=".8"/>
    <path d="M52 54L48 59H56ZM29 67L25 72H33ZM73 65L69 70H77Z" fill="${shade}"/>`,
  cake: ({ glow, shade, haze, accent }) => `
    <rect x="19" y="47" width="62" height="34" rx="9" fill="${glaze}"/>
    <path d="M19 57Q27 65 35 58Q42 53 50 59T65 59Q74 53 81 58V46Q80 36 69 36H31Q20 36 19 46Z" fill="${haze}"/>
    <path d="M20 69H80" stroke="${accent}" stroke-width="5" opacity=".65"/>
    <rect x="12" y="79" width="76" height="7" rx="3.5" fill="${shade}"/>
    <path d="M48 38V25Q48 22 51 22Q54 22 54 25V38Z" fill="${accent}"/>
    <path d="M51 10Q63 19 51 21Q44 21 51 10Z" fill="${glow}"/>
    <path d="M28 46l4 2m8-6 2 3m16 4 4-2m9-4 3 2" stroke="${accent}" stroke-width="2" stroke-linecap="round"/>`,
  stars: ({ glow, haze }) => `
    <path d="${star}" fill="${glow}" transform="translate(6 10) scale(.8)"/>
    <path d="${star}" fill="${haze}" transform="translate(66 6) scale(.28)"/>
    <path d="${star}" fill="${haze}" transform="translate(7 67) scale(.25)"/>
    <path d="M39 41L45 28M33 49L25 51" fill="none" stroke="${haze}" stroke-width="2.6" stroke-linecap="round" opacity=".82"/>`,
  hearts: ({ glow, haze }) => `
    <path d="${heart}" fill="${glaze}" transform="translate(-2 6) scale(.88)"/>
    <path d="${heart}" fill="${glow}" transform="translate(65 -1) scale(.34)"/>
    <path d="${heart}" fill="${haze}" transform="translate(65 65) scale(.26)"/>
    <path d="M16 39Q18 30 27 31" fill="none" stroke="${haze}" stroke-width="3" stroke-linecap="round" opacity=".85"/>`,
  confetti: ({ glow, haze, shade, accent }) => `
    <path d="M23 18L32 29M64 34L73 20M33 71L24 84M78 73L86 83M49 47L44 54" fill="none" stroke="${glow}" stroke-width="7" stroke-linecap="round"/>
    <path d="M11 50Q22 42 24 57M59 74Q57 87 46 85M82 45Q93 43 90 54" fill="none" stroke="${shade}" stroke-width="3" stroke-linecap="round" opacity=".65"/>
    <circle cx="51" cy="14" r="4" fill="${haze}"/><circle cx="62" cy="54" r="4" fill="${accent}"/><circle cx="14" cy="69" r="3" fill="${haze}"/>`,
  flowers: ({ shade, glow, haze }) => `
    <path d="M47 88Q50 64 38 46M51 88Q59 65 72 57" stroke="${shade}" stroke-width="3" fill="none" stroke-linecap="round"/>
    <path d="M51 79Q27 81 26 65Q45 64 51 79ZM54 74Q67 73 71 68Q69 84 52 84Z" fill="${shade}" opacity=".87"/>
    <path d="${flower}" transform="translate(6 0) scale(.63)" fill="${glaze}"/>
    <path d="${flower}" transform="translate(47 25) scale(.46)" fill="${glow}"/>
    <circle cx="38" cy="35" r="7" fill="${glow}"/><circle cx="71" cy="50" r="5" fill="${haze}"/>`,
  moon: ({ glow, haze, shade }) => `
    <path d="M64 14A37 37 0 1 0 85 69Q57 80 46 58Q34 35 64 14Z" fill="${glow}"/>
    <path d="M44 23Q16 38 27 64" stroke="${haze}" fill="none" stroke-width="3.6" stroke-linecap="round"/>
    <circle cx="40" cy="65" r="4" fill="${shade}" opacity=".13"/>
    <circle cx="48" cy="75" r="2" fill="${shade}" opacity=".18"/>
    <path d="${star}" fill="${haze}" transform="translate(61 27) scale(.27)"/>`,
  waves: ({ haze, shade, glow }) => `
    <path d="M7 66Q21 36 51 30Q74 25 77 39Q79 50 63 55Q71 45 60 45Q49 45 47 58Q48 71 68 71Q83 71 92 61V76Q80 88 52 87Q22 86 7 76Z" fill="${glaze}"/>
    <path d="M9 66Q25 39 51 32Q72 26 76 38M60 72Q79 78 92 63" stroke="${haze}" fill="none" stroke-width="4" stroke-linecap="round"/>
    <path d="M19 74Q34 83 53 83" stroke="${shade}" opacity=".45" fill="none" stroke-width="2.6" stroke-linecap="round"/>
    <circle cx="83" cy="43" r="3" fill="${glow}"/><circle cx="90" cy="50" r="2" fill="${haze}"/>`,
  film: ({ shade, glow, haze }) => `
    <path d="M58 72Q76 80 88 69L93 78Q78 91 57 84Q45 81 40 89L34 81Q43 68 58 72Z" fill="${glow}"/>
    <circle cx="48" cy="47" r="34" fill="${shade}"/><circle cx="47" cy="43" r="34" fill="${glaze}"/>
    <circle cx="47" cy="43" r="29" fill="none" stroke="${haze}" stroke-opacity=".72" stroke-width="1.5"/>
    <g fill="${shade}"><circle cx="47" cy="24" r="7"/><circle cx="65" cy="37" r="7"/><circle cx="58" cy="58" r="7"/><circle cx="36" cy="58" r="7"/><circle cx="29" cy="37" r="7"/></g>
    <circle cx="47" cy="43" r="3.8" fill="${glow}"/>`,
  candles: ({ glow, haze, shade }) => `
    <rect x="19" y="51" width="17" height="31" rx="4" fill="${glaze}"/>
    <rect x="41" y="37" width="18" height="45" rx="4" fill="${glow}"/>
    <rect x="64" y="49" width="17" height="33" rx="4" fill="${glaze}"/>
    <path d="M24 60V75M46 47V73M69 58V76" fill="none" stroke="${haze}" stroke-width="2" opacity=".85" stroke-linecap="round"/>
    <path d="M27 34Q37 46 27 48Q17 47 27 34ZM50 17Q61 31 50 33Q38 31 50 17ZM72 31Q82 43 72 45Q62 44 72 31Z" fill="${glow}"/>
    <rect x="13" y="82" width="74" height="4" rx="2" fill="${shade}"/>`,
  popcorn: ({ glow, haze, shade }) => `
    <path d="M24 45Q16 35 26 29Q27 17 39 20Q44 9 55 16Q65 10 71 23Q84 23 83 36Q89 46 77 51H27Z" fill="${glow}"/>
    <path d="M31 29Q35 24 40 27M49 23Q53 20 58 24M64 30Q70 26 74 31M39 38Q44 32 50 37M56 36Q60 33 65 37" fill="none" stroke="${haze}" stroke-width="3.4" stroke-linecap="round"/>
    <path d="M19 43H81L72 83Q71 89 65 89H35Q29 89 28 83Z" fill="${glaze}"/>
    <path d="M30 48H39L43 86H36ZM47 48H55L55 86H47ZM64 48H73L65 86H58Z" fill="${haze}" opacity=".85"/>
    <rect x="18" y="42" width="64" height="7" rx="3.5" fill="${shade}"/>
    <path d="M32 83Q50 87 68 83" fill="none" stroke="${shade}" stroke-width="2" opacity=".55"/>`,
};
