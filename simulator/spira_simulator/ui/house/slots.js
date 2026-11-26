import * as THREE from "./vendor/three.module.min.js";
import { createCeilingCove } from "./ceiling-cove.js";
import { createCleanerBody, roundedGeometry } from "./geometry.js";
import { addRoomWash, createRoomWash } from "./room-wash.js";

const colors = {
  princess_pink: "#d979a5", ocean_blue: "#638fae", forest_green: "#698a6f", sunny_yellow: "#e1af57",
};
const skins = { peach: "#edbc9a", tan: "#cb936d", brown: "#925944" };
const ivory = matte("#f0e9dc");
const wood = matte("#936d51");
const brass = matte("#b57d48");
const rose = matte("#af4e76");
const sphereGeometry = new THREE.SphereGeometry(1, 24, 16);
const sharedGeometries = new WeakSet([sphereGeometry]);
const sharedMaterials = new WeakSet([ivory, wood, brass, rose]);
const partyColors = [colors.princess_pink, colors.sunny_yellow, "#c0a0d1", "#8fb6ae", colors.ocean_blue];

function matte(color, properties = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: .78, ...properties });
}

function mesh(group, geometry, material, x, y, z) {
  const object = new THREE.Mesh(geometry, material);
  object.position.set(x, y, z);
  object.castShadow = object.receiveShadow = true;
  group.add(object);
  return object;
}

function box(group, w, h, d, material, x, y, z, bevel = .03) {
  const geometry = roundedGeometry(w, h, d, bevel);
  sharedGeometries.add(geometry);
  return mesh(group, geometry, material, x, y, z);
}

function disk(group, radius, height, material, x, y, z, bottom = radius, sides = 32) {
  return mesh(group, new THREE.CylinderGeometry(radius, bottom, height, sides), material, x, y, z);
}

function egg(group, w, h, d, material, x, y, z) {
  const object = mesh(group, sphereGeometry, material, x, y, z);
  object.scale.set(w, h, d);
  return object;
}

function cord(group, points, radius, material) {
  const path = new THREE.CatmullRomCurve3(points.map(point => new THREE.Vector3(...point)));
  return mesh(group, new THREE.TubeGeometry(path, 18, radius, 6), material, 0, 0, 0);
}

function balloon({ palette = "pink_white_gold", placement = "bunch", count = 5 } = {}) {
  const group = new THREE.Group();
  const mixed = [
    matte("#e97eaa", { roughness: .38 }),
    matte("#fff7ef", { roughness: .37 }),
    matte("#dfab4c", { metalness: .38, roughness: .30 }),
  ];
  const floor = placement === "floor";
  if (!floor) disk(group, .16, .055, brass, 0, .028, 0, .19);
  const positions = floor ? [
    [-.30, .235, -.12], [.19, .219, .17], [.36, .205, -.35], [-.43, .22, .39],
    [-.82, .22, -.16], [.72, .21, .28], [-.30, .21, -.68], [.13, .218, .70],
  ] : [
    [0, 2.02, -.17], [-.45, 1.85, .02], [.44, 1.76, -.12], [.02, 1.56, .25],
    [-.32, 1.45, -.29], [.25, 1.28, -.21], [-.48, 1.19, .16], [.53, 1.40, .20],
  ];
  for (const [i, [x, y, z]] of positions.slice(0, count).entries()) {
    const rubber = palette === "pink_white_gold" ? mixed[i % mixed.length] : matte(
      new THREE.Color(colors[palette]).lerp(new THREE.Color("#fff0e0"), .11 * (i % 3)), { roughness: .38 });
    const tether = new THREE.Group();
    tether.position.set(x, y, z);
    tether.rotation.z = floor ? Math.PI / 2 + .12 * (i % 3 - 1) : -.24 * Math.sign(x);
    tether.rotation.y = floor ? i * 2.4 : 0;
    group.add(tether);
    const size = floor ? y / .267 : 1;
    egg(tether, .265 * size, .333 * size, .249 * size, rubber, 0, 0, 0);
    disk(tether, .020, .043, rubber, 0, -.336 * size, 0, .029);
    if (!floor) {
      const knot = new THREE.Vector3(0, -.355, 0).applyEuler(tether.rotation).add(tether.position);
      cord(group, [[0, .05, 0], [knot.x * .49, knot.y * .55, z * .20], knot.toArray()], .007, wood);
    }
  }
  return group;
}

function partyHat({ count = 3 } = {}) {
  const group = new THREE.Group();
  group.scale.setScalar(1.55);
  const spread = count === 1 ? 0 : count < 4 ? .17 : .24;
  for (let index = 0; index < count; index++) {
    const angle = index / count * Math.PI * 2;
    const x = spread * Math.cos(angle), z = spread * Math.sin(angle);
    disk(group, .006, .218, matte(partyColors[index % partyColors.length]), x, .124, z, .094);
    disk(group, .094, .026, ivory, x, .014, z, .096);
    egg(group, .033, .030, .033, index % 2 ? rose : brass, x, .239, z);
    // Three tiny paper dots give the cones a printed face at close range.
    for (const [azimuth, y] of [[-.52, .065], [.25, .11], [.77, .054]]) {
      const radius = .103 - y * .39;
      egg(group, .013, .013, .009, ivory, x + Math.sin(azimuth) * radius, y, z + Math.cos(azimuth) * radius)
        .rotation.y = azimuth;
    }
  }
  return group;
}

function cakeTopper() {
  const group = new THREE.Group();
  group.scale.setScalar(1.55);
  const paper = matte("#baa6ca"), sponge = matte("#c08755"), icing = matte("#f1bbc9");
  disk(group, .278, .035, ivory, 0, .023, 0, .206);
  const rim = mesh(group, new THREE.TorusGeometry(.269, .009, 8, 48), brass, 0, .042, 0);
  rim.rotation.x = -Math.PI / 2;

  for (const [x, z] of [[0, -.075], [-.151, .068], [.151, .068]]) {
    disk(group, .102, .084, paper, x, .079, z, .073, 16);
    for (let pleat = 0; pleat < 12; pleat++) {
      const angle = pleat * Math.PI / 6;
      egg(group, .011, .033, .011, ivory, x + .085 * Math.cos(angle), .081, z + .085 * Math.sin(angle));
    }
    egg(group, .108, .053, .108, sponge, x, .129, z);
    for (const [radius, y] of [[.096, .163], [.075, .194], [.048, .225], [.024, .248]]) {
      egg(group, radius, .034, radius, icing, x + (y - .19) * .16, y, z);
    }
  }

  disk(group, .012, .20, wood, 0, .316, -.075);
  const crown = new THREE.Shape();
  crown.moveTo(-.115, 0);
  crown.lineTo(-.151, .123); crown.lineTo(-.065, .084);
  crown.lineTo(0, .16); crown.lineTo(.065, .084);
  crown.lineTo(.151, .123); crown.lineTo(.115, 0); crown.closePath();
  mesh(group, new THREE.ExtrudeGeometry(crown, {
    depth: .024, bevelSize: .011, bevelThickness: .009, bevelSegments: 2, steps: 1,
  }), brass, 0, .369, -.075);
  egg(group, .026, .026, .013, rose, 0, .414, -.041);
  return group;
}

function strawberry({ placement = "fridge" } = {}) {
  const group = new THREE.Group();
  const pulp = matte("#c34e49", { roughness: .60 });
  const seeds = matte("#f3c18e");
  const leaf = matte("#657d54");
  const tray = matte("#b9cfb3");
  box(group, .51, .045, .363, tray, 0, .023, 0);
  for (const x of [-.234, .234]) box(group, .043, .075, .36, tray, x, .052, 0, .013);
  for (const z of [-.16, .16]) box(group, .46, .075, .042, tray, 0, .052, z, .013);
  for (const x of [-.147, 0, .147]) for (const z of [-.072, .072]) {
    egg(group, .066, .058, .063, pulp, x, .089, z);
    egg(group, .047, .047, .047, pulp, x, .067, z);
    for (const offset of [-.022, .022]) {
      egg(group, .033, .010, .016, leaf, x + offset, .145, z).rotation.y = offset * 26;
    }
    for (const [dx, dy, dz] of [[-.023, .012, .056], [.025, .023, .049], [0, -.015, .057], [0, .037, -.041]]) {
      egg(group, .006, .008, .004, seeds, x + dx, .089 + dy, z + dz);
    }
  }
  box(group, .193, .042, .009, ivory, 0, .054, .183, .006);
  box(group, .064, .011, .007, pulp, 0, .054, .19, .002);
  if (placement === "counter") group.scale.setScalar(1.30);
  return group;
}

function cream({ placement = "fridge" } = {}) {
  const group = new THREE.Group();
  const white = matte("#fff8ee"), blue = matte("#366d9c");
  disk(group, .163, .205, white, 0, .105, 0, .142);
  disk(group, .158, .087, blue, 0, .105, 0, .149);
  disk(group, .173, .035, white, 0, .219, 0);
  disk(group, .156, .007, blue, 0, .239, 0);
  egg(group, .027, .031, .005, white, 0, .105, .157).rotation.z = -.17;
  if (placement === "counter") group.scale.setScalar(.90);
  return group;
}

function pegDoll({ skin, outfit, variant, scale }) {
  const group = new THREE.Group();
  const complexion = matte(skins[skin]);
  const fabric = matte(colors[outfit]);
  const hair = matte({ bow: "#4c3430", bob: "#302c38", curls: "#402d35", crop: "#584139", bun: "#48352e" }[variant]);
  const hem = matte(fabric.color.clone().multiplyScalar(.73));
  const profile = [[0, .032], [.131, .032], [.170, .056], [.180, .13], [.172, .28],
    [.155, .41], [.130, .49], [.080, .53], [0, .54]].map(point => new THREE.Vector2(...point));
  mesh(group, new THREE.LatheGeometry(profile, 32), fabric, 0, 0, 0);
  disk(group, .176, .025, hem, 0, .08, 0, .171);
  for (const side of [-1, 1]) {
    const hand = egg(group, .042, .092, .042, complexion, side * .157, .273, .005);
    hand.rotation.z = side * .24;
    const sleeve = egg(group, .058, .070, .051, fabric, side * .148, .349, 0);
    sleeve.rotation.z = side * .34;
    egg(group, .060, .046, .078, hem, side * .078, .043, .052);
  }
  disk(group, .078, .033, ivory, 0, .511, 0);
  egg(group, .147, .160, .142, complexion, 0, .664, .01);
  const hairCap = mesh(group,
    new THREE.SphereGeometry(1, 24, 16, 0, 2 * Math.PI, 0, variant === "crop" ? 1.51 : 1.72),
    hair, 0, .697, 0);
  hairCap.scale.set(.158, .149, .151);
  hairCap.rotation.x = -.23;
  if (variant === "bob" || variant === "bow") {
    for (const side of [-1, 1]) egg(group, .049, .112, .096, hair, side * .115, .642, -.04);
  }
  if (variant === "curls") {
    for (let i = 0; i < 6; i++) {
      const angle = i * Math.PI / 3;
      egg(group, .048, .052, .045, hair, .123 * Math.cos(angle), .781 + (i % 2) * .017, .113 * Math.sin(angle));
    }
  }
  if (variant === "bun") egg(group, .077, .071, .076, hair, .032, .799, -.108);
  if (variant === "bow") {
    egg(group, .052, .025, .026, rose, -.048, .825, .092).rotation.z = -.4;
    egg(group, .052, .025, .026, rose, .046, .825, .092).rotation.z = .4;
    egg(group, .025, .026, .029, brass, 0, .824, .098);
  }
  group.scale.setScalar(scale);
  return group;
}

function child({ skin = "peach", outfit = "princess_pink" } = {}) {
  return pegDoll({ skin, outfit, variant: "bow", scale: 1.23 });
}

function guestChild({ skin = "tan", outfit = "ocean_blue", variant = "bob" } = {}) {
  return pegDoll({ skin, outfit, variant, scale: { bob: 1.10, curls: 1.01, crop: 1.16 }[variant] });
}

function adult({ skin = "peach", outfit = "forest_green" } = {}) {
  return pegDoll({ skin, outfit, variant: "bun", scale: 1.69 });
}

export const guestLooks = [
  { variant: "bob", skin: "tan", outfit: "ocean_blue" },
  { variant: "curls", skin: "brown", outfit: "sunny_yellow" },
  { variant: "crop", skin: "peach", outfit: "forest_green" },
];

function confetti({ count = 24 } = {}) {
  const group = new THREE.Group();
  const geometry = new THREE.PlaneGeometry(.061, .096);
  const paper = partyColors.map(color => new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide }));
  for (let i = 0; i < count; i++) {
    const bit = mesh(group, geometry, paper[i % paper.length], 0, 0, 0);
    bit.castShadow = false;
  }
  poseConfetti(group, .46);
  return group;
}

export function poseConfetti(group, progress) {
  for (const [i, bit] of group.children.entries()) {
    const angle = i * 2.399963;
    const speed = .65 + (i % 7) * .11;
    const distance = speed * progress;
    bit.position.set(Math.cos(angle) * distance,
      .12 + (2.25 + (i % 5) * .22) * progress - 2.1 * progress ** 2,
      Math.sin(angle) * distance);
    bit.rotation.set(angle + 8 * progress, angle - 4 * progress, angle);
    bit.scale.setScalar(Math.max(.03, Math.min(1, progress * 12, (1 - progress) * 9)));
  }
}

function pennant(group, width, height, material) {
  const flag = new THREE.Shape();
  flag.moveTo(-width / 2, 0);
  flag.lineTo(width / 2, 0);
  flag.lineTo(width / 2, -height * .72);
  flag.lineTo(0, -height);
  flag.lineTo(-width / 2, -height * .72);
  flag.closePath();
  return mesh(group, new THREE.ShapeGeometry(flag), material, 0, 0, .006);
}

const letterMaterials = new Map();

function pennantLetter(letter) {
  if (!globalThis.document?.createElement) return null;
  if (!letterMaterials.has(letter)) {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 128;
    const ctx = canvas.getContext("2d");
    ctx.font = '900 112px "Arial Black", Arial, sans-serif';
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    ctx.lineJoin = "round";
    ctx.lineWidth = 8;
    ctx.strokeStyle = "#4b1330";
    ctx.fillStyle = "#ffda69";
    ctx.strokeText(letter, 64, 104);
    ctx.fillText(letter, 64, 104);
    const map = new THREE.CanvasTexture(canvas);
    map.colorSpace = THREE.SRGBColorSpace;
    const material = new THREE.MeshBasicMaterial({ map, alphaTest: .3, toneMapped: false });
    letterMaterials.set(letter, material);
    sharedMaterials.add(material);
  }
  return letterMaterials.get(letter);
}

function banner({ color = "princess_pink", artwork = null } = {}) {
  const group = new THREE.Group();
  const flags = new THREE.Group();
  group.add(flags);
  const paper = new THREE.MeshBasicMaterial({
    color: color === "princess_pink" ? "#d61970" : colors[color],
    side: THREE.DoubleSide,
    toneMapped: false,
  });
  const glyph = new THREE.PlaneGeometry(.238, .238);
  for (const [word, height] of [["HAPPY", 0], ["BIRTHDAY", -.238]]) {
    const length = word.length * .153 + .067;
    const hang = x => height - .034 * (1 - (x / length) ** 2);
    cord(flags, [-1, -.5, 0, .5, 1].map(fraction => [length * fraction, hang(length * fraction), 0]), .009, wood);
    for (const side of [-1, 1]) egg(flags, .027, .027, .019, brass, side * length, height, 0);
    for (const [index, letter] of Array.from(word).entries()) {
      const x = (index - (word.length - 1) / 2) * .306;
      const flag = new THREE.Group();
      flag.position.set(x, hang(x) - .006, 0);
      flag.rotation.z = x * .081;
      flags.add(flag);
      pennant(flag, .284, .216, paper);
      const lettering = pennantLetter(letter);
      if (lettering) mesh(flag, glyph, lettering, 0, -.084, .010).castShadow = false;
    }
  }
  if (artwork && typeof document !== "undefined") {
    let disposed = false;
    group.addEventListener("dispose", () => { disposed = true; });
    new THREE.TextureLoader().load(artwork, texture => {
      if (disposed) {
        texture.dispose();
        return;
      }
      texture.colorSpace = THREE.SRGBColorSpace;
      const fabric = matte(new THREE.Color(colors[color]).multiplyScalar(.72), { side: THREE.DoubleSide });
      const frame = box(group, 1.79, .80, .036, fabric, 0, -.483, .011);
      const panel = mesh(group, new THREE.PlaneGeometry(1, 1),
        new THREE.MeshBasicMaterial({ map: texture, side: THREE.DoubleSide, toneMapped: false }),
        0, -.483, .033);
      const aspect = texture.image.width / texture.image.height;
      panel.scale.set(Math.min(1.70, .71 * aspect), Math.min(.71, 1.70 / aspect), 1);
      frame.castShadow = panel.castShadow = false;
      flags.visible = false;
      group.dispatchEvent({ type: "artworkchange" });
    });
  }
  return group;
}

function routeCue(color) {
  const cue = new THREE.Mesh(new THREE.RingGeometry(.06, .12, 24),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .75, depthWrite: false }));
  cue.geometry.rotateX(-Math.PI / 2);
  return cue;
}

function cleanerSweep(_params, { inHouse } = {}) {
  if (inHouse) return routeCue("#ffffff");
  return createCleanerBody(matte("#403936"), matte("#eee0c5"), matte("#c4a99f", { metalness: .31 }),
    matte("#778875", { emissive: "#85bfb6", emissiveIntensity: .3 }));
}

function guestsEnter(_params, { inHouse } = {}) {
  const group = new THREE.Group();
  guestLooks.forEach((look, index) => {
    const guest = inHouse ? routeCue(colors[look.outfit]) : guestChild(look);
    guest.position.set((index - 1) * .50, 0, .15 - index * .12);
    group.add(guest);
  });
  return group;
}

export function createLightSpreadWash({ color = "princess_pink" } = {}) {
  return createRoomWash(colors[color], [-1.77, 1.05, -.18], [3.26, 3.2, 4.15]);
}

function lightSpread({ color = "princess_pink" } = {}, { inHouse } = {}) {
  if (inHouse) {
    const cue = new THREE.Mesh(new THREE.RingGeometry(.48, .55, 48),
      new THREE.MeshBasicMaterial({ color: colors[color], transparent: true, opacity: 0, depthWrite: false }));
    cue.geometry.rotateX(-Math.PI / 2);
    cue.userData.wash = createLightSpreadWash({ color });
    return cue;
  }
  const group = new THREE.Group();
  const wash = createRoomWash(colors[color], [0, .30, 0], [1.05, .86, .91]);
  group.userData.wash = wash;
  const floor = matte("#b98f65"), wall = matte("#e9dfca"), fabric = matte("#dfc5a8");
  for (const material of [floor, wall, fabric]) material.onBeforeCompile = shader => addRoomWash(shader, wash);
  box(group, 1.69, .065, 1.40, floor, 0, .034, 0);
  box(group, 1.69, .68, .09, wall, 0, .37, -.646);
  box(group, .09, .68, 1.40, wall, -.80, .37, 0);
  box(group, .85, .17, .39, fabric, .19, .176, -.32, .045);
  box(group, .85, .29, .12, fabric, .19, .287, -.47, .04);
  for (const x of [-.203, .583]) box(group, .11, .19, .39, fabric, x, .237, -.32, .04);
  return group;
}

// All builders use local coordinates, with the origin at the mounting surface.
export const slotBuilders = Object.freeze({
  balloon, party_hat: partyHat, cake_topper: cakeTopper, strawberry, cream,
  child, guest_child: guestChild, adult, confetti, banner,
  ceiling_cove: () => createCeilingCove().group,
  cleaner_sweep: cleanerSweep, guests_enter: guestsEnter, light_spread: lightSpread,
});

export function motionPath(points) {
  const path = new THREE.CatmullRomCurve3(points.map(point => new THREE.Vector3(...point)));
  path.updateArcLengths();
  return path;
}

function walkPose({ target, path, facing = 0 }, progress) {
  const position = path.getPointAt(progress);
  const tangent = path.getTangentAt(progress);
  const turn = THREE.MathUtils.smoothstep(progress, .87, 1);
  const heading = Math.atan2(tangent.x, tangent.z);
  const facingDelta = Math.atan2(Math.sin(facing - heading), Math.cos(facing - heading));
  const bounce = Math.sin(Math.PI * 36 * progress) ** 2 * Math.sin(Math.PI * progress) * .05;
  position.y += bounce;
  return { target, position, rotationY: progress === 1 ? facing : heading + turn * facingDelta };
}

const sweepDuration = 9.6;
const entryDuration = 4.5;
const spreadDuration = 3.6;

// Times are local elapsed seconds. Sampling returns render poses without changing
// the targets, paths, or anything outside the scene. Apply them only when drawing.
export const motionPresets = Object.freeze({
  cleaner_sweep: {
    duration: sweepDuration,
    sample(seconds, { target, path }) {
      const progress = THREE.MathUtils.clamp(seconds / sweepDuration, 0, 1);
      const tangent = path.getTangentAt(progress);
      const heading = Math.atan2(tangent.x, tangent.z);
      const amount = Math.min(1, progress * 20, (1 - progress) * 20);
      return [{ target, position: path.getPointAt(progress), rotationY: heading * amount }];
    },
  },
  guests_enter: {
    duration: entryDuration,
    sample(seconds, { tracks }) {
      return tracks.map((track, index) => walkPose(track,
        THREE.MathUtils.smoothstep(seconds, (index % 3) * .45, entryDuration - (2 - index % 3) * .24)));
    },
  },
  light_spread: {
    duration: spreadDuration,
    sample(seconds, { wash }) {
      const grow = THREE.MathUtils.smoothstep(seconds, 0, 2.2);
      const settle = THREE.MathUtils.smoothstep(seconds, 2.2, spreadDuration);
      return [{ target: wash, reach: .385 + 1.465 * grow,
        level: .48 * THREE.MathUtils.smoothstep(seconds, 0, .7) - .20 * settle }];
    },
  },
});

export function applyMotionFrame(poses) {
  for (const { target, position, rotationY, reach, level } of poses) {
    if (position) target.position.copy(position);
    if (rotationY !== undefined) target.rotation.y = rotationY;
    if (reach !== undefined) target.spreadReach.value = reach;
    if (level !== undefined) target.spreadLevel.value = level;
  }
}

export function disposeSlot(slot) {
  const geometries = new Set(), materials = new Set();
  slot.traverse(({ geometry, material }) => {
    if (geometry && !sharedGeometries.has(geometry)) geometries.add(geometry);
    if (material && !sharedMaterials.has(material)) materials.add(material);
  });
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) {
    material.map?.dispose();
    material.dispose();
  }
  slot.dispatchEvent({ type: "dispose" });
  slot.removeFromParent();
}
