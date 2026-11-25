import { createHouse } from "../spira_simulator/ui/house/house.js";
import { Box3, Vector3 } from "../spira_simulator/ui/house/vendor/three.module.min.js";

export function projectedMeshes(model, camera) {
  const bounds = new Box3();
  const vertex = new Vector3();
  model.traverseVisible((mesh) => {
    if (!mesh.isMesh) return;
    const positions = mesh.geometry.attributes.position;
    for (let index = 0; index < positions.count; index++) {
      bounds.expandByPoint(vertex.fromBufferAttribute(positions, index).applyMatrix4(mesh.matrixWorld).project(camera));
    }
  });
  return bounds;
}

export function houseHarness(t, { width = 680, height = 450, ...options } = {}) {
  let now = 1, nextTimer = 0, frame, scene, camera;
  const canvases = [], images = [], timers = new Map();
  const noop = () => {};
  const gradient = () => ({ stops: [], addColorStop(at, color) { this.stops.push([at, color]); } });
  const element = () => ({ append: noop, setAttribute: noop, hasAttribute: () => false,
    classList: { toggle: noop }, style: { setProperty: noop } });
  const globals = {
    document: {
      fonts: { load: () => new Promise(noop) },
      createElement(tag) {
        if (tag !== "canvas") return element();
        const calls = [];
        const ctx = new Proxy({
          createRadialGradient: gradient, createLinearGradient: gradient, fillRect() { calls.push(["fill", this.fillStyle]); },
          drawImage(image) { calls.push(["image", image.src]); },
          fillText(text) { calls.push(["text", text]); },
          measureText(text) { return { width: text.length * 14 }; },
        }, { get: (target, key) => target[key] ?? noop });
        const canvas = { calls, getContext: () => ctx };
        canvases.push(canvas);
        return canvas;
      },
    },
    Image: class { set src(source) { this.source = source; images.push(this); } get src() { return this.source; } },
    ResizeObserver: class { observe() {} },
    matchMedia: () => ({ matches: false }),
    devicePixelRatio: 1,
    requestAnimationFrame(callback) { frame = callback; return 1; },
    setTimeout(callback, delay) { timers.set(++nextTimer, { at: now + delay, callback }); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
    performance: { now: () => now },
  };
  for (const [key, value] of Object.entries(globals)) {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { value, configurable: true });
    t.after(() => descriptor ? Object.defineProperty(globalThis, key, descriptor) : delete globalThis[key]);
  }
  const stage = { clientWidth: width, clientHeight: height, append: noop, getBoundingClientRect: () => ({ width }) };
  const house = createHouse(stage, {
    createRenderer: () => ({
      shadowMap: {}, capabilities: { getMaxAnisotropy: () => 1 }, getPixelRatio: () => 1,
      setPixelRatio: noop, setSize: noop, render(value, view) { scene = value; camera = view; },
    }),
    ...options,
  });
  house.focus(undefined, { instant: true });
  return {
    house, images,
    get scene() { return scene; },
    get camera() { return camera; },
    canvas: width => canvases.find(canvas => canvas.width === width).calls,
    load(image) {
      Object.assign(image, { naturalWidth: 720, naturalHeight: 400 });
      image.onload();
    },
    draw(at) {
      now = at;
      for (const [id, timer] of timers) {
        if (timer.at > now) continue;
        timers.delete(id);
        timer.callback();
      }
      const next = frame;
      frame = undefined;
      next?.(at);
    },
    markers(values, { guests, person, planned = false } = {}) {
      const nodes = Object.entries(values).map(([device, reading]) => ({
        ...element(), dataset: { device, values: JSON.stringify(reading), ...person?.[device] },
        hasAttribute: name => planned && name === "data-planned",
      }));
      house.setMarkers({
        querySelectorAll: () => nodes,
        querySelector: () => ({ ...element(), dataset: { ...guests } }),
      });
    },
  };
}
