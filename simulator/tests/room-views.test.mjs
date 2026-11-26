import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import test from "node:test";
import { setImmediate as settle } from "node:timers/promises";
import { houseHarness, projectedMeshes } from "./house-fixture.mjs";

const ui = new URL("../spira_simulator/ui/", import.meta.url);
const profile = JSON.parse(readFileSync(new URL("../spira_simulator/profiles/ep_9031.json", import.meta.url)));
const rooms = ["entrance", "living_room", "kitchen"];

for (const [width, height] of [[1470, 824], [1226, 662], [372, 261]]) {
  test(`the Simulator room links frame their devices at ${width}×${height}`, async (t) => {
    const view = houseHarness(t, { width, height, viewer: true });
    const links = rooms.map(room => ({ hash: `#viewer-room-${room}`, setAttribute() {}, removeAttribute() {} }));
    const sections = rooms.map(room => ({ id: `viewer-room-${room}`, dataset: { room }, toggleAttribute() {} }));
    const events = new Map();
    document.getElementById = (id) => ({
      "viewer-world": {}, "viewer-house": { classList: { add() {} } },
      "viewer-markers": { querySelectorAll: () => [], querySelector: () => null },
    }[id]);
    document.querySelectorAll = (selector) => ({ ".viewer-room": sections, ".room-key a": links }[selector] ?? []);
    document.querySelector = () => null;
    Object.assign(globalThis, {
      window: { addEventListener: (type, listener) => events.set(type, listener), setTimeout() {} },
      location: { hash: "" },
      testHouse: view.house,
    });
    t.after(() => {
      delete globalThis.window;
      delete globalThis.location;
      delete globalThis.testHouse;
    });
    const renderer = new URL("house/house.js", ui).href;
    const hook = registerHooks({
      resolve(specifier, context, nextResolve) {
        if (specifier !== "/sim/assets/house/house.js") return nextResolve(specifier, context);
        return nextResolve("data:text/javascript," + encodeURIComponent(
          `export { HOUSE_ROOM_VIEWS, entrancePresentation, personActionClient, replaceHouseMarkers } from "${renderer}";
           export const createHouse = () => globalThis.testHouse;`), context);
      },
    });
    t.after(() => hook.deregister());
    await import(new URL(`stage.js?width=${width}`, ui));
    await settle();
    for (const [index, link] of links.entries()) {
      location.hash = link.hash;
      events.get("hashchange")();
      view.draw(2000 * (index + 1));
      view.scene.updateMatrixWorld(true);
      const room = rooms[index];
      const ids = profile.devices.filter((device) => device.room === room).map((device) => device.logical_id);
      if (room === "entrance") ids.push("entrance_door");
      for (const id of ids) {
        const { min, max } = projectedMeshes(view.scene.getObjectByName(id), view.camera);
        assert.ok(min.x > -.9 && max.x < .9 && min.y > -1 && max.y < 1, `${room}: ${id}`);
      }
    }
  });
}
