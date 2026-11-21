import assert from "node:assert/strict";
import test from "node:test";
import { createLivingLight, fitViewerCamera, layoutViewerLabels, orientHouseCamera, projectHouseLabels } from "../spira_simulator/ui/house/house.js";
import { MeshStandardMaterial, OrthographicCamera, PointLight, Vector3 } from "../spira_simulator/ui/house/three.module.min.js";

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
