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

From the repository root, run `scripts/demo-up` with `uv` and Mosquitto installed. Open the first printed URL (default `http://127.0.0.1:8729/`) for the App, Viewer, operator, Hub, and guided replay. Stop with Ctrl-C and relaunch for a fresh run.

- Flutter builds the App preview on the first run. Later runs reuse the cached build for the same sources and Dart defines. If Flutter and a matching build are both unavailable, the rest of the demo still starts.
- `--export-app DIR` copies the App build and exits. On another machine, run `scripts/demo-up --app-web DIR` to serve that build. Use a build made with the same Dart defines, including the same `--proxy-port` (default 8731).
- `--no-app` skips the App preview. Use it when starting a stack for [Flutter hot reload](app/README.md#run-in-the-browser). `--no-shell` hides the optional example staging.
- The local operator opens without a password. To use the operator from another device on a trusted network, add `--sim-lan-ip <demo-host-LAN-IPv4>` and use the URL and password printed in the terminal.

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
