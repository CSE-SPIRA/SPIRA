import * as THREE from "./vendor/three.module.min.js";
import { createCeilingCove } from "./ceiling-cove.js";
import { createHouse, hsvColor } from "./house.js";
import { birthdayCameraViews, birthdayReadings, birthdayScene, pinkLightReading } from "./library-scene.js";
import { applyMotionFrame, guestLooks, motionPath, motionPresets, poseConfetti, slotBuilders } from "./slots.js";

const options = {
  balloon: {
    label: "색과 배치",
    choices: [["분홍·흰색·금색 다발", {}], ["바닥 풍선", { placement: "floor", count: 3 }],
      ["분홍 다발", { palette: "princess_pink" }], ["파랑 다발", { palette: "ocean_blue" }],
      ["노랑 다발", { palette: "sunny_yellow" }]],
  },
  strawberry: { label: "배치", choices: [["냉장고 선반", {}], ["조리대", { placement: "counter" }]] },
  cream: { label: "배치", choices: [["냉장고 선반", {}], ["조리대", { placement: "counter" }]] },
  guest_child: { label: "머리 모양", choices: ["단발", "곱슬머리", "짧은 머리"].map((label, i) => [label, guestLooks[i]]) },
  banner: {
    label: "벽 장식",
    choices: [["가랜드", {}], ["그림", { artwork: new URL("./castle.jpg", import.meta.url).href }]],
  },
};

function createTurntable(card, slot, queue) {
  const scene = new THREE.Scene();
  const key = new THREE.DirectionalLight("#fff0d8", 2.4);
  key.position.set(-3, 7, 4);
  const fill = new THREE.DirectionalLight("#eee6ff", .75);
  fill.position.set(4, 3, -4);
  scene.add(key, fill, new THREE.HemisphereLight("#fff5e7", "#ac8877", 1.65));
  const table = new THREE.Group();
  scene.add(table);
  const deck = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, .04, 56),
    new THREE.MeshStandardMaterial({ color: "#d6b498", roughness: .78 }));
  deck.position.y = -.02;
  table.add(deck);

  const camera = new THREE.OrthographicCamera();
  const target = new THREE.Vector3();
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-hidden", "true");
  const output = canvas.getContext("2d");
  card.prepend(canvas);
  const samples = new Map();
  let object, sample, radius, span, dirty = true;

  function setSample(parameters) {
    object?.removeFromParent();
    const key = JSON.stringify(parameters ?? {});
    if (!samples.has(key)) {
      let model;
      if (slot.id === "ceiling_cove") {
        const cove = createCeilingCove();
        const { color } = pinkLightReading;
        cove.render(new THREE.Color(hsvColor({ ...color, brightness: 100 })), color.brightness / 100);
        model = cove.group;
      } else {
        model = slotBuilders[slot.id](parameters);
      }
      model.addEventListener("artworkchange", () => {
        dirty = true;
        queue();
      });
      samples.set(key, model);
    }
    object = samples.get(key);
    table.add(object);
    sample = null;
    const bounds = new THREE.Box3().setFromObject(object);
    if (slot.id === "banner") {
      object.position.y = parameters?.artwork ? .90 : .50;
      bounds.min.set(-1.34, 0, -.2);
      bounds.max.set(1.34, parameters?.artwork ? .94 : .54, .2);
    } else if (slot.id === "cleaner_sweep") {
      const path = motionPath([[-.54, 0, .30], [.45, 0, .30], [.46, 0, -.12], [-.50, 0, -.25], [-.54, 0, .30]]);
      sample = seconds => applyMotionFrame(motionPresets.cleaner_sweep.sample(seconds, { target: object, path }));
      bounds.min.set(-.85, 0, -.59);
      bounds.max.set(.80, .23, .63);
    } else if (slot.id === "guests_enter") {
      const tracks = object.children.map((target, i) => ({
        target, path: motionPath([[-.55 + .05 * i, 0, -.54], [-.18 + .03 * i, 0, -.24],
          [-.50 + .5 * i, 0, .22 - .12 * i]]),
      }));
      sample = seconds => applyMotionFrame(motionPresets.guests_enter.sample(seconds, { tracks }));
      bounds.min.set(-.76, 0, -.77);
      bounds.max.set(.76, 1.05, .43);
    } else if (slot.id === "light_spread") {
      const { wash } = object.userData;
      sample = seconds => applyMotionFrame(motionPresets.light_spread.sample(seconds, { wash }));
    } else if (slot.id === "confetti") {
      sample = seconds => poseConfetti(object, Math.min(seconds / 2, 1));
      bounds.min.set(-.57, 0, -.57);
      bounds.max.set(.57, 1.24, .57);
    }

    const size = bounds.getSize(new THREE.Vector3());
    if (["strawberry", "cream"].includes(slot.id)) {
      const otherPlacement = parameters?.placement === "counter" ? "fridge" : "counter";
      size.max(new THREE.Box3().setFromObject(slotBuilders[slot.id]({ placement: otherPlacement })).getSize(new THREE.Vector3()));
    }
    radius = Math.max(.28, Math.hypot(size.x, size.z) * .62);
    span = Math.max(size.y * .78, radius * .92);
    target.set(0, size.y * .44, 0);
    const thickness = Math.min(1, radius * 2);
    deck.scale.set(radius, thickness, radius);
    deck.position.y = -.02 * thickness;
    dirty = true;
  }

  setSample();
  return {
    canvas, setSample,
    draw(renderer, now, reduce) {
      if (reduce && !dirty) return;
      dirty = false;
      const density = Math.min(devicePixelRatio, 1.5);
      const width = Math.round(canvas.clientWidth * density), height = Math.round(canvas.clientHeight * density);
      if (!width || !height) return;
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      const aspect = width / height;
      const extent = Math.max(span, radius * 1.16 / aspect);
      Object.assign(camera, { left: -extent * aspect, right: extent * aspect,
        top: extent, bottom: -extent, near: .01, far: 40 });
      camera.position.set(3, target.y + 3, 6);
      camera.lookAt(target);
      camera.updateProjectionMatrix();
      const fixedAngle = ["banner", "ceiling_cove", "light_spread"].includes(slot.id);
      table.rotation.y = fixedAngle ? .23 : reduce ? -.17 : -.17 + now / 13400;
      const duration = motionPresets[slot.id]?.duration ?? 2;
      const moment = slot.id === "guests_enter" ? duration : duration * .46;
      sample?.(reduce ? moment : (now / 1000) % (duration + .7));
      if (renderer.domElement.width !== width || renderer.domElement.height !== height) {
        renderer.setSize(width, height, false);
      }
      renderer.render(scene, camera);
      output.clearRect(0, 0, width, height);
      output.drawImage(renderer.domElement, 0, 0, width, height);
    },
    invalidate() { dirty = true; },
  };
}

function showShelf(slots) {
  const grid = document.querySelector("#slot-grid");
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.16;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const visible = new Map();
  const cards = new Map();
  let pending = 0, drawnAt = -Infinity;
  function queue() {
    if (!pending) pending = requestAnimationFrame(draw);
  }
  function draw(now) {
    pending = 0;
    if (reduce.matches || now - drawnAt >= 30) {
      for (const turntable of visible.values()) turntable.draw(renderer, now, reduce.matches);
      drawnAt = now;
    }
    if (visible.size && !reduce.matches) queue();
  }
  const intersection = new IntersectionObserver(entries => {
    for (const { target, isIntersecting } of entries) {
      if (isIntersecting) visible.set(target, cards.get(target));
      else visible.delete(target);
    }
    queue();
  });
  const resize = new ResizeObserver(entries => {
    for (const { target } of entries) cards.get(target).invalidate();
    queue();
  });
  reduce.addEventListener("change", () => {
    for (const turntable of cards.values()) turntable.invalidate();
    queue();
  });

  for (const slot of slots) {
    const card = document.createElement("article");
    card.className = "slot";
    const caption = document.createElement("div");
    caption.className = "slot-caption";
    const title = document.createElement("h3");
    title.textContent = slot.label;
    const id = document.createElement("code");
    id.className = "slot-id";
    id.textContent = slot.id;
    caption.append(title, id);
    card.append(caption);
    const turntable = createTurntable(card, slot, queue);
    const choice = options[slot.id];
    if (choice) {
      const label = document.createElement("label");
      label.className = "slot-options";
      label.append(choice.label);
      const select = document.createElement("select");
      select.setAttribute("aria-label", `${slot.label} ${choice.label}`);
      for (const [index, [name]] of choice.choices.entries()) select.add(new Option(name, index));
      select.addEventListener("change", () => {
        turntable.setSample(choice.choices[select.selectedIndex][1]);
        queue();
      });
      label.append(select);
      caption.append(label);
    }
    grid.append(card);
    cards.set(turntable.canvas, turntable);
    intersection.observe(turntable.canvas);
    resize.observe(turntable.canvas);
  }
}

async function start() {
  const response = await fetch(new URL("./slots.json", import.meta.url));
  if (!response.ok) throw new Error(`Slot library HTTP ${response.status}`);
  const slots = await response.json();
  const stage = document.querySelector("#house-stage");
  const house = createHouse(stage, { viewer: true, sampleReadings: birthdayReadings });
  function showSample(motion) {
    const input = motion ? { ...birthdayScene, slots: [...birthdayScene.slots, motion] } : birthdayScene;
    const { ok, reasons } = house.setScene(input);
    if (!ok) throw new Error(reasons.join("\n"));
  }
  let sampleArrival = 0;
  function enterGuests() {
    house.setEntrance({ packagePresent: false, guests: { arrival: ++sampleArrival, count: 3 } });
  }

  showSample();
  enterGuests();
  const lightStatus = document.querySelector("#sample-light-status");
  const controls = document.querySelector("#replay");
  for (const slot of slots.filter(({ kind }) => kind === "motion")) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = slot.label;
    button.addEventListener("click", () => {
      if (slot.id === "guests_enter") {
        enterGuests();
        return;
      }
      if (slot.id === "light_spread") {
        house.setSampleReading("light_01", pinkLightReading);
        lightStatus.textContent = "켜짐 · 분홍색";
      }
      showSample({ slot: slot.id, anchor: slot.anchors[0], params: {} });
    });
    controls.append(button);
  }
  document.querySelector("#sample-light-off").addEventListener("click", () => {
    house.setSampleReading("light_01", birthdayReadings.light_01);
    lightStatus.textContent = "꺼짐";
    showSample();
  });
  house.focus();
  const cameras = [...document.querySelectorAll("#cameras button")];
  for (const button of cameras) {
    button.addEventListener("click", () => {
      house.focus(birthdayCameraViews[button.dataset.camera], { instant: true });
      for (const choice of cameras) choice.setAttribute("aria-pressed", String(choice === button));
    });
  }
  showShelf(slots);
}

start().catch(error => {
  document.querySelector("#load-error").hidden = false;
  console.error(error);
});
