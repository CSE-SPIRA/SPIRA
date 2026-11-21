# 🏠 SPIRA

**Your order arrives. Your home is already prepared.**

> 26-2 Hanyang University · Software Engineering & AI and Applications Project

SPIRA reads an order screenshot, finds similar cases in a synthetic purchase-intent knowledge base, judges the purpose of the order, and prepares the home with appliances and IoT devices without asking.

## Repository map

| Folder | What | Owner |
| --- | --- | --- |
| [`app/`](app) | Flutter app: share orders, preparation card, stop / switch off | Yejoon Kim |
| [`server/`](server) | SPIRA Server: extract → retrieve → judge intent → tasks → plan (S1–S7) | Seojin Lee |
| [`hub/`](hub) | Home Hub: pull plan, triggers, execute, read back, restore | Yejoon Kim |
| [`simulator/`](simulator) | Virtual household (MQTT) + 3D viewer | Yejoon Kim |
| [`contracts/`](contracts) | Values shared between parts: API, schemas, enums, fixtures | Shared |
| [`design/`](design) | Shared design tokens, vocabulary, writing rules and fonts | Shared |
| [`docs/`](docs) | [Architecture](docs/architecture.md) · [Paper (LaTeX)](docs/paper) | Shared · Jeewon Lee |
| [SPIRA_KB](https://github.com/CSE-SPIRA/SPIRA_KB) | Synthetic purchase-intent knowledge base (separate repository) | Uijin Lee |

## Where to start

1. Read [`contracts/README.md`](contracts/README.md) — the values every part agrees on.
2. Read the `README.md` and `spec.md` in your part folder.
3. Follow [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) for branches and pull requests.

## Run the demo

Start the fixture stack with `scripts/demo-up --no-shell`. Follow the [Android setup](app/README.md#run-the-live-demo-on-android) to connect SPIRA to the printed fixture URL.

To open the household event controls from another device, add `--sim-lan-ip <demo-host-LAN-IPv4>` when starting the demo on a trusted network shared by both devices. For a USB-connected Android phone, you can also forward the Simulator port with `adb reverse tcp:<sim-port> tcp:<sim-port>` and use the printed loopback URL.

1. Put [`app/assets/example-order.png`](app/assets/example-order.png) or any order screenshot on the phone.
2. Share the screenshot to SPIRA from Android’s share menu.
3. Open the printed **집에서 일어나는 일** URL on a second phone or laptop and sign in with the login shown beside it. Press **택배 들이기** and **손님 도착** when the story calls for them.
4. Watch the Simulator’s `/sim/viewer` and the Hub dashboard at the printed URLs.

Run `scripts/demo-up` to also start the [optional demo shell](demo-shell/README.md), or use [`app/scripts/browser-demo`](app/scripts/browser-demo) for the Flutter App preview.

## Paper

Build from `docs/paper` with [Tectonic](https://tectonic-typesetting.github.io):

```bash
cd docs/paper
tectonic -X compile main.tex
```

## Team

| Name | Part |
| --- | --- |
| Jeewon Lee | Paper integration, deployment |
| Uijin Lee | Knowledge base |
| Seojin Lee | Server, integration contracts, evaluation |
| Yejoon Kim | App, Home Hub, Simulator |
