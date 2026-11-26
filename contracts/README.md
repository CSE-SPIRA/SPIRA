# Contracts

Values every part must agree on: APIs, JSON shapes, enum values, ID and time rules, example payloads. **This folder is the single source of truth between parts.** If a part keeps its own schema and it differs, this folder wins.

Version `0.1.0` (also in `enums.json`). Source: the Notion page *SPIRA integration contract*, agreed items only; IDs such as `HUB-07` in comments point to its items.

## Read in this order

1. [`rules.md`](rules.md): IDs, time, versions, polling, idempotency, demo mode
2. [`openapi/hub.yaml`](openapi/hub.yaml) or [`openapi/app.yaml`](openapi/app.yaml): the API of your part
3. [`schemas/`](schemas): the body shapes the API refers to (`common.json` first)
4. [`enums.json`](enums.json) and [`state-mapping.md`](state-mapping.md)
5. [`fixtures/ep_9031/timeline.md`](fixtures/ep_9031/timeline.md): one full scenario with every payload

## Folders

| Path | What |
| --- | --- |
| `openapi/` | `app.yaml` (app ↔ server), `hub.yaml` (hub ↔ server), `demo.yaml` (demo shell ↔ server, `DEMO_MODE=1` only). The server never calls the hub |
| `schemas/` | JSON Schema 2020-12, one file per body. `common.json` holds IDs, time formats and enums |
| `enums.json` | Every closed set of string values and where it is used |
| `rules.md` · `state-mapping.md` | Common rules · how card line states are derived (C-7) |
| `kb/` | Knowledge-base lists copied from SPIRA_KB `config/lists/` (owner: KB): intents, calendar tags, household types, intent id map |
| `fixtures/` | Example payloads per scenario + `manifest.json` (file → schema) |
| `codegen/` | `generate.sh` makes the models in `generated/` |
| `generated/` | Data models from the schemas: Python (server, hub) and Dart (app). Do not edit |
| `check/` | `check.py` (run by CI) and `bad/` (cases that must fail) |

Not here: connection URLs and keys (environment variables only), the embedding function (install the SPIRA_KB package, KB-16: `pip install "spira-kb[embed] @ git+https://github.com/CSE-SPIRA/SPIRA_KB@<kb version>"`), anything internal to one part.

## Use

```bash
pip install -r contracts/check/requirements.txt
python contracts/check/check.py              # contracts OK
pip install -e contracts/generated/python    # from spira_contracts.plan import Plan
```

In tests, `spira_contracts.validate.validate(payload, "plan.json")` checks the rules the models cannot express (e.g. `payload.by` required for device events).

## Changing a contract

1. Update the Notion integration contract first (agree with the affected owner).
2. On a branch `contracts/<topic>`, change `schemas/` / `enums.json` / `openapi/` / `rules.md`, update or add fixtures, then run `bash contracts/codegen/generate.sh` and `python contracts/check/check.py`.
3. Open a PR that changes `contracts/` only. Every affected owner reviews (CODEOWNERS). CI must pass.
4. Version: patch for wording, minor for an added optional field or value, major for anything that breaks an existing sender or reader. Bump `enums.json` `version` and this file.

Adding a device type needs no change here (`device_type` is an open list). Adding a trigger kind does (HUB-02): `enums.json` `trigger_event`, `schemas/plan.json`, `rules.md`, then the server spec.
