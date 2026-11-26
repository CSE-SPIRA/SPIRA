import { previewGallery } from "./gallery.js";

const gallery = document.getElementById("artwork-gallery");
gallery.innerHTML = previewGallery();

try {
  const [{ createFridgePanel }] = await Promise.all([
    import("/sim/assets/house/house.js").catch(() => import("/demo/replay-house/house.js")),
    document.fonts.load('500 36px "IBM Plex Sans KR"'),
    document.fonts.load('600 34px "IBM Plex Sans KR"'),
  ]);
  for (const canvas of gallery.querySelectorAll("canvas")) {
    const ctx = canvas.getContext("2d");
    const panel = createFridgePanel(draw => draw(ctx, canvas.width, canvas.height), () => {});
    panel.show(canvas.dataset.notice, canvas.dataset.art);
  }
} catch {
  const message = document.createElement("p");
  message.textContent = "시뮬레이터 화면을 불러오면 냉장고 안내를 볼 수 있어요.";
  gallery.querySelector(".fridge").before(message);
}
