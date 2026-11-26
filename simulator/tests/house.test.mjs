import assert from "node:assert/strict";
import test from "node:test";
import { createFridgePanel, createLivingLight, entrancePresentation, fitViewerCamera, layoutViewerLabels, orientHouseCamera, projectHouseLabels, tvSceneTransition } from "../spira_simulator/ui/house/house.js";
import { MeshStandardMaterial, OrthographicCamera, PointLight, SRGBColorSpace, Vector3 } from "../spira_simulator/ui/house/vendor/three.module.min.js";
import { houseHarness } from "./house-fixture.mjs";

test("change markers stay together until selected and toggle the close-up by click or Escape", (t) => {
  const width = 920, height = 560;
  const view = houseHarness(t, { width, height });
  const { house, stage, rendererCanvas } = view;
  const layer = stage.children.find(({ className }) => className === "house-change-markers");
  const detail = stage.children.find(({ className }) => className === "house-change-detail");
  house.showChangeMarkers(["display_01", "light_01", "unknown"], id =>
    id === "light_01" ? { observed: "노란 빛" } : {});
  view.draw(100);
  const overview = view.camera.position.toArray();
  const [display, light] = layer.children;
  assert.equal(layer.children.length, 2);
  assert.ok(layer.children.every(marker => marker.type === "button" && !marker.hidden));
  assert.match(light.getAttribute("aria-label"), /거실 조명 · 변경 보기/);
  assert.notDeepEqual([display.style.left, display.style.top], [light.style.left, light.style.top]);
  assert.ok(detail.hidden);

  light.onclick();
  view.draw(2000);
  assert.ok(display.hidden);
  assert.equal(light.getAttribute("aria-expanded"), "true");
  assert.equal(detail.textContent, "거실 조명 · 노란 빛");
  assert.notDeepEqual(view.camera.position.toArray(), overview);
  light.onclick();
  view.draw(4000);
  assert.ok(detail.hidden);
  assert.deepEqual(view.camera.position.toArray(), overview);

  view.scene.updateMatrixWorld(true);
  const point = new Vector3(-.70, 1.52, -3.419).project(view.camera);
  rendererCanvas.onclick({ clientX: (point.x + 1) * width / 2, clientY: (1 - point.y) * height / 2 });
  assert.equal(display.getAttribute("aria-expanded"), "true");
  assert.equal(detail.hidden, false);
  document.onkeydown({ key: "Escape", preventDefault() {} });
  assert.equal(document.activeElement, display);
  assert.ok(detail.hidden);
  assert.ok(layer.children.every(marker => !marker.hidden));

  light.onclick();
  house.clearChangeMarkers();
  assert.ok(detail.hidden);
  assert.deepEqual(layer.children, []);
});

test("observed light values drive the pendant, point light, and room glow", () => {
  const lamp = new PointLight("#ffffff", 0);
  const material = new MeshStandardMaterial();
  const glow = { value: 0 };
  const livingLight = createLivingLight(lamp, material, glow);
  function observe(color, power, at) {
    const snapshot = { devices: [{ logical_id: "light_01", values: { power, color } }] };
    livingLight.update(snapshot.devices[0].values, at);
  }

  const pink = { hue: 330, saturation: 45, brightness: 70 };
  observe(pink, true, 0);
  livingLight.render(0);
  assert.equal(lamp.intensity, 0);
  livingLight.render(500);
  assert.equal(glow.value, .35);
  livingLight.render(1000);
  assert.equal(glow.value, .7);
  assert.equal(lamp.color.getHexString(), "ff8cc6");
  assert.ok(material.emissive.equals(lamp.color));
  const brightIntensity = lamp.intensity;
  const brightEmissive = material.emissiveIntensity;

  observe({ ...pink, brightness: 35 }, true, 1100);
  livingLight.render(2100);
  assert.equal(lamp.intensity, brightIntensity / 2);
  assert.equal(material.emissiveIntensity, brightEmissive / 2);
  assert.equal(lamp.color.getHexString(), "ff8cc6");

  observe({ ...pink, hue: 120 }, true, 2200);
  livingLight.render(3200);
  assert.equal(material.emissive.getHexString(), "8cff8c");
  observe({ ...pink, saturation: 0 }, true, 3300);
  livingLight.render(4300);
  assert.equal(material.emissive.getHexString(), "ffffff");

  observe({ kelvin: 2700 }, true, 4400);
  livingLight.render(5400);
  const warm = lamp.color.clone();
  const whiteIntensity = lamp.intensity;
  observe({ kelvin: 6500 }, true, 5500);
  livingLight.render(6000);
  assert.ok(warm.b < lamp.color.b);
  const midwayBlue = lamp.color.b;
  livingLight.render(6500);
  assert.ok(midwayBlue < lamp.color.b);
  assert.ok(material.emissive.equals(lamp.color));
  assert.equal(lamp.intensity, whiteIntensity);

  observe(pink, false, 6600);
  livingLight.render(7600);
  assert.equal(lamp.intensity, 0);
  assert.equal(material.emissiveIntensity, 0);
  assert.equal(glow.value, 0);
});

test("a new parcel does not reactivate the lock light from a previous door signal", () => {
  assert.deepEqual(entrancePresentation(["presence", "door", "doorbell", "package"]),
    { packagePresent: true, signal: "door" });
  assert.deepEqual(entrancePresentation(["package", "presence", "door", "doorbell"]),
    { packagePresent: true, signal: "package" });
});

test("a guest departure leaves the latest entrance signal in place", () => {
  assert.deepEqual(entrancePresentation(["empty", "presence", "door", "package"]),
    { packagePresent: true, signal: "door" });
  assert.deepEqual(entrancePresentation(["empty", "presence"]),
    { packagePresent: false, signal: undefined });
});

test("the TV logo starts only after an observed off-to-on transition", () => {
  const on = { scene: "kids_party" };
  assert.deepEqual(tvSceneTransition(undefined, on), { scene: on.scene, poweringOn: false });
  assert.deepEqual(tvSceneTransition(null, on), { scene: on.scene, poweringOn: true });
  assert.deepEqual(tvSceneTransition(on.scene, { scene: "calm" }), { scene: "calm", poweringOn: false });
  assert.deepEqual(tvSceneTransition(on.scene, null), { scene: null, poweringOn: false });
  assert.deepEqual(tvSceneTransition(on.scene, undefined), { scene: undefined, poweringOn: false });
});

test("the TV and fridge panel bypass the active room wash and keep their canvas colors", (t) => {
  const view = houseHarness(t);
  view.markers({
    display_01: { play_mood: { scene: "kids_party" } },
    light_01: { power: true, color: { hue: 330, saturation: 45, brightness: 70 } },
    fridge_01: { show_notice: "차갑게 두세요." },
  });
  view.draw(1200);
  assert.equal(view.scene.getObjectByName("cove_strip").visible, true);
  const compile = (material) => {
    const shader = { uniforms: {}, vertexShader: "#include <worldpos_vertex>", fragmentShader: "#include <opaque_fragment>" };
    material.onBeforeCompile(shader);
    return shader;
  };
  const bezel = view.scene.getObjectByName("display_01").children[0];
  assert.equal(compile(bezel.material).uniforms.livingLevel.value, .7);
  assert.match(compile(bezel.material).fragmentShader, /outgoingLight = mix/);
  const screens = ["tv_screen", "fridge_notice"].map((name) => view.scene.getObjectByName(name));
  const materials = screens.map(({ material }) => material);
  view.house.setPresentation(new Map([["display_01", { resting: true }], ["fridge_01", { resting: true }]]));
  for (const [index, screen] of screens.entries()) {
    const { material } = screen;
    assert.equal(material, materials[index]);
    assert.equal(material.isMeshBasicMaterial, true);
    assert.equal(material.color.getHexString(), "ffffff");
    assert.equal(material.map.colorSpace, SRGBColorSpace);
    assert.equal(material.toneMapped || material.fog || screen.castShadow || screen.receiveShadow, false);
    assert.deepEqual(compile(material).uniforms, {});
    assert.equal(compile(material).fragmentShader, "#include <opaque_fragment>");
  }
});

test("the fridge keeps the plain notice until corresponding artwork loads", () => {
  const frames = [];
  const images = [];
  let invalidations = 0;
  const panel = createFridgePanel((paint) => {
    const frame = { words: [], images: [] };
    frames.push(frame);
    paint({
      fillRect() {},
      fillText(text) { frame.words.push(text); },
      measureText(text) { return { width: text.length * 15 }; },
      createLinearGradient: () => ({ addColorStop() {} }),
      save() {}, restore() {},
      drawImage(image) { frame.images.push([image.src, this.globalAlpha]); },
    }, 360, 420);
  }, () => invalidations++, () => {
    const image = {};
    images.push(image);
    return image;
  });
  const current = () => frames.at(-1);
  const notice = "씻지 말고 키친타월을 깔아 냉장 보관하고, 토요일 꾸미기 직전에 씻어 주세요";
  const later = "생크림은 차갑게 두세요.";
  const firstArt = "data:image/svg+xml;base64,Zmlyc3Q=";
  const secondArt = "data:image/svg+xml;base64,c2Vjb25k";

  panel.show(notice);
  assert.equal(current().words.slice(1).join(""), notice);
  assert.deepEqual(current().images, []);
  assert.equal(images.length, 0);

  panel.show(notice, firstArt);
  assert.equal(current().words.slice(1).join(""), notice);
  assert.deepEqual(current().images, []);
  panel.show(later, secondArt);
  images[0].onload();
  assert.deepEqual(current().words, ["냉장고 안내", later]);
  assert.deepEqual(current().images, []);

  images[1].onload();
  assert.deepEqual(current().words, ["냉장고 안내", later]);
  assert.deepEqual(current().images, [[secondArt, .55]]);
  assert.equal(invalidations, 1);
  panel.show(later);
  assert.deepEqual(current().words, ["냉장고 안내", later]);
  assert.deepEqual(current().images, []);
});

test("the viewer fits the house at desktop and phone widths and keeps labels clear of the table", () => {
  const sizes = {
    entrance: [134, 28], display_01: [142, 73], light_01: [130, 73], cooktop_01: [110, 73],
    fridge_01: [168, 73], oven_01: [188, 73], plug_kettle: [116, 73], cleaner_01: [85, 45],
    purifier_01: [84, 45], styler_01: [110, 45],
  };
  for (const [width, height] of [[1470, 824], [1226, 662], [372, 261]]) {
    const camera = new OrthographicCamera();
    orientHouseCamera(camera, new Vector3(8.5, 10.6, 17.4), new Vector3(-.10, .76, 0), 1, width / height);
    fitViewerCamera(camera, width, height);
    const outline = [[-6.8, -.43, 3.975], [6.8, -.43, -3.975], [-6.72, 2.73, -3.96], [6.8, -.43, 3.975]]
      .map(point => new Vector3(...point).project(camera));
    assert.ok(outline.every(({ x, y }) => Math.abs(x) < 1 && Math.abs(y) < 1));
    assert.ok(outline[1].x - outline[0].x > 1.7);
    if (width < 720) continue;
    const { anchors, ...clearance } = projectHouseLabels(camera, width, height, null, true);
    const markers = Object.entries(sizes).map(([id, [width, height]]) => ({
      id, ...anchors[id], width, height, required: !["purifier_01", "styler_01"].includes(id),
    }));
    const labels = layoutViewerLabels(markers, width, height, clearance);
    assert.equal(labels.length, markers.length);
    for (const [index, label] of labels.entries()) {
      assert.ok(label.top >= 54 && label.bottom <= height - 8);
      assert.ok(label.left >= 8 && label.right <= width - 8);
      for (const obstacle of [...Object.values(clearance), ...labels.slice(index + 1)]) {
        assert.ok(label.right <= obstacle.left || obstacle.right <= label.left ||
          label.bottom <= obstacle.top || obstacle.bottom <= label.top, label.id);
      }
    }
  }
});
