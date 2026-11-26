import { renderFridge } from "./fridge.js";
import { renderTv } from "./tv.js";

export const svgUrl = svg => `data:image/svg+xml,${encodeURIComponent(svg)}`;

export function withSceneArtwork(scene, values) {
  if (!values) return scene;
  const artwork = {};
  const tv = values.tv && renderTv(values.tv);
  if (tv) artwork.tv = svgUrl(tv);
  if (values.fridge_panel?.template === "fridge_panel") {
    artwork.fridge_panel = svgUrl(renderFridge(values.fridge_panel));
  }
  return Object.keys(artwork).length ? { ...scene, artwork } : scene;
}
