export function createOrderShare(context, ui) {
  const { state, REPLAY, notice, exchange, defaultPath } = context;

  const SAMPLE_EPISODES = { birthday: "ep_9031", groceries: "ep_9150" };

  // These are sample inputs for the share action. Judgment always comes back from the Server.
  const SAMPLE_ORDERS = {
    birthday: ["설향 딸기 500g (냉장) × 2", "OO 컵케이크 믹스", "동물성 휘핑크림 500ml × 1",
      "OO 액체 세탁세제 3L × 1", "OO 베이비 로션 300ml × 1", "파티 풍선 세트 × 1",
      "디즈니 공주 케이크 토퍼 × 1", "파티 고깔모자 × 6", "아이싱 펜 × 1"],
    groceries: ["우유 1L × 1", "계란 10구 × 1", "바지락 400g × 1", "딸기 500g × 1", "두루마리 휴지 × 1", "주방 세제 × 1"],
  };

  function sampleOrder() {
    const canvas = document.createElement("canvas");
    canvas.width = 650;
    canvas.height = 880;
    const ctx = canvas.getContext("2d");
    const tokens = getComputedStyle(document.documentElement);
    ctx.fillStyle = tokens.getPropertyValue("--surface").trim();
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = tokens.getPropertyValue("--ink").trim();
    ctx.font = '700 46px "Apple SD Gothic Neo", sans-serif';
    ctx.fillText("주문 상세", 32, 65);
    ctx.fillStyle = tokens.getPropertyValue("--muted").trim();
    ctx.font = '500 26px "Apple SD Gothic Neo", sans-serif';
    ctx.fillText("예시 주문", 33, 111);
    ctx.font = '600 29px "Apple SD Gothic Neo", sans-serif';
    SAMPLE_ORDERS[state.order].forEach((item, index) => {
      const y = 150 + index * 75;
      ctx.fillStyle = tokens.getPropertyValue("--green-soft").trim();
      ctx.fillRect(32, y, 46, 46);
      ctx.fillStyle = tokens.getPropertyValue("--ink").trim();
      ctx.fillText(item, 97, y + 32);
      ctx.fillStyle = tokens.getPropertyValue("--soft").trim();
      ctx.fillRect(32, y + 59, 586, 2);
    });
    return canvas;
  }

  async function shareSample() {
    if (state.sharing || REPLAY || !state.config.server) return false;
    state.sharing = true;
    ui.presenter.renderControls();
    try {
      const blob = await new Promise((resolve) => sampleOrder().toBlob(resolve, "image/png"));
      if (!blob) throw new Error("No sample image");
      return await share(blob, state.order);
    } catch {
      notice("예시 주문 화면을 만들지 못했어요.");
      return false;
    } finally {
      state.sharing = false;
      ui.reasoning.renderReason();
    }
  }

  async function share(file, sample) {
    const demoPath = draftPath();
    const form = new FormData();
    form.append("images", file, "sample-order.png");
    if (sample && state.config.fixture) form.append("sample", sample);
    try {
      await ui.surface.checkHouseBeforeShare();
      notice("주문을 보내는 중이에요.");
      const sharedAt = ui.recording.stamp();
      const result = await exchange("/demo/api/order", { method: "POST", body: form, signal: AbortSignal.timeout(35000) });
      if (!result.ok || !result.body?.episode_id) throw new Error(result.status);
      const accepted = result.body;
      state.sharedEpisode = accepted.episode_id;
      ui.episode.followOrder(accepted.episode_id, { data: { ...accepted, sample, images: 1 }, at: sharedAt, demoPath });
      notice();
      return true;
    } catch (error) {
      notice(`주문을 보내지 못했어요. (${error.message})`);
      return false;
    }
  }

  function chooseOrder(order) {
    if (state.sharing || REPLAY) return;
    state.order = order;
    state.draft = Boolean(state.episodeId);
    if (state.draft) state.auto = null;
    ui.reasoning.renderReason();
  }

  function draftPath() {
    return state.draftPath ?? (state.config.fixture ? defaultPath(SAMPLE_EPISODES[state.order]) : "house");
  }

  return { shareSample, chooseOrder, draftPath };
}
