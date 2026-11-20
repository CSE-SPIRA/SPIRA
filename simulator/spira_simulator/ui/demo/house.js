// The 3D house on page 2: living room + kitchen + entrance, fixed layout.
// Device looks come only from World snapshot values (update); the timeline only
// moves the camera and shows people that the world events put in the house.
import * as THREE from "three";
import { OrbitControls } from "/demo/assets/orbit-controls.js";

const FONT = '"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",sans-serif';
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

const CAMS = {
  overview: [[12, 13, 15.5], [0, 0.2, -0.4]],
  fridge: [[1.6, 4.6, 4.6], [5.0, 1.0, -3.4]],
  living: [[5.5, 8.5, 11.5], [-2.2, 0.4, -0.6]],
  party: [[8.5, 9.5, 13.5], [-1.4, 0.6, -0.6]],
  kitchen: [[1.8, 3.8, 3.4], [4.2, 0.8, -3.4]],
};
const moodOf = (v) => (v && typeof v === "object" ? v.scene : v) || null;
const SCENES = { kids_party: "어린이 파티", party: "파티", calm: "차분한 분위기", cinema: "영화" };

function hsvColor(h, s, v) {
  s /= 100; v /= 100;
  const l = v * (1 - s / 2);
  const sl = l === 0 || l === 1 ? 0 : (v - l) / Math.min(l, 1 - l);
  return new THREE.Color().setHSL(h / 360, sl, l);
}
function kelvinColor(k) {
  const t = k / 100;
  const r = t <= 66 ? 255 : 329.7 * Math.pow(t - 60, -0.1332);
  const g = t <= 66 ? 99.47 * Math.log(t) - 161.1 : 288.1 * Math.pow(t - 60, -0.0755);
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5 * Math.log(t - 10) - 305.0;
  const c = (x) => Math.max(0, Math.min(255, x)) / 255;
  return new THREE.Color(c(r), c(g), c(b));
}
function noticeText(v) {
  if (!v) return [];
  if (typeof v === "string") return [v];
  if (Array.isArray(v)) return v.map((x) => (typeof x === "string" ? x : x.text || x.item || JSON.stringify(x)));
  return [v.text || JSON.stringify(v)];
}

export function createHouse(stage, tagsRoot, hud) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  stage.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#171a20");
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 200);
  const controls = new OrbitControls(camera, renderer.domElement);
  Object.assign(controls, { enableDamping: true, enablePan: false, maxPolarAngle: 1.32, minDistance: 4, maxDistance: 32 });

  scene.add(new THREE.HemisphereLight("#e4e9ff", "#3b3029", 0.9));
  const sun = new THREE.DirectionalLight("#fff3e2", 2.0);
  sun.position.set(9, 15, 11); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12 });
  sun.shadow.bias = -0.0006; scene.add(sun);
  const roomLight = new THREE.PointLight("#ffd9a8", 18, 16, 1.4);
  roomLight.position.set(-2, 2.6, -0.6); scene.add(roomLight);

  const mat = (color, r = 0.8, m = 0) => new THREE.MeshStandardMaterial({ color, roughness: r, metalness: m });
  function box(w, h, d, color, x, y, z, o = {}) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), o.material || mat(color, o.r ?? 0.8, o.m ?? 0));
    m.position.set(x, y, z); m.castShadow = o.cast ?? true; m.receiveShadow = true; (o.parent || scene).add(m); return m;
  }
  function cyl(rt, rb, h, color, x, y, z, o = {}) {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, o.seg || 32), o.material || mat(color, o.r ?? 0.6, o.m ?? 0));
    m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; (o.parent || scene).add(m); return m;
  }
  function canvasTex(w, h) {
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
    return { c, g: c.getContext("2d"), t };
  }
  function screen(w, h, tex, x, y, z) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex.t, toneMapped: false }));
    m.position.set(x, y, z); scene.add(m); return m;
  }

  // Shell: living room (left), kitchen (right), entrance strip (far left).
  const WALL = "#e3ded6";
  box(15.6, 0.4, 10.4, "#262a31", 0, -0.2, 0, { cast: false });
  box(8.5, 0.06, 9, "#b58b5d", -2.75, 0.03, 0, { cast: false, r: 0.7 });
  box(5.5, 0.06, 9, "#d4d6d2", 4.25, 0.03, 0, { cast: false, r: 0.5 });
  box(2.2, 0.07, 3.3, "#8e8981", -5.9, 0.035, 2.85, { cast: false });
  box(14.2, 3, 0.2, WALL, 0, 1.5, -4.6);
  box(0.2, 3, 6.7, WALL, -7.1, 1.5, -1.15);
  box(0.2, 3, 1.1, WALL, -7.1, 1.5, 3.95);
  box(0.2, 0.9, 1.2, WALL, -7.1, 2.55, 2.8);
  box(0.2, 1.1, 2.7, WALL, 1.5, 0.55, -3.15);

  const doorPivot = new THREE.Group(); doorPivot.position.set(-7.05, 0, 2.2); scene.add(doorPivot);
  box(0.08, 2.1, 1.2, "#6d5a48", 0, 1.05, 0.6, { parent: doorPivot });
  const pkg = box(0.6, 0.45, 0.5, "#b88a57", -7.85, 0.32, 2.75);

  // Living room
  box(4.2, 0.02, 3, "#ccb9a6", -1.8, 0.07, 0.5, { cast: false, r: 1 });
  const SOFA = "#5c6b7a";
  box(3.4, 0.45, 1.0, SOFA, -1.8, 0.3, 2.5); box(3.4, 0.8, 0.28, SOFA, -1.8, 0.7, 2.95);
  box(0.3, 0.65, 1.0, SOFA, -3.35, 0.4, 2.5); box(0.3, 0.65, 1.0, SOFA, -0.25, 0.4, 2.5);
  box(1.5, 0.08, 0.8, "#7c5a3c", -1.8, 0.42, 0.6); box(1.3, 0.38, 0.6, "#6b4d33", -1.8, 0.2, 0.6);
  box(2.6, 0.55, 0.5, "#4a3b2f", -1.8, 0.33, -4.15);
  box(2.5, 1.42, 0.08, "#111317", -1.8, 1.6, -4.45, { m: 0.4, r: 0.4 });
  const tvTex = canvasTex(1024, 576);
  screen(2.36, 1.3, tvTex, -1.8, 1.6, -4.405);
  const glowMat = new THREE.MeshStandardMaterial({ color: "#fff", emissive: "#ffd9a8", emissiveIntensity: 1.4 });
  box(6.0, 0.06, 0.06, null, -1.75, 2.9, -4.47, { material: glowMat, cast: false });
  cyl(0.22, 0.18, 0.4, "#8a6a52", 0.9, 0.26, 2.9);
  const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.42, 16, 12), mat("#4f7a52", 0.9));
  leaf.position.set(0.9, 0.8, 2.9); leaf.castShadow = true; scene.add(leaf);

  const vac = new THREE.Group(); scene.add(vac);
  cyl(0.27, 0.27, 0.09, "#2b2e35", 0, 0.1, 0, { parent: vac, r: 0.3, m: 0.3 });
  cyl(0.09, 0.09, 0.04, "#9aa3b0", 0, 0.16, 0, { parent: vac, m: 0.5 });
  const VAC_DOCK = new THREE.Vector3(0.7, 0, -3.9);
  vac.position.copy(VAC_DOCK);

  function person(scale, color, hat) {
    const g = new THREE.Group();
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.22, 0.6, 6, 16), mat(color, 0.8));
    body.position.y = 0.55; body.castShadow = true; g.add(body);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.19, 20, 16), mat("#f0cfb4", 0.7));
    head.position.y = 1.12; head.castShadow = true; g.add(head);
    if (hat) { const h = new THREE.Mesh(new THREE.ConeGeometry(0.12, 0.3, 20), mat(hat, 0.6)); h.position.y = 1.4; g.add(h); }
    g.scale.setScalar(scale); scene.add(g); return g;
  }
  const guests = [
    [person(0.75, "#e58fb6", "#ffd66b"), [-2.7, 0.07, 0.3]],
    [person(0.72, "#8fb0e5", "#ff8fc0"), [-1.1, 0.07, 0.9]],
    [person(0.78, "#f2c46d", "#b99cff"), [-2.0, 0.07, -0.6]],
    [person(1.0, "#6c7f73", null), [-5.6, 0.07, 3.0]],
  ];
  guests.forEach(([m, p]) => { m.position.set(...p); m.visible = false; });

  // Kitchen
  box(3.8, 0.9, 0.7, "#e9e6e0", 3.8, 0.45, -4.1, { r: 0.6 });
  box(3.9, 0.05, 0.75, "#5b5e66", 3.8, 0.925, -4.1, { r: 0.4 });
  const indTex = canvasTex(256, 180);
  const ind = new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.56), new THREE.MeshBasicMaterial({ map: indTex.t, toneMapped: false }));
  ind.rotation.x = -Math.PI / 2; ind.position.set(2.65, 0.952, -4.1); scene.add(ind);
  box(0.82, 0.62, 0.04, "#2a2c31", 4.4, 0.42, -3.73, { m: 0.4, r: 0.35 });
  const ovenTex = canvasTex(256, 64);
  screen(0.6, 0.15, ovenTex, 4.4, 0.64, -3.705);
  const kettle = cyl(0.12, 0.14, 0.26, "#d8d8d8", 5.25, 1.08, -4.15, { m: 0.6, r: 0.3 });
  box(1.0, 2.15, 0.85, "#c9ccd1", 6.4, 1.08, -3.95, { m: 0.35, r: 0.35 });
  const frTex = canvasTex(256, 360);
  screen(0.36, 0.5, frTex, 6.15, 1.45, -3.515);
  box(1.6, 0.06, 0.9, "#a07a55", 4.0, 0.78, -1.1);
  [[3.35, -1.45], [4.65, -1.45], [3.35, -0.75], [4.65, -0.75]].forEach(([x, z]) => box(0.07, 0.75, 0.07, "#8a6748", x, 0.39, z));

  // ---------- device faces, drawn from values ----------
  function drawTV(mood) {
    const { g, c, t } = tvTex, W = c.width, H = c.height;
    if (!mood) {
      g.fillStyle = "#0b0c10"; g.fillRect(0, 0, W, H); t.needsUpdate = true; return;
    }
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#ff9ccb";
    const bg = g.createLinearGradient(0, 0, W, H); bg.addColorStop(0, accent); bg.addColorStop(1, "#a98cff");
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    let seed = 7; const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
    for (let i = 0; i < 70; i++) { g.fillStyle = `rgba(255,255,255,${0.35 + rnd() * 0.5})`; g.beginPath(); g.arc(rnd() * W, rnd() * H, 1.5 + rnd() * 3.5, 0, 7); g.fill(); }
    g.fillStyle = "#fff"; g.textAlign = "center";
    g.font = `700 88px ${FONT}`; g.fillText(SCENES[mood] || mood, W / 2, 320);
    g.font = `500 34px ${FONT}`; g.fillStyle = "rgba(255,255,255,.9)"; g.fillText("♪ 분위기 화면", W / 2, 420);
    t.needsUpdate = true;
  }
  function drawOven(preset) {
    const { g, c, t } = ovenTex; g.fillStyle = "#07080a"; g.fillRect(0, 0, c.width, c.height);
    g.textAlign = "center"; g.textBaseline = "middle"; g.font = `600 28px ${FONT}`;
    const on = preset && (preset.temp_c || preset.minutes);
    g.fillStyle = on ? "#ffb24a" : "#2a2c31";
    g.fillText(on ? `${preset.temp_c}℃ ${preset.minutes}분 대기` : "--:--", c.width / 2, c.height / 2 + 2);
    t.needsUpdate = true;
  }
  function drawFridge(lines) {
    const { g, c, t } = frTex; g.fillStyle = lines.length ? "#18202c" : "#0d0f13"; g.fillRect(0, 0, c.width, c.height);
    g.textAlign = "left"; g.font = `500 21px ${FONT}`;
    lines.slice(0, 3).forEach((text, i) => {
      const y = 20 + i * 112;
      g.fillStyle = "#263247"; g.beginPath(); g.roundRect(14, y, c.width - 28, 100, 12); g.fill();
      g.fillStyle = "#e7ecf5";
      const words = text.split(" "); let line = "", ly = y + 30;
      for (const w of words) {
        if (g.measureText(line + w).width > c.width - 56) { g.fillText(line, 28, ly); line = ""; ly += 26; if (ly > y + 90) break; }
        line += w + " ";
      }
      if (ly <= y + 90) g.fillText(line, 28, ly);
    });
    t.needsUpdate = true;
  }
  function drawInduction(locked) {
    const { g, c, t } = indTex; g.fillStyle = "#121317"; g.fillRect(0, 0, c.width, c.height);
    g.strokeStyle = "#3a3d45"; g.lineWidth = 4;
    [[70, 90, 50], [180, 70, 38], [180, 130, 30]].forEach(([x, y, r]) => { g.beginPath(); g.arc(x, y, r, 0, 7); g.stroke(); });
    if (locked) { g.fillStyle = "#ff6b6b"; g.font = `700 26px ${FONT}`; g.textAlign = "center"; g.fillText("잠금", 128, 168); }
    t.needsUpdate = true;
  }
  drawTV(null); drawOven(null); drawFridge([]); drawInduction(false);

  // ---------- tags ----------
  const TAGS = {
    light_01: { name: "거실 조명", at: new THREE.Vector3(-4.2, 3.15, -4.4) },
    display_01: { name: "TV", at: new THREE.Vector3(-1.8, 2.5, -4.3) },
    fridge_01: { name: "냉장고 화면", at: new THREE.Vector3(6.4, 2.35, -3.5) },
    oven_01: { name: "오븐", at: new THREE.Vector3(4.4, 0.95, -3.6) },
    cooktop_01: { name: "인덕션", at: new THREE.Vector3(2.65, 1.25, -4.1) },
    plug_kettle: { name: "전기포트 플러그", at: new THREE.Vector3(5.25, 1.45, -4.15) },
    cleaner_01: { name: "로봇청소기", at: null },
  };
  for (const tag of Object.values(TAGS)) {
    tag.el = document.createElement("div"); tag.el.className = "tag"; tagsRoot.appendChild(tag.el);
    tag.changedAt = 0; tag.text = "";
  }
  let reasons = {};
  let lastValues = {};

  function statusText(id, v) {
    switch (id) {
      case "light_01":
        if (v.power === false) return "꺼짐";
        if (v.color?.hue != null) return `색 ${v.color.hue}° · 밝기 ${v.color.brightness}`;
        return v.color?.kelvin ? `${v.color.kelvin}K (평소)` : "켜짐";
      case "display_01": { const m = moodOf(v.play_mood); return m ? SCENES[m] || m : "꺼짐"; }
      case "fridge_01": return noticeText(v.show_notice).length ? "안내 표시 중" : "평소 화면";
      case "oven_01": return v.preset ? `${v.preset.temp_c}℃ ${v.preset.minutes}분 대기` : v.in_use ? "사용 중" : "꺼짐";
      case "cooktop_01": return v.child_lock ? "잠금" : v.in_use ? "사용 중" : "평소";
      case "plug_kettle": return v.power === false ? "전원 차단" : "켜짐";
      case "cleaner_01": return v.job_status === "running" || v.in_use ? "청소 중" : "충전 중";
      default: return "";
    }
  }

  const target = { light: new THREE.Color("#ffd9a8"), lightI: 18, door: 0 };
  let cleaning = false;

  function update(snapshot) {
    const now = performance.now();
    for (const d of snapshot.devices) {
      const v = d.values, id = d.logical_id;
      const key = JSON.stringify(v);
      const changed = lastValues[id] !== undefined && lastValues[id] !== key;
      lastValues[id] = key;
      if (id === "light_01") {
        if (v.power === false) { target.light.set("#222"); target.lightI = 2; }
        else if (v.color?.hue != null) {
          target.light.copy(hsvColor(v.color.hue, v.color.saturation, v.color.brightness));
          target.lightI = 14 + (v.color.brightness || 70) * 0.25;
          document.documentElement.style.setProperty("--house-accent", `#${target.light.getHexString()}`);
        } else { target.light.copy(kelvinColor(v.color?.kelvin || 3000)); target.lightI = 18; }
      }
      if (id === "display_01") drawTV(moodOf(v.play_mood));
      if (id === "oven_01") drawOven(v.preset);
      if (id === "fridge_01") drawFridge(noticeText(v.show_notice));
      if (id === "cooktop_01") drawInduction(v.child_lock);
      if (id === "plug_kettle") kettle.material.color.set(v.power === false ? "#7a7a7a" : "#d8d8d8");
      if (id === "cleaner_01") cleaning = v.job_status === "running" || !!v.in_use;
      const tag = TAGS[id];
      if (!tag) continue;
      if (changed) tag.changedAt = now;
      const on = now - tag.changedAt < 10000;
      const why = on && reasons[id] ? `<span class="why">${reasons[id]}</span>` : "";
      const html = `<b>${tag.name}</b><span class="st">${statusText(id, v)}</span>${why}`;
      if (html !== tag.text) { tag.el.innerHTML = html; tag.text = html; }
      tag.el.classList.toggle("on", on);
    }
  }

  function setMoment(id) {
    const inHouse = id === "guests" || id === "party";
    guests.forEach(([m]) => (m.visible = inHouse));
    pkg.visible = !["delivery", "before", "guests", "party", "end"].includes(id);
    target.door = id === "delivery" || id === "guests" ? 1.25 : 0;
    hud.innerHTML = "";
  }

  const camFrom = { p: new THREE.Vector3(), t: new THREE.Vector3() };
  const camTo = { p: new THREE.Vector3(), t: new THREE.Vector3() };
  let camT = 1;
  function focus(name) {
    const [p, t] = CAMS[name] || CAMS.overview;
    camFrom.p.copy(camera.position); camFrom.t.copy(controls.target);
    const k = camera.aspect < 1 ? 1.7 : camera.aspect < 1.45 ? 1.3 : 1;
    camTo.t.set(...t); camTo.p.set(...p).sub(camTo.t).multiplyScalar(k).add(camTo.t);
    camT = reduce ? 1 : 0;
    if (reduce) { camera.position.copy(camTo.p); controls.target.copy(camTo.t); }
  }

  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(stage);

  const v = new THREE.Vector3(); let vacA = 0; const clock = new THREE.Clock();
  const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
  function frame() {
    const dt = Math.min(clock.getDelta(), 0.05);
    if (camT < 1) {
      camT = Math.min(1, camT + dt / 1.4); const e = ease(camT);
      camera.position.lerpVectors(camFrom.p, camTo.p, e); controls.target.lerpVectors(camFrom.t, camTo.t, e);
    }
    controls.update();
    roomLight.color.lerp(target.light, 0.06); roomLight.intensity += (target.lightI - roomLight.intensity) * 0.06;
    glowMat.emissive.copy(roomLight.color);
    doorPivot.rotation.y += (target.door - doorPivot.rotation.y) * 0.08;
    if (cleaning) { vacA += dt * 0.7; vac.position.set(-1.8 + Math.cos(vacA) * 2.3, 0, 0.4 + Math.sin(vacA) * 1.5); vac.rotation.y = -vacA; }
    else vac.position.lerp(VAC_DOCK, 0.05);
    const w = stage.clientWidth, h = stage.clientHeight;
    for (const tag of Object.values(TAGS)) {
      const p = (tag.at ? v.copy(tag.at) : v.set(vac.position.x, 0.6, vac.position.z)).project(camera);
      if (p.z > 1 || Math.abs(p.x) > 1.1 || Math.abs(p.y) > 1.1) { tag.el.style.opacity = 0; continue; }
      tag.el.style.opacity = "";
      tag.el.style.transform = `translate(-50%,-100%) translate(${(p.x * 0.5 + 0.5) * w}px,${(-p.y * 0.5 + 0.5) * h - 6}px)`;
    }
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  camera.position.set(...CAMS.overview[0]); controls.target.set(...CAMS.overview[1]);
  resize();
  frame();

  return { resize, update, focus, setMoment, setReasons: (r) => (reasons = r || {}) };
}
