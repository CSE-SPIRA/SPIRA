# SPIRA Server Specification

Implementation spec for `server/`. A coding agent should be able to build the server from this repository alone: this file, `contracts/`, `server/config/` and `server/spira_server/prompts/`.

- **Language.** Everything here is English, except the LLM prompt files in `spira_server/prompts/` and Korean display text (room names, card sentences, care notices). Prompts stay Korean because every LLM input (product names, intent names, calendar tags, KB cases) is Korean and the prompts were tuned in Korean. Each prompt is summarised in English in its section.
- **Sources.** Notion *Server technical spec (Seojin)* S1–S7 and appendix B, and the *SPIRA integration contract*. IDs such as `HUB-07` or `KB-16` in parentheses only mark where a rule came from; everything needed is written here or in `contracts/`.
- **Pseudocode** below is a plan, not code. Names of modules and functions are recommendations; the API, JSON, DB columns and behaviour are binding.
- **Example scenario.** Every example continues one scenario, `ep_9031` (order on Thu 2026-10-15 21:00, kid's birthday party Sat 2026-10-17 14:00–17:00). SPIRA is not birthday-specific: intents come from 30 KB labels, items are read from screenshots, devices come from the hub's list. See `contracts/fixtures/` for this and two other scenarios.

## Contents

0. [Overview and scope](#0-overview-and-scope)
1. [Glossary](#1-glossary)
2. [Architecture](#2-architecture)
3. [Runtime](#3-runtime)
4. [Config files](#4-config-files)
5. [Data model](#5-data-model)
6. [LLM layer](#6-llm-layer)
7. [S1 Order intake and extraction](#7-s1-order-intake-and-extraction)
8. [S2 Context (RAG) and calendar tagging](#8-s2-context-rag-and-calendar-tagging)
9. [S3 Intent judgement](#9-s3-intent-judgement)
10. [S4 Task generation](#10-s4-task-generation)
11. [S5 Plan confirmation and cards](#11-s5-plan-confirmation-and-cards)
12. [S6 APIs](#12-s6-apis)
13. [S7 Observation and this-home memory](#13-s7-observation-and-this-home-memory)
14. [Re-run rules](#14-re-run-rules)
15. [Evaluation switches and call log](#15-evaluation-switches-and-call-log)
16. [Extension points and not implemented](#16-extension-points-and-not-implemented)
17. [Acceptance tests](#17-acceptance-tests)
- [Appendix A. Coverage of the Notion spec](#appendix-a-coverage-of-the-notion-spec)
- [Appendix B. Decisions made in this spec](#appendix-b-decisions-made-in-this-spec)

---

## 0. Overview and scope

The server receives shopping screenshots (order screen, cart or product page) and runs a pipeline:

| Step | What | LLM |
| --- | --- | --- |
| S1 | Read items from screenshots, label and mask them, group captures into one order | 1 call |
| S2 | Attach context: order time, this home (household types, unusual items, calendar), similar KB cases (RAG) | none (calendar tagging is a separate call when a calendar arrives) |
| S3 | Judge intent bundles and situation | 1 call |
| S4 | Find the time, generate tasks for the home's devices | 1 call (or none) |
| S5 | Safety checks, merge, confirm the plan, make cards | none |
| S6 | App and hub APIs (the hub pulls plans) | none |
| S7 | Observe what happened, judge the intent, write this-home memory | none |

**The server does not** execute device commands, wait for triggers, restore devices, run the simulator, send push notifications, create KB cases, or deploy. Those belong to the hub, app, KB and deployment (HUB-01, APP-14, KB-01).

### Scope rule: the home moves at two moments only

| Moment | Tasks | Condition |
| --- | --- | --- |
| ① The intent's time | Situation preparation: cleaning, child-safety mode, mood screen/light/music, actions at guest arrival or event end, and standby for the intent (e.g. oven preset) at the schedule start | There is an intent and its time was found |
| ② Package brought in | Per-item tasks that are harmless whenever the item is used: fridge care notice, styler/shoe-care standby, super-freeze, mattress deodorising | Regardless of intent (item group table, §4). With an intent, only the notice wording changes |

When an intent has no time, the server (never the LLM) looks for one: calendar → holiday calendar → this home's habit → otherwise **held** for 14 days (§10.3). Notices and per-item tasks do not wait for a time.

Most orders end with no intent and zero tasks; that is the normal result.

### LLM rule: never ask

LLM output is read by a program. A question, request for confirmation, refusal, empty answer or timeout counts as a format error: retry once, then use the step's default (S1 `read_failed` · calendar tags empty · S3 no intent · S4 no situation tasks). The service never asks the user back either (order edit and the held-card notice are the only "corrections").

---

## 1. Glossary

| Term | Meaning |
| --- | --- |
| Household (`h_…`) | One home. Has household types, devices (from the hub), calendar events, pause state |
| Capture | One shared screenshot request (`POST /v1/orders`, 1–3 images) |
| Episode (`ep_…`) | One order group: every capture shared within 8 h of the first capture. Also the plan id |
| Item | One ordered product line: `name` (as shown), `type` (plain name, e.g. 딸기), `group` (one of 18 product groups), `label` (care / clue), `qty`, `attributes` |
| Masked item | A sensitive item; only group and qty are stored, never name/type |
| Label `care` (관리) / `clue` (단서) | care = the item alone may create a per-item task; clue = only meaningful inside an intent |
| Bundle | Items that belong to one intent. An episode has 0–2 bundles |
| Intent | One of 30 KB intent ids (`contracts/kb/intents.json`) or `unclassified`. "No intent" = zero bundles |
| Situation | `event`, `guests`, `activity`, `theme` of a bundle, each filled only with evidence (`basis`) |
| Card (`nc_…`) | The notice for one preparation = one bundle. At most 4 lines. Stop applies to one card |
| Line | One card row = one situation task. The unit the user switches off |
| Task (`t_{name}#{n}`) | One thing the home does. `source` situation or item; `way` run / standby / notice |
| `way` | `run`: device acts by itself at the trigger. `standby`: device is set up, a person starts it (ends at first use). `notice`: text on a screen |
| Trigger | When a task starts: `time` (absolute) or event `package.brought_in` / `guest_arrived` / `event_end` |
| End | When a task stops (`on` an event or at `time`, fallback `or_time` / `or_after`, `restore`) |
| Situation preparation | Tasks of a bundle that run at the intent's time (on the card) |
| Per-item task | Tasks from the item group table triggered by package arrival (not on the card) |
| Held | A situation task whose time is unknown; kept 14 days, not sent to the hub |
| Plan / plan version | All live tasks of an episode as sent to the hub (`contracts/schemas/plan.json`). Any change makes a new version |
| Observation window | Per card: from the first situation run to `event_end` (fallback schedule end + 3 h) |
| Confirmation signal | Evidence that the intent was right: a person started a standby device, or an event trigger's event happened |
| Verdict | Per card: `match` / `stopped` / `unconfirmed` |
| Task feedback | Per line at window close: `off` / `changed` / `kept` |
| This-home memory | `cases` rows with `source = this_home`, one per card |
| KB case | `cases` rows with `source = synthetic` (made by SPIRA_KB) |
| Same intent | Same `intent_id` and overlapping calendar tags (both empty also counts) |
| Action key | `(device type, cmd)`; plugs use `smart_plug:{label}` as the type. How lines are recognised across orders |

---

## 2. Architecture

### 2.1 Modules

| Path | Responsibility |
| --- | --- |
| `spira_server/main.py` | App factory: settings, DB, routers, scheduler start/stop, `/health` |
| `spira_server/settings.py` | Environment variables (§3.1), typed (`pydantic-settings`) |
| `spira_server/clock.py` | `now()` (Asia/Seoul aware). Tests replace it |
| `spira_server/config.py` | Loads `server/config/*.yaml` and applies `DEMO_MODE` overrides |
| `spira_server/db/` | SQLAlchemy engine/session for the server DB, read-only engine for the KB DB, ORM models (§5) |
| `spira_server/api/` | `app_routes.py`, `hub_routes.py`, `auth.py`, `errors.py` (error body, §12.1) |
| `spira_server/pipeline/s1_extract.py` | Receive captures, group, quiet timer, LLM read, label/mask/merge |
| `spira_server/pipeline/s2_context.py` | `build_context`, unusual items, KB search, representative cases |
| `spira_server/pipeline/s2_calendar.py` | Calendar intake and tagging |
| `spira_server/pipeline/s3_intent.py` | Message, schema, call, format check, fill windows/tags |
| `spira_server/pipeline/s4_time.py` | `find_time`, holiday calendar, habit |
| `spira_server/pipeline/s4_tasks.py` | Stop check, item tasks, reactions, LLM call, post-processing |
| `spira_server/pipeline/s5_plan.py` | Safety net, merge, fridge notices, confirm, publish, reactions, held expiry |
| `spira_server/pipeline/s5_cards.py` | Card creation, text templates, line states (C-7) |
| `spira_server/pipeline/s6_release.py` | Package-arrival linking |
| `spira_server/pipeline/s7_observe.py` | Windows, signals, verdict, task feedback |
| `spira_server/pipeline/s7_memory.py` | `case_row`, memory API data |
| `spira_server/llm/` | `client.py` (one interface, providers, mock), `prompts.py` (load files), `calls.py` (call log) |
| `spira_server/kb/` | `lists.py` (`contracts/kb/*.json`), `embedding.py` (wraps `spira.embedding`), `search.py`, `household.py` (combination rules) |
| `spira_server/scheduler.py` | APScheduler jobs (§2.3) |
| `spira_server/prompts/*.txt` | Prompt originals (Korean) |
| `server/config/*.yaml` | Tables and numbers (§4) |
| `server/migrations/` | Alembic (§5.3) |
| `server/tests/` | pytest (§17) |

Request and response bodies use the generated models in `contracts/generated/python/spira_contracts` (install with `pip install -e ../contracts/generated/python`). Do not redefine them. Every inbound body is also checked with `spira_contracts.validate.validate(...)` for rules the models cannot express; a failure returns 422 (§12.1).

### 2.2 Flow

```
App ──POST /v1/orders──▶ S1 receive (202) ── quiet 10 min ──▶ S1 read ─▶ S2 ─▶ S3 ─▶ S4 ─▶ S5 ─▶ plan version + card
App ──PUT calendar────▶ S2 calendar tagging ─▶ re-run held / not-started episodes (§14)
App ◀─GET cards (30 s)─ S5 cards          App ──reactions──▶ S5 ─▶ new plan version
Hub ──GET plans (15 s)─ S6 pull            Hub ──ack / events / executions──▶ S6 ─▶ S5 line states, S7 windows
S7 window closes ─▶ verdict + task feedback ─▶ cases (this_home) ─▶ used by the next S4
```

Pipeline steps run in background tasks (FastAPI `BackgroundTasks` or the scheduler); API calls return immediately. Locking and transactions: §2.4.

### 2.3 Scheduled jobs (APScheduler, in-process)

| Job | When | What |
| --- | --- | --- |
| `quiet_timer` | per episode, at `episodes.quiet_due` | S1 read + S2–S5 (§7) |
| `close_windows` | every 10 min | Open / close observation windows, write pending memory rows (§13) |
| `end_tasks` | every 10 min | End tasks by their end rule and expiry (§11.8) |
| `expire_held` | daily 04:10 | Drop held tasks older than `hold_d` (§11.6) |
| `purge` | daily 04:00 | Delete device-state events older than 14 days, temp images older than 1 day |
| `close_episodes` | every 10 min | Close finished episodes (§11.8) |

Every job takes the locks of §2.4 and is safe to run twice. On start: re-schedule `quiet_timer` for every episode with unread images (any status) at `max(quiet_due, now)`; resume every episode whose `stage` is not `done` from its last committed stage (§2.4).

### 2.4 Transactions and locks

- **Lock order.** Anything that decides for the whole household (grouping a capture, package linking, pause, calendar replace, S5 confirm and publish, reactions) first takes `SELECT … FROM households WHERE id = … FOR UPDATE`, then the episode rows it touches in `id` order. Never the other way round.
- **One transaction per input.** An event, an execution result, an ack, a reaction or a capture is stored **together with every effect** (task status, line states, new plan version, `care_notices_shown`, window changes) in one transaction. Duplicates are found by the unique key (`event_id`, `result_id`, (`household_id`, `source_id`)) with `INSERT … ON CONFLICT DO NOTHING`; a conflict means the whole input was already applied, so nothing else runs. A crash before commit leaves nothing, and the resend is processed normally.
- **Long steps.** LLM and KB calls never run inside a transaction. A pipeline run reads its inputs, calls outside any lock, then commits each stage's result and `episodes.stage` (`s1` items stored → `s2` context stored → `s5` plan published → `done`). A stage is re-run from its stored inputs after a crash. Every stage also records, in the transaction that stores its result, the wall time it ended in `episodes.stage_times` (`received`, `s1_start`, `s1`, `s2`, `s3`, `s4`, `s5`; ISO with milliseconds; wall time, not the server clock, because the demo clock may move during a run; a re-run overwrites the keys it passes). S4 stores what it produced in `episodes.s4` when it ends, before S5 (display and replay only; S5 confirms from the drafts in memory as before). S5 re-reads the household state under the lock before confirming, so a result computed on stale state is merged, never blindly written.
- **Hub and app replies** are built from the committed state.

---

## 3. Runtime

### 3.1 Environment variables

Set in `server/.env` (never committed; template `server/.env.example`). No URL or key appears anywhere in git (COM-07).

| Name | Required | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | yes | Server DB (`postgresql://…`). Local default in `.env.example` |
| `KB_DATABASE_URL` | if `KB_MODE=on` | KB DB, read-only account (`kb_reader`). In deployment it may equal `DATABASE_URL` (KB-13, DEP-05) |
| `KB_MIGRATION_URL` | migrations only | KB DB owner account, used by `alembic -x db=kb` (Seojin only, never deployed) |
| `KB_VERSION` | if `KB_MODE=on` | e.g. `kb-v1`. Search cases with version number ≤ this (§8.4) |
| `LLM_PROVIDER` | yes | `anthropic` / `openai` / `gemini` / `mock` |
| `LLM_MODEL` | yes | Exact model name with version |
| `LLM_API_KEY` | unless mock | Provider key |
| `LLM_TIMEOUT_S` | no | Default `60` |
| `EMBED_MODE` | no | `bge` (default): BGE-M3 via `spira.embedding` / `mock`: deterministic fake 1024-d vectors, no model download (tests and mock runs only, §17) |
| `APP_DEMO_TOKEN` | yes | Bearer token the app uses (APP-08) |
| `KB_MODE` | no | `on` (default) / `off` (§15) |
| `HOME_CONTEXT` | no | `on` (default) / `off` (§15) |
| `KB_SAMPLE` | no | `1.0` (default); fraction of KB cases searched (§15) |
| `OTHER_HOME` | no | `off` (only value; extension 1) |
| `DEMO_MODE` | no | `0` (default) / `1`: shortened starting values (§4, `contracts/rules.md`) |
| `IMAGE_DIR` | no | Temp screenshot folder, default `/tmp/spira-images` (deployment may use S3 with a 1-day lifecycle, DEP-06) |
| `CALENDAR_HMAC_KEY` | yes | Secret for calendar change fingerprints (§8.5); any random 32+ bytes |
| `TZ` | no | `Asia/Seoul` |

### 3.2 Dependencies (`server/pyproject.toml`)

Runtime: `fastapi`, `uvicorn[standard]`, `python-multipart`, `pydantic>=2.7`, `pydantic-settings`, `sqlalchemy>=2`, `alembic`, `psycopg[binary]>=3.2`, `pgvector`, `apscheduler>=3.10,<4`, `pyyaml`, `jsonschema`, `referencing`, `anthropic>=2.12`, `openai`, `google-genai`, `spira-contracts` (local path). Extra `embed`: `spira-kb[embed] @ git+https://github.com/CSE-SPIRA/SPIRA_KB@<KB_VERSION tag>` (KB-16; embedding only, pulls the BGE-M3 runtime, ~2 GB); installed by the Docker image and for real runs, not needed with `EMBED_MODE=mock`. Dev: `pytest`, `httpx`, `ruff`.

Python 3.12 (`spira-kb` requires `<3.13`).

### 3.3 Commands

The image needs `contracts/` too, so the Docker build context is the repository root.

```bash
cd server
cp .env.example .env                       # fill in locally
docker compose up --build                  # api :8000, postgres+pgvector :5432
docker compose exec api alembic upgrade head
curl localhost:8000/health

# without Docker (Python 3.12)
python -m venv .venv && source .venv/bin/activate
pip install -e ../contracts/generated/python -e ".[dev]"          # add ,embed for EMBED_MODE=bge
alembic upgrade head
uvicorn spira_server.main:app --reload
pytest
```

`docker-compose.yml`: `api.build` is `{context: .., dockerfile: server/Dockerfile}`; the Dockerfile copies `contracts/kb`, `contracts/generated/python` and `server/`. The BGE-M3 model (~2 GB) downloads on first start; mount a cache volume at `/root/.cache/huggingface`. `/health` returns 503 until the DB and the embedding model are ready.

---

## 4. Config files

Tables and starting values live in `server/config/*.yaml`, not in code (so new items, devices or numbers need no code change). `config.py` loads them at start; `DEMO_MODE=1` replaces values listed under `demo:`.

| File | Contents | Used by |
| --- | --- | --- |
| `numbers.yaml` | Every numeric starting value below, with `demo:` overrides | all |
| `label_table.yaml` | 18 product groups → label `care` / `clue`, and the two attribute rules | S1 |
| `sensitive_words.yaml` | Words checked against the raw product name (safety net for masking) | S1 |
| `item_tasks.yaml` | Per-item tasks: which items create which device task, and their end rule | S4, S7 |
| `holiday_calendar.yaml` | Dated holidays by calendar tag + default time window | S4 |
| `device_names.yaml` | Device type → Korean display name for prompts | S4 |
| `card_templates.yaml` | Card sentences with fallbacks | S5 |
| `material_courses.yaml` | Clothing material → styler course | S4 |
| `command_policy.yaml` | Commands the server allows per `way` (safety, §11.1) | S5 |

### 4.1 `numbers.yaml`

| Key | Value | DEMO | Meaning |
| --- | --- | --- | --- |
| `group_window_h` | 8 | 0 | Captures within this many hours of the first capture form one episode (DEMO: every share is its own episode, so a rehearsal never lands in an earlier, judged one; send the captures of one order in one request, ≤ `images_per_request`) |
| `quiet_s` | 600 | 0 | Judge after this many seconds without a new capture (DEMO: right away) |
| `max_images_per_call` | 10 | 10 | S1 images per LLM call |
| `image_max_mb` / `images_per_request` | 5 / 3 | | Request limits |
| `calendar_window_d` | 14 | 14 | Calendar events used, from `shared_at` |
| `max_events` | 5 | 5 | Calendar events given to S3 |
| `min_orders` | 10 | 10 | Below this, unusual items are not computed |
| `history_d` | 90 | 90 | Unusual-item history |
| `routine_min` | 3 | 3 | Bought this often in 90 days = usual |
| `spike` | 2.0 | 2.0 | Quantity ≥ this × median = spike |
| `type_sim` | 0.85 | 0.85 | Item type names this similar count as the same |
| `sim_floor` | 0.70 | 0.70 | KB case counts as similar above this (tuned; R48: about a third of an 8-item basket shared) |
| `min_similar` | 5 | 5 | Fewer similar cases → KB not given (tuned) |
| `w_cal` / `w_house` | 0.05 / 0.03 | | Context bonus (tuned) |
| `search_limit` | 200 | 200 | KB candidates (`hnsw.ef_search` ≥ this) |
| `max_use` | 50 | 50 | Cases counted |
| `search_record_top` | 10 | 10 | Searched cases kept with their similarity for display (`context.kb_search`, §8.3 step 9) |
| `cover` / `none_min` / `max_reps` | 0.8 / 0.10 / 3 | | Representative cases |
| `base_refresh_min` | 60 | | KB base rates (cases per intent) are counted again after this (R48) |
| `max_bundles` | 2 | 2 | Bundles kept |
| `max_lines` | 4 | 4 | Lines per intent |
| `hold_d` | 14 | 14 | Held tasks kept |
| `line_off_d` | 180 | 180 | Switched-off actions left out |
| `habit_min` | 2 | 2 | `match` runs in the same slot → habit time |
| `habit_slot_h` | 1 | 1 | Same slot = same weekday, start within ± this |
| `before_start_default_min` | 90 | 3 | Cleaning lead time in examples. With `DEMO_MODE=1` every `before_start` minutes from S4 is replaced by this demo value (§10.4) |
| `guest_window_before_min` | 30 | 1 | Guest-arrival window opens this long before the schedule |
| `end_fallback_min` | 180 | 10 | `or_time` = schedule end + this |
| `after_event_end_min` | 60 | 5 | A task triggered by `event_end` ends this long after it starts (§10.4) |
| `notice_after_door_min` | 120 | 2 | Fridge notice ends this long after the first door opening |
| `notice_max_min` | 720 | 720 | … or this long after arrival |
| `standby_max_min` | 1440 | 60 | A standby task triggered by the package ends unused after this long (§11.8) |
| `late_grace_min` | 10 | 1 | A trigger time already this far in the past when published → task dropped `late` (§11.1) |
| `ack_timeout_min` | 30 | 2 | No ack of a version this long after publish → its new lines `failed` (§12.2) |
| `notice_repeat_max` / `notices_per_screen` | 2 / 3 | | Fridge notices |
| `quiet_hours` | `[22, 8]` | | Noisy devices are not run between these hours |
| `llm_timeout_s` | 60 | 60 | Every LLM call |
| `device_event_keep_d` | 14 | 14 | Device-state events kept |

Every duration is an integer in the unit its key names (`_s`, `_min`, `_h`, `_d`), so demo values are exact (`contracts/rules.md` demo table).

### 4.2 `label_table.yaml`

```yaml
# product group -> label. care: may create a per-item task. clue: only inside an intent.
groups:
  음·식료품: care
  농축수산물: care
  의복: care
  신발: care
  가구: clue            # mattress only -> care (rule below)
  화장품: clue          # storage 냉장 -> care (rule below)
  생활용품 – 침구·패브릭: clue
  생활용품 – 주방용품: clue
  애완용품: clue
  가전·전자: clue
  아동·유아용품: clue
  패션용품·액세서리, 가방: clue
  생활용품 – 세제·청소용품: clue
  생활용품 – 휴지·위생, 파티용품: clue
  스포츠·레저용품: clue
  서적, 사무·문구: clue
  컴퓨터 및 주변기기, 통신기기: clue
  자동차 및 자동차용품: clue
attribute_rules:
  - {group: 가구, type_contains: 매트리스, label: care}
  - {group: 화장품, attribute: {key: 보관, value: 냉장}, label: care}
default: clue           # group null or unknown
```

### 4.3 `item_tasks.yaml`

```yaml
# Per-item tasks. Trigger is always package.brought_in (released by the server, HUB-12).
# A task is made only if the hub list has exactly one device of `device_type` with `cmd` delegated
# (and in `room` when set). None or several -> no task (skip ambiguous targets).
# `name` is the task id name (t_{name}#n). Durations: hours as numbers, or keys of numbers.yaml.
tasks:
  - name: fridge                 # care notice on the fridge screen
    when:
      any:
        - {groups: [음·식료품, 농축수산물]}
        - {group: 화장품, attribute: {key: 보관, value: 냉장}}
    device_type: fridge
    cmd: show_notice
    value: llm_notice            # text from the S4 LLM (fridge_notices); no text -> no task
    way: notice
    end: {on: fridge.door_opened, after: notice_after_door_min, or_after: notice_max_min, restore: false}
  - name: freeze                 # super-freeze for bulk meat / frozen food
    when:
      groups: [음·식료품, 농축수산물]
      type_words: [소고기, 돼지고기, 닭, 목살, 삼겹살, 갈비, 생선, 냉동]
      bulk: true
    device_type: fridge
    cmd: super_freeze
    way: run
    end: {on: fridge.super_freeze_done, or_after: 24, restore: false}
  - name: styler                 # styler course standby for clothes
    when: {group: 의복}
    device_type: styler
    cmd: set_course_standby
    value: {course: from_material}   # material_courses.yaml, else the device default
    way: standby
    end: {on: styler.started, by: user, restore: false}
  - name: shoes                  # shoe-care standby
    when: {group: 신발}
    device_type: shoe_care
    cmd: set_course_standby
    way: standby
    end: {on: shoe_care.started, by: user, restore: false}
  - name: mattress               # bedroom purifier deodorising for a new mattress
    when: {group: 가구, type_contains: 매트리스}
    device_type: purifier
    room: 침실                    # exactly one purifier in a room named 침실
    cmd: mode
    value: {mode: deodorize}
    way: run
    end: {on: purifier.odor_normal, or_after: 72, restore: true}
bulk: {min_qty: 3, or_name_kg_at_least: 1}   # "대량"
```

A per-item task is created only when the hub list has a device of that `device_type` with that `cmd` delegated (and, if `value` has parameters, they fit its `value_schema`; otherwise the device default). `fridge`, `styler`, `shoe_care`, `purifier` and their commands beyond `show_notice` are not in the fixtures; they are used only when a hub registers them (device types are an open list, HUB-06).

### 4.4 `holiday_calendar.yaml`

Only tags with dates fixed for everyone. Birthdays and anniversaries are personal and come only from the calendar or habit.

```yaml
# tag: main days (YYYY-MM-DD, the holiday itself; Korean dates from the 2027 calendar notice) and a default window
설날:      {days: [2027-02-07], window: ["10:00", "14:00"]}
추석:      {days: [2026-09-25, 2027-09-15], window: ["10:00", "14:00"]}
크리스마스: {days: [2026-12-25, 2027-12-25], window: ["18:00", "21:00"]}
어린이날:  {days: [2027-05-05], window: ["11:00", "15:00"]}
어버이날:  {days: [2027-05-08], window: ["18:00", "20:00"]}
```

A holiday matches a bundle when the tag is one of the intent's `related_tags` (`contracts/kb/intents.json`); the first day whose window **starts after `now`** and within 14 days of `shared_at` wins (dates in Asia/Seoul). Extend the list each year.

### 4.5 Other files

- `sensitive_words.yaml`: `words` (starting list `[의약품, 상비약, 감기약, 소화제, 진통제, 연고, 수면유도, 피임, 콘돔, 윤활, 임신테스트, 배란, 혈당, 성인용 기저귀, 요실금, 탈모, 보청기, 성인용품, 다이어트 약]`) and `exempt` (`[치약, 약산성, 약알칼리, 약콩]`). Match = case-insensitive substring of the raw product name after removing every `exempt` word. No single-syllable words. Daily supplements and hygiene goods (비타민, 유산균, 휴지, 치약, 샴푸, 생리대) are never added. Test cases: 치약 → not masked, 감기약 → masked (T6).
- `command_policy.yaml`: server-side command allow list (§11.1). `run` = commands S4 may run; `standby` = preset commands (`set_*_standby`); `notice` = `show_notice`. A command in none of them is dropped `unsafe_cmd`, whatever the LLM wrote; `deny_words` (`start`, `ignite`, `heat`, `unlock`, `open`, `buy`, `order`, `pay`, `delete`, `reset`) block a command even if listed. `protective` = `{device type}.{cmd}` patterns of safety actions (`*.child_lock`, `smart_plug.off`); a task with any matching action is sent with `protective: true` (§11.3). The LLM never sets it.
- `device_names.yaml`: `cleaner: 로봇청소기, light: 조명, display: TV, cooktop: 인덕션, oven: 오븐, fridge: 냉장고, smart_plug: 스마트 플러그, purifier: 공기청정기, styler: 스타일러, shoe_care: 신발관리기`. Unknown types show the type string.
- `material_courses.yaml`: `{울: 울케어, 캐시미어: 울케어, 니트: 울케어, 면: 표준, 가죽: 표준}`; used only if the course is in the device's enum.
- `card_templates.yaml`: §11.4.

---

## 5. Data model

### 5.1 Server DB tables (PostgreSQL 16 + pgvector ≥ 0.7)

Column types are binding; extra internal columns are allowed.

| Table | Columns | Notes |
| --- | --- | --- |
| `households` | `id text pk`, `household_types text[]`, `paused bool`, `hub_key_hash text`, `created_at`, `updated_at` | Hub key stored as SHA-256 hex |
| `device_lists` | `household_id pk`, `revision int`, `body jsonb` (C-2), `updated_at` | Latest list only. The device catalog is derived from `body` |
| `calendar_events` | `household_id`, `id`, `start timestamptz`, `end timestamptz`, `tags text[]`, `tagged bool`, `fingerprint text`, `updated_at`; pk (`household_id`, `id`) | Titles are never stored. `fingerprint` = HMAC-SHA256(server secret, title + start + end), used only to detect changes |
| `calendar_revisions` | `household_id pk`, `revision int` | +1 on every calendar PUT (§8.5) |
| `episode_sources` | `household_id`, `source_id`, `episode_id`; pk (`household_id`, `source_id`) | Idempotency of `POST /v1/orders`, also while paused |
| `episodes` | `id text pk`, `household_id`, `status` (§5.2), `shared_at`, `received_at`, `source_ids text[]`, `judged bool`, `stage` (`s1`/`s2`/`s5`/`done`, last committed step, §2.4), `quiet_due null`, `plan_version int`, `context jsonb` (S2), `intent jsonb` (S3), `error jsonb`, `closed_at`, `created_at`, `updated_at`, `stage_times jsonb` (§2.4, migration 0003), `s4 jsonb null` (§10, migration 0003) | Index (`household_id`, `status`), (`household_id`, `shared_at`) |
| `episode_images` | `id`, `episode_id`, `path`, `read bool`, `created_at` | Deleted after the extraction of its pass is committed (≤ 1 day) |
| `orders` | `episode_id`, `order_no text null`, `mall text null`, `eta_text text null` | eta is stored only |
| `order_items` | `episode_id`, `id text` (`it_…`, numbered inside the episode); pk (`episode_id`, `id`), `order_no null`, `name null`, `type null`, `grp null`, `label`, `qty int null`, `deal null`, `attributes jsonb`, `masked bool`, `created_at` | Masked rows: name/type/attributes null |
| `tasks` | `episode_id`, `task_id`, `card_id null`, `source`, `way`, `status` (§5.2), `need`, `line`, `actions jsonb`, `trigger jsonb`, `end jsonb`, `target_room null`, `end_after_start_minutes null`, `meta jsonb` (item, kind, point, intent_change, rule ids), `started_at null`, `ended_at null`, `drop_reason null`; pk (`episode_id`, `task_id`) | One row per task; values in contract form |
| `plans` | `episode_id`, `version int`, `body jsonb` (C-1), `devices_revision`, `created_at`, `ack jsonb null`, `acked_at null`; pk (`episode_id`, `version`) | Every published version; `plan_id` → episode → household for hub auth (§12.1) |
| `cards` | `id text pk`, `episode_id`, `bundle_index int`, `ordinal int` (1, 2, 3 … per episode, never reused), `intent_id`, `template`, `text`, `starts_at null`, `stopped bool`, `archived bool`, `notify bool`, `updated_at`, `seq bigint` | At most 2 non-archived cards per episode (§14). `seq` from a household sequence, set on every write (§12.2 cards) |
| `card_lines` | `card_id`, `task_id`, `position int`, `checked bool`, `checked_changed_at`, `state`, `end_state null`, `note null`; pk (`card_id`, `task_id`) | State per §11.5 |
| `events` | `event_id text pk`, `household_id`, `type`, `source`, `at`, `payload jsonb`, `received_at` | Device-state rows purged after 14 days |
| `executions` | `result_id text pk`, `kind`, `operation_id null`, `plan_id`, `plan_version`, `task_id`, `device null`, `cmd null`, `substrate null`, `status null`, `reason null`, `body jsonb`, `at`, `received_at` | |
| `windows` | `id text pk` (`ow_…`), `episode_id`, `card_id unique`, `start_at null`, `scheduled_start null`, `end_due null`, `end_at null`, `end_reason null`, `status` (`pending`/`open`/`closed`), `memory` (`pending`/`written`/`ineligible`), `verdict null`, `task_feedback jsonb null`, `checks jsonb` | Created with the card (§13.1) |
| `care_notices_shown` | `household_id`, `item_type`, `kind`, `count`; pk all but count | Fridge notice repetition |
| `llm_calls` | `id`, `episode_id null`, `stage` (`s1`/`cal`/`s3`/`s4`/`retype`), `provider`, `model`, `input_tokens`, `output_tokens`, `latency_ms`, `attempts`, `outcome` (`ok`/`format_fail`/`timeout`/`error`), `created_at` | §15 |
| `cases` | from migration `0001` (do not change columns) | `this_home` rows written by S7; `synthetic` rows only in the KB DB |

### 5.2 Status values

- `episodes.status`: the APP-11 values in `contracts/enums.json` (`received`, `reading`, `read_failed`, `judged`, `notified`, `held`, `closed`, `paused_skip`). Internally S2–S5 run while the status is `reading`; a failure in S2 or S3 ends as `judged` with `error` set.
- `tasks.status`: `held` (no time, not sent), `live` (in the current plan), `cancelled`, `dropped` (held expired, removed by the safety net, late, or rejected), `ended`. Drafts from S4 live in memory until S5 and are never stored (no `draft` status).
- `tasks.started_at` is set by the first execution result with status `running` or `completed` (a confirmed start). `blocked` never sets it; `failed` / `unknown` / `unverifiable` without an earlier `running` set `start_uncertain = true` in `meta` instead. Restore (§11.3), `line_on` (§11.7) and feedback (§13.4) treat a start as `started_at is not null or start_uncertain`.

### 5.3 Migrations

| Revision | What |
| --- | --- |
| `0001_create_cases` | exists; `cases` in both DBs |
| `0002_core_tables` | every table in §5.1 except `cases`, server DB only (skip when `-x db=kb`) |

---

## 6. LLM layer

### 6.1 Interface

```python
class LLM(Protocol):
    def structured(self, *, stage: str, system: str, user: str, schema: type[BaseModel],
                   images: list[bytes] = (), episode_id: str | None = None, raw: bool = False) -> BaseModel | dict: ...
```

- One implementation per provider (`anthropic`, `openai`, `gemini`) using that provider's structured-output feature with the Pydantic JSON schema: Anthropic JSON outputs (`output_config.format` json_schema, schema adapted with the SDK's `transform_schema`; forced `tool_choice` is refused by current models), OpenAI `response_format` json_schema, Gemini `response_json_schema`. Constraints a provider drops (e.g. `minimum`, `maxLength`) are still checked by the stage. **S4 is the exception** (`enforce_schema=False`): its schema grows with the household's device list and exceeded Anthropic's compiled-grammar size in dry run A, so the provider sends no constrained-output parameter, appends the JSON schema to the system prompt as text (`[답 JSON 스키마]`, OpenAI `response_format: json_object`, Gemini JSON mime type without schema), and the stage validates the answer exactly as before (§10.7, then S5). A JSON object wrapped in prose or a code fence is unwrapped (first `{` to last `}`). S1, calendar tagging and S3 keep the enforced schema. `LLM_PROVIDER` / `LLM_MODEL` choose; nothing else changes (model choice is made later by the evaluation plan).
- Default for development: `anthropic` with Claude Opus 5.5 until model selection.
- Temperature: provider default (not set).
- `raw=True` (S1 only): the schema is still sent to the provider, but the parsed JSON is returned without model validation; the stage validates parts itself (§7.3). Other stages validate the whole answer.
- `mock`: returns recorded outputs from `server/tests/llm_fixtures/{stage}/{key}.json` where `key` is a stable hash of (system, user, image hashes). Unknown key → raises (tests must record outputs explicitly).

### 6.2 Call rule (every stage)

```
for attempt in 1..2:
    try: out = provider call (timeout LLM_TIMEOUT_S)
    except timeout/API error: record; continue
    if out is a refusal / empty / not parseable / fails schema: errors = [...]
    else: errors = stage_format_check(out)
    if not errors: return out
    user += retry_text(errors)          # the stage's "format error" text, listing only the errors
return stage_default                     # never ask, never block
```

Every call writes one `llm_calls` row (tokens and latency from the provider response).

### 6.3 Prompt files

All in `spira_server/prompts/`, UTF-8, loaded once. Lists inside prompts are filled from `contracts/kb/*.json` at start (intent list, tag list) so the prompt and the KB never drift.

| File | Stage | Fills |
| --- | --- | --- |
| `s1_system.txt` | S1 system | `{GROUPS}` the 18 product groups of `label_table.yaml`, joined with " / " |
| `s1_user.txt` · `s1_user_one.txt` | S1 user (several images · one image) | `{N}` image count |
| `s1_retry.txt` | S1 retry | `{ERRORS}` one "- …" line per error |
| `cal_system.txt` | calendar tagging system | `{TAGS}` "tag · definition" lines from `contracts/kb/calendar_tags.json` + `cal_tag_definitions.yaml` |
| `cal_user.txt` | calendar tagging user | `{EVENTS}` |
| `s3_system.txt` | S3 system | `{INTENTS}` "id · name · definition" lines from `contracts/kb/intents.json` |
| `s3_blocks.yaml` | S3 user message blocks | per block (§9.3) |
| `s3_retry.txt` | S3 retry | `{ERRORS}` |
| `s4_system.txt` | S4 system | — |
| `s4_blocks.yaml` | S4 user message blocks | per block (§10.5) |
| `s4_retry.txt` | S4 retry | `{ERRORS}` |
| `retype_system.txt` | order edit: product name → type and group | `{GROUPS}` |

Placeholders are replaced with plain string replacement. Enum values inside prompts and schemas are the English codes of `contracts/enums.json` (e.g. `way` run / standby / notice, `kind` prep / storage); prompts gloss them in Korean.

The exact texts are in those files; each stage section below gives the schema, the message assembly and an English summary.

---

## 7. S1 Order intake and extraction

**Purpose.** Receive screenshots of an order screen, a cart or a product page, group captures into one episode, read items with one LLM call per quiet period, then label, mask and merge them in code.

**Inputs.** `POST /v1/orders` multipart: `household_id`, `images` (1–3, jpg/png, ≤ 5 MB each), optional `shared_at`, optional `source_id` (APP-02).
**Outputs.** `202 {episode_id, status}` at once (no notification); later `order_items` rows and the next steps.

### 7.1 Receive

1. Validate images (count, type, size). Bad → `400 invalid_image`, no episode.
2. Lock the household (§2.4). If (`household_id`, `source_id`) is in `episode_sources` → `200 {episode_id, status}` of that episode; nothing else (no LLM).
3. `shared_at = request.shared_at or now()`, then clamped to [`now − 1 d`, `now`]; `received_at = now()`. All date arithmetic is in Asia/Seoul.
4. If the household is paused → create an episode with status `paused_skip` and its `episode_sources` row; images are not stored (nothing will read them); `202`. A resend returns the same episode (step 2). Resuming does not judge paused episodes.
5. Find the household's open group: an episode not `closed` / `paused_skip` whose first capture is within `group_window_h` (8 h) of this `shared_at`; several → the newest. None → create a new episode (`ep_…`, status `received`, `shared_at` = this capture).
6. Store images in `IMAGE_DIR` (`episode_images`, `read=false`), insert `episode_sources`, append `source_id`.
7. Set `episodes.quiet_due = now + quiet_s` and (re)schedule `quiet_timer` (each capture restarts the wait). Commit, return `202`.

### 7.2 On quiet (`quiet_timer`)

1. Under the episode lock: if `quiet_due > now` (a capture arrived meanwhile) → stop; the newer timer runs. Else status → `reading`, take unread images, up to `max_images_per_call` (10); the rest run in a second pass right after. Commit.
2. LLM call `s1` (§7.3) with those images, outside any lock.
3. Post-process every returned item (§7.4) and dedupe **inside this pass** — before masking drops the name. Same item = same `name`, and the shown `qty` and the `order_no` are **each equal or missing on one side** (overlapping screenshots often show one of them only). Same name with a different `qty` is a second purchase and stays separate. When merging, a missing `qty` / `order_no` / `deal` is filled from the other copy.
4. Lock the household, then the episode (§2.4). Merge into the episode: unmasked items dedupe against stored items with the same rule (`name`, `qty`, `order_no`); masked items are never merged across passes (a masked item seen in two passes counts twice, known limit). If an `order_no` already belongs to another open episode of the household, merge into that one instead (APP-07). Store orders (order_no, mall, eta text), set `stage = s1`, mark the images read. Commit. **Then** delete the image files.
5. If the episode has no items at all (this and earlier passes) → status `read_failed`, card-less notification flag for the app (APP-14), stop.
6. If every item is masked → no S2–S5; status `judged`, `intent = {bundles: [], none_reason: "all_masked"}`; the app shows only `masked_count`.
7. Not judged yet → run S2 → S5 now (do not wait 8 h). Already judged and new items were added → re-run from S2 (§14).

### 7.3 LLM call (S1)

- Prompts: `s1_system.txt` (`{GROUPS}`), `s1_user.txt` or `s1_user_one.txt`, images attached.
- Schema:

```python
AttrKey = Literal["재질", "포장", "가공", "보관", "테마"]
Group = Literal[<18 groups from label_table.yaml>]
SensitiveKind = Literal["의약품·의약외품", "건강 상태", "성·피임", "민감한 책·콘텐츠", "신체 보정·의료"]
class Attribute(BaseModel): key: AttrKey; value: str; source: str
class Item(BaseModel):
    name: str; type: str; group: Group | None; qty: int | None = Field(None, ge=1, le=999)
    deal: str | None; order_no: str | None
    attributes: list[Attribute] = []; sensitive_kind: SensitiveKind | None
class Order(BaseModel): order_no: str | None; mall: str | None; eta: str | None
class OrderExtraction(BaseModel): items: list[Item]; orders: list[Order] = []
```

- Validation is two-step (S1 only): the provider is asked for `OrderExtraction`, but the server parses the raw JSON envelope `{items: [...], orders: [...]}` and validates `orders` and **each item on its own** with `Item`. An item that fails is dropped alone (not the whole answer). If no item survives (and the envelope was not `items: []`) → retry once with `s1_retry.txt` listing the errors (e.g. `- 물건 3의 group "파티용품"은 상품군 목록에 없다`). Still nothing → no items from this pass. `LLM.structured` therefore has a `raw=True` mode returning the parsed JSON (§6.1).
- Default (refusal / timeout twice): no items from this pass.
- **Prompt summary.** Three screens are read: order screens (ordered items, not cancelled or returned), carts (items in the cart, except unchecked, sold-out or unavailable ones; all items when no checkboxes are visible) and product pages (that one product with its chosen options). Never read recommendations, "bought together", recently viewed, ads, fees or coupons; a shop home, search results or category lists give no items even when they show products; same item across overlapping images once; `type` is a 2–3 word plain name without brand, size, flavour, colour or character, but keeps an occasion or use word from the product name (생일, 파티, 캠핑, 명절 …) so the same product always gets the same type (R50); `qty` null if not visible (never 1 by default); `deal` copied, never multiplied; attributes only from the product name/options with the exact `source` text; flag five sensitive categories, when unsure pick the closest (mask); daily supplements and hygiene goods are not sensitive.

### 7.4 Post-processing (code)

For each item:
1. `name` empty → drop the item.
2. `type` empty → `core_noun(name)`: drop tokens containing digits or units (g, kg, ml, L, 개, 매, 입, 팩), bracketed text and known brand markers; take the last remaining token.
3. Drop attributes whose `source` is not a substring of `name`.
4. `qty` counts packs as shown on the order line. `deal` "1+1" → `qty = 2 × (qty or 1)`; "2+1" → `qty = 3 × (qty or 1)`; other deals → `qty` unchanged. Result clamped to [1, 999].
5. `label` from `label_table.yaml` by `group` (null → `clue`), then the two attribute rules (mattress, refrigerated cosmetics → `care`).
6. `masked = sensitive_kind is not None or sensitive_words hit on name` (§4.5). Masked: store only `grp`, `qty`, `masked=true`; `name`, `type`, `attributes` null; the category itself is not stored.
7. Store as `order_items` with `item_id = it_{n}`.

Masked items never reach S2 embedding, S3, S4, notices, rationale or the order edit screen; they appear only as `masked_count`.

### 7.5 Failure handling

| Case | Handling |
| --- | --- |
| Bad image | 400, no episode |
| Same `source_id` again | 200 with the existing episode |
| One item fails the schema | Drop that item only |
| Zero items after retry, whole episode empty | `read_failed`, notify once |
| LLM timeout (60 s) | Retry once, then as above |
| Not an order, cart or product screen (shop home, search results, other apps) | Zero items from that image; other images still count |
| Type / group unclear | `core_noun`; group null → `clue` |
| Missing qty / order_no / eta | null, continue |

### 7.6 Example

`ep_9031`: captures at 21:00:08 and 21:01:12 → both `202 {"episode_id": "ep_9031", "status": "received"}` → 21:11 one S1 call with 2 images → 9 items (`contracts/fixtures/ep_9031/episode.json` items). 딸기 and 휘핑크림 are `care` (food), 로션 is `clue` (cosmetics without 보관 냉장), 고깔모자 qty 6. A capture at 23:30 (inside 8 h, after judging) is read alone and re-runs from S2 with no notification.

---

## 8. S2 Context (RAG) and calendar tagging

**Purpose.** Build the context S3 reads: order time, this home (household types, unusual items, calendar) and similar KB cases. Code only; the LLM is used only to tag calendar events when they arrive.

**Output.** `episodes.context = {"for_intent": {order_time, this_home, kb_neighbors}, "snapshot": [case_id, …]}`.

### 8.1 Order time

`order_time = {"shared_at": episode.shared_at, "weekday": "목"}`. Always present (all evaluation conditions). Seasons are not used.

### 8.2 This home (only if `HOME_CONTEXT=on`)

- `household_types`: as stored (may be empty).
- `unusual_items` (masked items excluded), from this household's other episodes in the last `history_d` (90) days:
  - fewer than `min_orders` (10) episodes in total → `{"status": "insufficient"}`;
  - for each current item: past items of the same type (equal string, or `embed_basket([a])`·`embed_basket([b])` cosine ≥ `type_sim` 0.85). Count episodes containing it: 0 → `"이 집이 산 적 없는 종류"`; `< routine_min` (3) → `"90일에 {n}번 산 드문 물건"`; `qty ≥ spike × median past qty` → `"평소 {m}개 → 이번 {q}개"`; otherwise usual;
  - result `{"status": "list", "items": [{item, why}], "usual": [types]}` or `{"status": "all_usual"}`.
- `calendar`: this household's tagged events with start in [`shared_at`, `shared_at + 14 d`], dropping events whose tags are all everyday tags (`contracts/kb/calendar_tags.json` `everyday: true`) or empty; nearest first; at most `max_events` (5). Each: `{id, days_after, day, tags, start "HH:MM", end "HH:MM"}` (`days_after` counted in calendar days from the shared date).

### 8.3 KB neighbours (only if `KB_MODE=on`)

1. `q = embed_basket([types of unmasked items])` (`from spira.embedding import embed_basket`; KB-16). Same function and model as the KB loader.
2. Search the KB DB (`KB_DATABASE_URL`, read-only), §8.4: up to `search_limit` (200) `synthetic` cases by cosine similarity.
3. `similar` = candidates with `sim > sim_floor` (0.70). Measured with BGE-M3 in dry run B (11-21): 8-item baskets sharing 0 · 1 · 2 · 3 · 4 · 6 items score about 0.56 · 0.59 · 0.65 · 0.70 · 0.76 · 0.87, so 0.70 ≈ a third of the items shared; 0.6 let in baskets sharing 0–1 items (R48). The level depends on the basket: in B8 (a real kid birthday cart) many cases sharing 0–1 exact names were above 0.70 because the embedding matches the same item under another name (케이크 초 ≈ 생일 초).
4. `len(similar) < min_similar` (5) → `{"similar_count": n, "note": "비슷한 사례가 거의 없음"}`.
5. Else score = sim (+ `w_cal` if any calendar tag of the case is among this order's calendar tags, + `w_house` if any household type matches — both only when `HOME_CONTEXT=on`). Sort by (score, sim, case_id) desc, keep `max_use` (50).
6. `intent_counts` = per `intent_id` among the kept cases (one row = one case): `n`, `share = n / kept`, and `base_share` = that intent's share of all searchable cases (same `source`, `KB_VERSION` and `KB_SAMPLE` filter as §8.4, `GROUP BY intent_id`; counted once per process and again after `base_refresh_min`, because the KB grows under one version while it is built). `none` always has a row (`n` 0 when absent). `base_total` = all searchable cases. Names from `contracts/kb/intents.json` (`none` → "의도 없음"). No label or threshold is added: S3 compares the two shares itself (R48).
7. Representative cases (`pick_reps`): go through intents by count desc; take the best case (score, sim, case_id) of each intent until the covered share reaches `cover` (0.8), at most `max_reps` (3); `none` is always included if its share ≥ `none_min` (0.10). Keep only `case_id, items, intent_id, intent_text, situation, calendar_tags, case_household_types`. No item overlap count: exact names miss the same item under another name (R49).
8. `snapshot` = the case ids used (for the rationale).
9. `kb_search` (next to `for_intent` and `snapshot` in `context`, **never read by S3**, display and replay only): `{searched` = candidates returned, `sim_floor`, `above_floor` = candidates with `sim > sim_floor` (not capped by `max_use`, unlike `similar_count`), `used` = cases kept, `sims` = every candidate's similarity (desc, 4 decimals), `top` = the `search_record_top` (10) most similar `{case_id, sim, score, intent_id, intent_text, items, used}}`. Not written when `KB_MODE=off`.

### 8.4 KB search query

```sql
SET LOCAL hnsw.ef_search = 200;
SET LOCAL hnsw.iterative_scan = relaxed_order;          -- pgvector >= 0.8 (Neon); skip on 0.7
SELECT case_id, items, intent_id, intent_text, situation, "when", household,
       1 - (basket_emb <=> :q) AS sim
FROM cases
WHERE source = 'synthetic'
  AND substring(kb_version from '^kb-v([0-9]+)$')::int <= :kb_version_number   -- versions are cumulative (Q1)
  AND (:sample >= 1.0 OR ('x' || substr(encode(sha256(case_id::bytea), 'hex'), 1, 8))::bit(32)::bigint
                          < :sample * 4294967296)                               -- KB_SAMPLE (§15)
ORDER BY basket_emb <=> :q
LIMIT 200;
```

On pgvector 0.7 (no iterative scan) use `LIMIT 1000` and keep the first 200 rows that pass the filters in Python. The same `sha256` rule in Python: `int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16) < sample * 2**32`.

### 8.5 Calendar intake and tagging

`PUT /v1/households/{hid}/calendar` (APP-03) carries the full list for now .. +14 days.
1. Lock the household; `calendar_revisions.revision += 1` (= `r`). Events missing from the list are deleted; for each event `fp = HMAC-SHA256(server secret, title + start + end)`; new ones or ones whose `fp` differs are to be tagged; unchanged ones keep their tags. Store `start`, `end`, `fingerprint` now (tags of changed events cleared, `tagged=false`). Commit, respond `202 {accepted: n}`.
2. One LLM call (`cal`) for all events to tag: system `cal_system.txt`, user `cal_user.txt` with lines `- {id} · {M}월 {D}일 ({요일}) {HH:MM}~{HH:MM} · {title}`.
3. Schema: `EventTags{id: Literal[ids], tags: list[Literal[30 tags]] (max 3)}`, `CalendarTagging{events: list[EventTags]}`. Missing ids → no tags.
4. Lock the household. If `calendar_revisions.revision` is still `r` → store `tags` (`tagged=true`) and run calendar re-runs (§14). Else discard the result (a newer PUT owns the calendar). **Titles are never stored**; they live only in this request's memory. The HMAC secret is a server setting (`CALENDAR_HMAC_KEY`, §3.1).
5. Default on failure: tags empty for those events (`tagged=false`); they are retried at the next calendar PUT (their `fp` is unchanged, so `tagged=false` is what marks them).

**Prompt summary.** Tag only when the title clearly says so; health events get no tag; up to 3 tags; "손님 방문" only when someone comes to this home; do not tag from the date alone; never output the title.

Example: `contracts/fixtures/ep_9031/calendar.json` → c1 `[생일]`, c2 `[가족 모임]`, c3 `[회의]`, c4 `[]` (clinic), c5 `[]`. S3 sees only c1 and c2.

### 8.6 Failure handling

| Case | Handling |
| --- | --- |
| Embedding model not loaded | `/health` 503; orders are not processed |
| KB DB timeout (search or base count) | Retry once → status `judged` with `error.stage = s2`; nothing prepared |
| No KB cases / fewer than 5 similar | `note` only (normal) |
| No calendar / types / < 10 orders | Field omitted or status line (normal) |
| Calendar tagging fails | Empty tags, title dropped, retried at next PUT |

### 8.7 Example (`ep_9031`, C2)

`contracts/fixtures/ep_9031/rationale.json` `evidence` shows the values: unusual items (케이크 토퍼 … 딸기 평소 1개 → 이번 2개), calendar c1 (2 days later, Sat 14:00–17:00, 생일) and c2, KB counts 아이 생일 파티 9 · 홈베이킹 2 · 의도 없음 1 (the S3 test message adds base shares 2 % · 3 % · 64 % of 30,000), two representative cases (9/12 = 75 % < 80 % so 홈베이킹 is added; 의도 없음 is 8 % < 10 %).

---

## 9. S3 Intent judgement

**Purpose.** One LLM call decides intent bundles and their situation; code checks only the format and fills times and tags.

**Output.** `episodes.intent`:

```json
{"bundles": [{"intent_id": "...", "intent_text": "...", "items": ["..."], "situation": {"event": null, "guests": null, "activity": null, "theme": null},
              "basis": {"intent": [], "event": [], "guests": [], "activity": [], "theme": []},
              "calendar_event_id": "c1", "calendar_tags": ["생일"], "use_window": {"start": "...", "end": "..."}}],
 "unbundled": ["..."], "none_reason": null, "error": null}
```

### 9.1 Steps

1. Build the user message (§9.3).
2. Build the schema with the current item types, calendar ids and intent ids as enums (§9.4).
3. Call `s3`; check the format (§9.5); on errors retry once with `s3_retry.txt`; still failing → no intent (`none_reason = "format_fail"`).
4. Situation fields filled without basis → set to null (no retry; logged in `error.notes`).
5. Keep the `max_bundles` (2) bundles with the most items (ties: LLM order).
6. For each bundle: `use_window` = start/end of `calendar_event_id` (null if none); `calendar_tags` = its tags (`[]` if none).
7. `unbundled` = unmasked item types in no bundle (recomputed by code).

### 9.2 Prompt summary (`s3_system.txt`)

Most orders are plain shopping; weak evidence → no intent (a wrong intent that moves the home is worse than a missed one). Evidence order: items > calendar (only to link an intent the items already show) > household types and unusual items (narrowing only). One bundle per intent, an item in one bundle only. Labels only from the list, separated by their distinguishing clues; `unclassified` only for one clear purpose not in the list; never guess health/body purposes. Situation fields only with basis (item types, calendar ids, "가구 유형"); never copy other homes' details; guests by count of one-per-person items above the household size, counting pack sizes; "모름" quantities are not used. Link a calendar event only when its occasion is the intent's occasion, even if it is the only event left (birthday items with only a "가족 모임" event → no link). Never write dates, weekdays or times. `intent_text` contains every filled field, in the same words as the field, and nothing else.

### 9.3 User message

Blocks in this order, each with its header and how-to-use text from `s3_blocks.yaml`. A block switched off is left out with its text; a block switched on but empty uses its status line.

| Block | C0 | C1 | C2 / service | Empty |
| --- | --- | --- | --- | --- |
| `[이번 주문]` | ✓ | ✓ | ✓ | — |
| `[주문 시각]` | ✓ | ✓ | ✓ | — |
| `[이 집 가구 유형]` | | | ✓ | omitted |
| `[이 집 지난 90일 주문과 비교]` | | | ✓ | insufficient / all usual line |
| `[캘린더 일정]` | | | ✓ | "14일 안에 행사 태그가 붙은 일정 없음" |
| `[비슷한 다른 집 주문]` | | ✓ (similarity only) | ✓ | "거의 없다 ({N}건)" line |

- Items: unmasked, `- {type} × {qty or 모름}` + ` [{key}: {value}, …]` for attributes 테마, 포장, 가공 only.
- Calendar: `- {id} · {days}일 뒤 {요일} {start}~{end} · {tags joined by ", "}`.
- KB: counts header `비슷한 주문 {N}건 (전체 {TOTAL}건 중):`, one line per intent `- {name} {n}건 · 이번 {share}% · 평소 {base}%` (`none` last, "1% 미만" below 0.5 %), then one example per representative case (no case id, no weekday). The how-to text reads "more than usual" as the evidence and `none` only when above its usual share (R48).

The full message for `ep_9031` (C2) is the reference output of `build_intent_message` (test `test_s3_message_ep9031`, §17); expected text in `server/tests/expected/s3_message_ep_9031.txt`.

### 9.4 Schema

```python
def build_schema(item_types, cal_ids, intent_ids):
    ItemT = Literal[tuple(item_types)]
    CalT = Literal[tuple(cal_ids)] if cal_ids else None
    BasisT = Literal[tuple(item_types + cal_ids + ["가구 유형"])]
    class Situation(BaseModel): event: str | None; guests: str | None; activity: str | None; theme: str | None
    class Basis(BaseModel):
        intent: list[BasisT] = Field(min_length=1)
        event: list[BasisT] = []; guests: list[BasisT] = []; activity: list[BasisT] = []; theme: list[BasisT] = []
    class Bundle(BaseModel):
        intent_id: Literal[tuple(intent_ids + ["unclassified"])]
        intent_text: str; items: list[ItemT] = Field(min_length=1)
        situation: Situation; basis: Basis; calendar_event_id: CalT | None = None
    class IntentDecision(BaseModel): bundles: list[Bundle]; none_reason: str | None
    return IntentDecision
```

### 9.5 Format check (retry on any of these)

- an item in two bundles;
- two bundles with the same `intent_id` (except `unclassified`);
- bundles empty and `none_reason` empty, or bundles present and `none_reason` set;
- a filled situation field that is not in `intent_text`: the whole value ignoring spaces and the list marks `,` `·` `/` is not there, and neither is its key word (the value itself, or for several words its longest word; words are split on spaces and those marks). "하츄핑, 공주, 핑크" is found in "하츄핑·공주·핑크 테마…";
- a linked calendar event whose tags share none of the intent's `related_tags` (`contracts/kb/intents.json`); checked only for intents that have related tags (not `unclassified`, not intents with an empty list) and only on the first attempt — a link still wrong after the retry is removed (`calendar_event_id` null, the time is then found by §10.3) and noted in `error.notes`, the bundle is kept;
- (schema already rejects unknown labels, items, calendar ids).

### 9.6 Failure handling

| Case | Handling |
| --- | --- |
| Format error twice / timeout / API error | No intent; `error` recorded; S4 makes per-item tasks only |
| Field without basis | Field → null, no retry |
| 3+ bundles | Two with most items |
| `unclassified` | Accepted; no same-intent memory, no habit time, no run tasks (§10), not written to memory |

### 9.7 Example

`ep_9031` → one bundle `kid_birthday_party`, items 7 (케이크 토퍼 … 딸기), situation 생일 / 손님 여러 명 / 컵케이크 굽고 꾸미기 / 디즈니 공주, calendar c1, `use_window` 10-17 14:00–17:00, unbundled 세탁 세제, 로션 (`contracts/fixtures/ep_9031/rationale.json` `intents`). Plain groceries (`ep_9150`) → `bundles: []`, `none_reason` set.

---

## 10. S4 Task generation

**Purpose.** For each bundle: check this home's past reactions, find the time, then let the LLM turn the situation into device tasks (situation preparation). Per-item tasks come from `item_tasks.yaml` in code; the LLM only writes care-notice texts.

**Output.** Draft tasks, kept in memory until S5 and never stored (§5.2), in contract form: `task_id, source, way, actions, trigger, end`, plus `need`, `line`, `target_room`, `meta`.

### 10.1 Steps

1. `catalog` = devices from the hub list with only delegated commands (`never` removed). No list → no LLM call, per-item tasks only (none needing a device either); log a warning.
2. Drop bundles whose intent was **stopped** before in this home (§10.2), or whose intent has a **stopped card in this episode** (a re-run never brings back a stopped card's work, §14); `unclassified` bundles skip memory lookups. Household paused → no S4 at all.
3. `when = find_time(bundle)` for each remaining bundle (§10.3).
4. Per-item tasks from `item_tasks.yaml` (§4.3) for unmasked `care` items.
5. `notice_items` = items that need a fridge notice text (fridge notice rule matched and the household has a fridge with `show_notice`).
6. No bundles and no `notice_items` → done (no LLM).
7. `reactions` per bundle (§10.2). Build the schema (§10.6) and message (§10.5); call `s4`; check (§10.7); retry once; failing → no situation tasks (per-item tasks stay; notices without text are not created).
8. Drop run tasks of `unclassified` bundles.
9. Turn `fridge_notices` into per-item notice tasks (text set, `kind`, `intent_change` kept in `meta`). **Shared-screen rule** (fridge and TV are seen by guests): a notice text must not name the occasion. Drop the notice (no task, recorded `public_text`) if its text contains, as a substring, the bundle's `intent_text`, the intent label name, `situation.event`, `situation.guests`, `situation.theme`, or any of the bundle's `calendar_tags`. A weekday is allowed ("토요일").
10. For each situation task (§10.4): `task_id`, trigger, end, value fill, drop switched-off actions.
11. Cap at `max_lines` (4) per bundle, in `needs` order.
12. Store the result in `episodes.s4` with stage time `s4` (§2.4), for display and replay only: `{llm_called, whens` (bundle index → `{start, end, source}` or null), `skipped_bundles, drafts` (contract task + `need, line, target_room, bundle`, `meta` item/kind/slug), `dropped` (`{slug|item, reason}` plus, for tasks dropped in steps 7/8/10/11, what they said: `line, way, need, actions` as `device.cmd`)`}`. S5 still confirms from the drafts in memory.

### 10.2 This home's reactions (from `cases` with `source = this_home`)

- **Same intent** = same `intent_id` and (both tag lists empty, or they share a tag).
- **Stopped before**: among same-intent rows, the latest with verdict `stopped` or `match` (skip `unconfirmed`) is `stopped` → no situation tasks for this bundle (per-item tasks still made). A later `match` lifts it.
- **Switched-off actions**: action keys of lines with `user = off` in same-intent rows within `line_off_d` (180) days, **plus** action keys of lines currently `checked: false` on this episode's card of the same intent (re-runs) → given to the LLM and removed in code.
- **Changed**: `changes` of the most recent same-intent row that has any → given to the LLM (value to use, or `end_after_start_minutes`).
- Action key: device `type`, except `smart_plug` → `smart_plug:{label}`; paired with `cmd`.
- DB error → retry once; failing → no situation tasks for this episode (do not act without checking).

### 10.3 `find_time(bundle)` — the LLM never makes times

1. `use_window` (calendar) → it.
2. Holiday calendar: a holiday whose tag is in the intent's `related_tags`, date within 14 days of `shared_at` → that date with the holiday's default window.
3. Habit: same-intent rows with verdict `match`; for each, the **occasion start** = `windows.scheduled_start` of the window that wrote the row (found by episode and card `ordinal` from `case_id`; rows without it are skipped), never `when.executed_at` (that is the first preparation run, earlier than the occasion). Sort by (weekday, minute of day); a slot = a run of rows on the same weekday whose starts are within ± `habit_slot_h` (1 h) of the slot's first row. A slot with ≥ `habit_min` (2) rows → candidate at the slot's median start (lower median for even counts). Several candidates → most rows, then most recent row, then earliest weekday. Next occurrence of that weekday at that time that is after `now` and within 14 days of `shared_at`; window end = start + 3 h. Starts are never near midnight in practice; a slot does not wrap across days.
4. Otherwise `None` → run tasks become **held**.

Every `when` satisfies `start > now` and `end > start`; a window that fails is skipped and the next step is tried.

`unclassified` bundles use step 1 and 2 only.

### 10.4 Post-processing per situation task

| Field | Rule |
| --- | --- |
| `task_id` | `t_{slug}#{n}`; `slug` from the LLM (lowercase `[a-z][a-z0-9_]*`, made unique by suffix `_2`); `n` = next number in the episode (never reused), assigned in this order: situation tasks by bundle then `needs` order, then per-item tasks in `item_tasks.yaml` order then item order. Per-item tasks use `name` from `item_tasks.yaml` as slug |
| `source` | `situation` |
| `way = run` | needs `when`; none → status `held` (kept, not sent). `before_start: m` (`minutes` required; `DEMO_MODE=1` → `m = before_start_default_min` demo value) → `time = when.start − m min`. `guest_arrived` → `{event, first_only: true, window: {from: when.start − guest_window_before_min, to: when.end}}`. `event_end` → `{event: event_end, first_only: true, window: {from: when.start, to: when.end + end_fallback_min}}` |
| `way = standby` | one device only (several → drop the task); `when` → `{time: when.start}`; no `when` → `{event: package.brought_in, released: false}` (released with the package, §12.4) |
| `way = notice` | `{event: package.brought_in, released: false}` |
| `end` (run, time or `guest_arrived` trigger) | `{on: event_end, or_time: when.end + end_fallback_min, restore: true}`; cleaning-type tasks (no state to undo: every action's device type is `cleaner`) use `restore: false`. With `end_after_start_minutes` from memory: `{time: when.start + m, restore: true}` |
| `end` (run, `event_end` trigger) | `{on: event_end, after: "{after_event_end_min}m", restore: true}` — the triggering `event_end` itself starts the `after` countdown, so the task runs that long and then restores (no contract change) |
| `end` (standby) | `{on: "{device type}.started", by: user, or_time: when.end (or release + standby_max_min), restore: false}` |
| `end` (notice) | from `item_tasks.yaml` |
| values | every parameter of the command's `value_schema`: item attribute value if it maps (e.g. 포장 count) > LLM value. The LLM value already passed the strict schema (§10.6), so no clamping; parameters the LLM may omit (not in the schema as required) take the device default. Per-item tasks (code) use their `item_tasks.yaml` value or the device default |
| switched-off | remove actions whose key is switched off; a task left with no action is dropped |
| `target_room` | kept for S5 |

### 10.5 User message (`s4_blocks.yaml`)

Order: `[의도 n]` per bundle (unclassified first line added) → `[관리법 문구가 필요한 물건]` → `[이 집]` (household types if any, rooms) → `[이 집 기기]` → `[이 집이 지난번 같은 의도에서 남긴 반응]` (only when reactions exist).

- Intent block: situation fields "모름" when empty; time `"{요일}요일 {start}~{end} ({days}일 뒤)"` or `"모름 (일정이 아직 없음)"`; items with qty and attributes.
- Notice item line: `- {type} × {qty or 모름} [{key}: {value}, …] · {group}{ · 의도 n의 물건}` — attributes included, so the notice can see 냉동, 손질 and the like (R47).
- Device line: `- {id} · {Korean name} · {room or 방 모름} · {cmd}({param} {lo}~{hi} / {a}/{b}/…), …`; text commands as `{cmd}(글자)`; commands without values as the name only.
- Reaction lines: off → line text + action keys; changed → `"{일정 시작 n분 뒤 }{Korean device name}을 {property}({param value, …})로 바꿈"` from `changes` (the time part only when `after_start_minutes` is set), e.g. `"일정 시작 70분 뒤 조명을 color_temp(kelvin 2700)로 바꿈"`.

### 10.6 Schema

```python
def build_task_schema(catalog, bundle_ids, notice_items):
    RoomT = Literal[tuple(catalog.rooms())]
    # one model per (device, cmd): key "device.cmd", value model built from value_schema (int/float ranges, enums);
    # text commands take str; commands without value take no value field
    Action = Annotated[Union[...], Field(discriminator="key")]
    class Need(BaseModel): id: str; bundle: Literal[tuple(bundle_ids)]; need: str; from_: list[str] = Field(alias="from", min_length=1)
    class Trigger(BaseModel): kind: Literal["before_start", "guest_arrived", "event_end"]; minutes: int | None = Field(None, ge=0, le=720)
    class Task(BaseModel):
        need_id: str; slug: str; way: Literal["run", "standby", "notice"]; target_room: RoomT | None
        actions: list[Action] = Field(min_length=1); trigger: Trigger | None
        end_after_start_minutes: int | None = None; line: str
    class FridgeNotice(BaseModel):
        item: Literal[tuple(notice_items)]; kind: Literal["prep", "storage"] | None
        point: str | None; intent_change: str | None; text: str | None
    class TaskPlan(BaseModel): needs: list[Need]; tasks: list[Task]; fridge_notices: list[FridgeNotice] = []
```

### 10.7 Format check (retry once with `s4_retry.txt`)

`need_id` not in needs; `from` empty; `way` standby/notice with a trigger; `way` run without a trigger; `before_start` without `minutes`; `standby` with more than one device; `guest_arrived` when the bundle's guests is empty; `fridge_notices.item` outside `notice_items`; duplicate slug. More than 4 tasks per bundle is not an error (cut in step 11). After the retry, tasks still breaking a rule are dropped one by one.

### 10.8 Prompt summary (`s4_system.txt`)

Needs first, then tasks only where a listed device fulfils a need, then notice texts. Only what the day needs (usually 1–3, never more than 4 per intent; zero is normal). Do not make per-item tasks (fridge, freeze, styler, mattress). One task = one purpose the user switches off. Never run money, heat-starting, door-opening or irreversible actions: use standby. `way` run/standby/notice; triggers before_start / guest_arrived / event_end as minutes only, no dates; guest_arrived only when guests is known. `target_room` = the device's room. Values are numbers or enum values inside the listed ranges, never words. `slug` is one lowercase English word. Notices: `kind` prep/storage, only sure facts, skip what is already processed or obvious, frozen items (`보관`/`가공` 냉동) never get thaw-and-chill advice on arrival (without an intent no notice, since freezing is obvious; with an intent, `intent_change` says to move them to the fridge the day before), adapt to the intent with `intent_change` — but the text is shown on a shared screen, so never name the occasion, guests or theme (a weekday is fine). Answer format (`[답의 형식]`, since S4 has no enforced schema): one JSON object following the appended schema, no prose or code fence, field names and enum values exactly as in the schema, `actions[].key` only from the schema, every `value` field filled with listed values or numbers in range, numbers unquoted, empty fields null.

### 10.9 Failure handling

| Case | Handling |
| --- | --- |
| Reactions lookup fails | Retry once → no situation tasks |
| Format error twice / timeout | No situation tasks; per-item tasks without notice text are not created |
| Need-less task / unknown trigger | Drop that task |
| Value out of range / missing / trigger rules after retry | Drop that task (no clamping; S5 checks again) |
| More than 4 per intent | First 4 in needs order |
| Run task, no time | Held (§11.6) |
| Device room empty | Keep; S5 drops room-specific tasks |
| No device list | No LLM; zero tasks |

### 10.10 Example

`ep_9031` → `t_clean#1` (run, cleaner 거실, 12:30), `t_safe#2` (run, protective, cooktop child_lock + plug off, 13:30), `t_mood#3` (run, display kids_party + light hue 330/45/70, guest_arrived 13:30–17:00), `t_oven#4` (standby, oven 170 °C 20 min, 14:00), `t_fridge#5` 딸기 (storage) and `t_fridge#6` 휘핑크림 (prep) waiting for the package → `contracts/fixtures/ep_9031/plan.v1.json`. The air purifier, styler and fridge in the prompt's device list are not chosen (decoys in the prompt test).

---

## 11. S5 Plan confirmation and cards

**Purpose.** Check the draft against the whole home, confirm the plan, publish a plan version for the hub, create or update cards, and apply reactions. No LLM.

### 11.1 Confirm (`finalize(episode)`)

Runs under the household lock (§2.4) on the state as it is now; `now` is read after the lock is taken, so a card's `updated_at` is never earlier than a `server_time` already returned by the card poll (§12.2). Household paused → every not-started task `cancelled`, nothing new goes live.

1. **Safety net** (drop the task, record `drop_reason`):
   - a command not allowed by `command_policy.yaml` for the task's `way` (run → `run` list; standby → `standby_pattern`; notice → `notice`), or containing a `deny_words` word → `unsafe_cmd`. Applied to situation and per-item tasks; an unknown command is unsafe (fail closed);
   - device or cmd not in the current hub list / in `never` → `not_delegated`;
   - a value outside `value_schema` → `value_out_of_range`;
   - `target_room` set: actions on a device whose room is not `target_room` (or null) are removed from the task and kept in `meta.room_removed` (not shown on the card); only a task left with no action is dropped `room_mismatch`;
   - a noisy device whose `time` trigger falls in `quiet_hours` (22:00–08:00) → `quiet_hours` (event triggers are guarded by the hub, `blocked: quiet_hours`);
   - a `time` trigger earlier than `now − late_grace_min`, or an event window whose `to` is in the past → `late` (re-runs, restart recovery and late packages all use this rule);
   - an end time not after its trigger time → `late`.
2. **Merge with the home's live tasks** (all episodes of the household, including this one's started tasks). Each task gets an interval for overlap: time trigger → [time, end `time` / `or_time`]; event trigger with window → [`from`, end `or_time` or `to`]; unreleased package trigger → [now, now + `standby_max_min`] (a reservation, since the arrival time is unknown); a missing end → + `end_fallback_min`. Same device and overlapping intervals → keep one by priority **started > per-item > already confirmed plan > new plan**; ties → the earlier trigger, then the lower `task_id`. The loser is dropped (`overlap`) if it is a draft, or **cancelled in its own episode** (and that episode publishes a version in the same transaction) if it was live. Same device + same cmd + same value → keep the existing one. `fridge.show_notice` tasks never conflict with each other (step 3 limits them).
3. **Fridge notices**: drop notices with no text; drop a notice whose (`item_type`, `kind`) was shown `notice_repeat_max` (2) times in this home (`care_notices_shown`), unless it has `intent_change`; order intent-wording first, then `prep`, then `storage`; keep `notices_per_screen` (3). Increment `care_notices_shown` when the notice is released.
4. **Cards**: one card per bundle that has situation tasks (held or live). Lines = that bundle's situation tasks in `needs` order (≤ 4), all `checked` (re-runs keep the existing state, §14). Per-item tasks are never on a card. A new card gets the next `ordinal` and a `windows` row in `pending` (§13.1).
5. **Store**: tasks with time or event triggers → `live`; held → `held` (kept `hold_d` days).
6. **Publish** (§11.3) if the plan changed (a task became live, was cancelled, or was released).
7. Episode status: any card with a live line → `notified`; cards with held lines only → `held`; no card → `judged`.

### 11.2 Card creation and update

- New card (`nc_…`): `notify: true`, `updated_at = now`. Template text (§11.4).
- `starts_at` = bundle `when.start` (null when held).
- Any later change of the card (line state, re-run, reaction) → same card, new `updated_at`, `notify: false` — **except** a held card whose time was found (§14), which gets `notify: true` once.
- `stopped: true` → `buttons: []`.
- `summary`: `done` = lines in `done`/`partial`/`user_changed`; `total` = lines not `off`/`stopped`/`cancelled`; `waiting_for` = the event trigger of a `scheduled` line whose trigger window has opened (`window.from` ≤ now) and whose event was not seen yet (`guest_arrived` before `event_end`), else null. Before the window opens it stays null (`ep_9031/card.v1.json`).

### 11.3 Publish a plan version

```
version = episode.plan_version + 1
body = {plan_id, household_id, plan_version: version, devices_revision: current hub revision,
        sent_at: now, tasks: [live tasks in contract form], cancelled: [every cancelled task so far, with restore]}
store plans(version, body); episode.plan_version = version
```

`line`, `need`, `target_room`, `meta` are never sent. Held tasks are not sent. Each task carries `protective: true` when any of its actions matches `command_policy.yaml` `protective` (omitted otherwise). The hub releases a protective task only on an observed end event or a cancellation with `restore: true`; at a time fallback it keeps it and reports `withheld_end_not_observed` (`contracts/rules.md`). `tasks` and `cancelled` never share a `task_id`.

**Restore of a cancelled task** = it had started (§5.2: `started_at` or `start_uncertain`) and its end has `restore: true`; otherwise false. When an execution result arrives for a task that is already cancelled with `restore: false` and the result shows a start (`running` / `completed`, or `failed` / `unknown` after dispatch), the server sets its restore to true and publishes a new version in the same transaction; a duplicate of that result changes nothing (§2.4).

**Which versions the hub gets** (pull, §12.2): the latest version of an episode is pulled while any of these holds — a task is live; a cancelled task with `restore: true` has no restore result yet; or the latest version is not acked yet (so a version made only of cancellations still reaches the hub). The hub picks it up on its next pull; responses to hub events set `plans_changed: true` when a version was created while handling them.

### 11.4 Card text (`card_templates.yaml`, template `common.v1`)

```yaml
common.v1:
  with_time_theme: "{요일}요일 {event}({theme} 테마)에 맞춰 집을 준비해 둘게요"
  with_time:       "{요일}요일 {event}에 맞춰 집을 준비해 둘게요"
  held:            "{event} 준비를 알아챘어요. 일정을 캘린더에 넣어 두시면 그 시간에 맞춰 준비할게요"
  # theme: situation.theme. For unclassified with no event, {event} = "이번"
lines:
  dropped_note: "준비하지 않았어요"
  blocked_note: {plan_unconfirmed: "허브가 최신 계획을 확인하지 못해 시작하지 않았어요", offline: "기기가 연결되지 않아 실행하지 못했어요",
                 in_use_by_person: "사용 중이라 실행하지 않았어요", not_delegated: "맡기지 않은 동작이라 실행하지 않았어요",
                 quiet_hours: "조용한 시간이라 실행하지 않았어요", default: "실행하지 못했어요"}
  user_changed_note: "사용자가 {device_name}{을/를} 바꿔 현재 상태를 유지했어요"   # 을 after a final consonant, else 를
  rejected_note: "허브가 받지 못한 할 일이에요"
  withheld_note: "행사 끝을 확인하지 못해 잠금을 그대로 두었어요"
```

`{event}` = the bundle's first calendar tag, else `situation.event`, else the intent's Korean name cut at the first "·". `ep_9031` → "토요일 생일(디즈니 공주 테마)에 맞춰 집을 준비해 둘게요"; `ep_9120` held → "가족 모임 준비를 알아챘어요. …", after the calendar arrives → "토요일 가족 모임에 맞춰 집을 준비해 둘게요".

### 11.5 Line state (C-7, `contracts/state-mapping.md`)

Recompute a line whenever an ack, execution result, user event or reaction for its task arrives:

1. `off` if unchecked; `stopped` if the card is stopped; `failed` (`rejected_note`) if the ack rejected the task or no ack came in time (checked before the task status, since such a task is `dropped` with `rejected`); `cancelled` / `dropped` from the task status; `held` if held.
2. Else from the task's **expected actions** (each (device, cmd) in the published task). For each action take its latest result of the latest operation (by `at`, then `received_at`); a final result (`completed`, `failed`, `blocked`, `unknown`, `unverifiable`) is never replaced by a later `running`. An action with no result is pending. Then: every action `completed` → `done`; some `completed` and every other action final → `partial`; some `completed` and others pending/running → `running`; none completed and every action final: any `failed` → `failed`, any `blocked` → `blocked` (note from `blocked_note`), else `unknown`; any `running` → `running`; nothing yet → `scheduled`. Ack rejection of the task, or no ack within `ack_timeout_min` → `failed` + `rejected_note` (§12.2).
3. `user_changed` overrides `done`/`partial` when, after the task's first `completed` result and before the window closes, an event `{type}.changed` with `by: user` arrives for one of the line's devices.
4. Priority when several apply: off, stopped > user_changed > done, partial > running > failed, unknown, blocked > scheduled.
5. `end_state` from the task's restore result: all `restored`/`not_needed` → `restored`; any `skipped_user_changed` → `kept_user_change`; any `failed`/`unknown` → `restore_failed`; any `withheld_end_not_observed` (and none failed/unknown) → `withheld`, note from `card_templates.yaml` `withheld_note` ("행사 끝을 확인하지 못해 잠금을 그대로 두었어요"); task with `restore: false` that ended → `none`; otherwise null. Priority: `restore_failed` > `withheld` > `kept_user_change` > `restored`.

### 11.6 Held tasks

- Kept `hold_d` (14) days from judging; not sent; card lines `held`, `when: null`. A held task was never sent to the hub, so when its time is found it keeps its id (§14 step 3).
- A calendar change re-runs the episode (§14); if a time is found the card is updated with times, `notify: true` once.
- `expire_held` (daily): held tasks older than 14 days → `dropped`; card lines `dropped` with `dropped_note`; nothing sent.

### 11.7 Reactions (`POST /v1/cards/{card_id}/reactions`)

| Reaction | Effect |
| --- | --- |
| any, card already stopped | `200`, ignored, return the card |
| `stop` | Every situation task of this card: not started → cancelled (restore false); started → cancelled (restore true). Card `stopped: true`, lines `stopped`, buttons `[]`. Per-item tasks untouched. Publish. Verdict will be `stopped` (§13) |
| `line_off` (task_id) | That task cancelled (restore = started). Line `checked: false`, `off`. Publish |
| `line_on` (task_id) | Started (§5.2) → `409 line_started`. Else the task gets a **new id** (`t_{slug}#{next n}`, same actions, trigger and end; the old id stays in `cancelled`); the line now points to the new id, `checked: true`; status live, or held if the card is held. Publish |

Each change records `checked_changed_at`. Switching every line off is not stop. Return the updated card.

### 11.8 Task and episode end

`end_tasks` (every 10 min) sets `ended` (live tasks only) when:

| Task | Ends when |
| --- | --- |
| Any task with an end event | the end event arrives (with `by` if set), plus `after` if set |
| Time end | `end.time` passed |
| Fallback | `or_time` passed, or `or_after` passed since the trigger fired (package release time for package tasks) |
| Trigger never fired | the trigger window's `to` (event trigger) passed with no matching event, or `time` trigger + `end_fallback_min` passed with no run result — line ends `scheduled` → shown as `dropped` with `dropped_note` |
| Standby never used | `or_time` / `standby_max_min` after release passed (the line stays `scheduled` until then, then `done` if the preset was set, else as above) |
| Per-item task never released | 14 days after judging |
| Rejected by ack / ack timeout | immediately `dropped` (`rejected`), line `failed` |

A task that must restore stays live until its restore result arrives (or 24 h, then `restore_failed`). A protective task that ended at its `or_time` / `or_after` gets a restore result with `withheld_end_not_observed`: it ends at once (`withheld`); a later observed `event_end` for that window does not re-open it (the hub releases what it still holds and reports it as a new restore result, which updates `end_state` to `restored`). `close_episodes` (every 10 min): an episode is `closed` when every task is ended / cancelled / dropped, every cancelled task with `restore: true` has a restore result, every card's window is `closed`, and every window's `memory` is `written` or `ineligible`.

### 11.9 Failure handling

| Case | Handling |
| --- | --- |
| Safety net hit | Drop that task with `drop_reason` (shown in rationale) |
| No situation tasks | No card; per-item tasks still published; none at all → no plan, episode `judged` |
| Hub does not pull / ack | The version stays in the pull (§11.3); after `ack_timeout_min` its new lines are `failed` (`rejected_note`) |
| Reaction after the trigger | Cancelled with restore true in a new version (stop works while running) |
| Duplicate stop | First wins; later ones 200 |
| `line_on` on a started line | 409 |

---

## 12. S6 APIs

The API surface, paths, bodies and status codes are in `contracts/openapi/app.yaml` and `contracts/openapi/hub.yaml`; shapes in `contracts/schemas/`. This section adds server behaviour only.

### 12.1 Common

- **Auth.** App routes: `Authorization: Bearer {APP_DEMO_TOKEN}` → else 401. Hub routes: `X-API-Key` → household by key hash → else 401. Then every household the request names must be the key's, else 403 `forbidden`: the path or body `household_id`, the `household` query of the pull, the owner of `plan_id` (plan → episode → `household_id`) for acks and execution results, and the device ids (must be in that household's list). Checked before anything is read or written. `/health` has no auth.
- **Errors.** Every 4xx/5xx body is `contracts/schemas/error.json`, except `/health` 503, which returns `health.json` (`{"status": "degraded", …}`) as the OpenAPI files say. Body validation failure (models or `validate`) → 422 `validation_error` with `details.path`. Unknown id → 404 `not_found`.
- **Time.** Store `timestamptz`; serialise with `+09:00`.
- **Idempotency.** `event_id`, `result_id`, `source_id` (`contracts/rules.md`).

### 12.2 Behaviour per route

| Route | Server behaviour |
| --- | --- |
| `POST /v1/households` | Create `h_…`, random 32-byte hex key (`hk_` + 64 hex), store its SHA-256; validate household types (§12.3) |
| `PUT …/profile` | Validate types (§12.3) → 422 `household_types_invalid` if blocked; store; affects later orders only |
| `PUT …/calendar` | §8.5 |
| `POST …/pause` | Household lock. true: cancel not-started tasks of every open episode (publish each, same transaction); later orders become `paused_skip` (§7.1); re-runs and S5 add nothing while paused (§11.1). false: later orders judged again. Return the state |
| `GET …/episodes` | Newest first by `shared_at`, `limit` (≤ 100), `before` cursor |
| `GET …/cards?since=` | `since` with a `+` left unencoded (arrives as a space) is accepted. Every card write takes the household lock and sets `updated_at = now()` and `seq` inside it; this read takes the same lock (shared), so no write can commit with an `updated_at` at or before the returned `server_time`. Return cards with `updated_at > since` (or all non-archived cards of open episodes), `server_time` = the time read under the lock. Archived cards are returned once more with their final state, then never |
| `GET …/memory`, `DELETE …/memory/{case_id}` | §13.5 |
| `POST /v1/orders` | §7.1 |
| `GET /v1/episodes/{id}` | Items (unmasked), `item_count`, `masked_count`, item tasks with state, `card_ids` = non-archived cards (≤ 2, `episode.json`). Readable from the start: `items` fill after S1, `item_tasks` and `card_ids` after S5 |
| `PUT /v1/episodes/{id}/order` | §14 (order edit) → 202 |
| `GET /v1/episodes/{id}/rationale` | Readable from S2 on, so a poller sees each stage as it is stored: `404 not_found` until S2 stored `context` (unless the episode was judged before S2, e.g. all items masked); then `evidence`, with `intents` `[]` and `none_reason` null until S3; `card_id` null and `tasks`/`item_tasks` `[]` until S5. Assemble from stored values only (no LLM): intents (+card id of the card with that `bundle_index`, basis), evidence from `context` (`kb_counts` keeps `intent_id, name, n` of rows with `n` ≥ 1 only, as in `contracts/schemas/rationale.json`; the base shares stay in `context`, R48; `kb_counts` null when KB was off, `[]` when only the note; `kb_examples[].overlap` = the example's items with the exact same name in this order, for display only — S3 never sees it, R49), unbundled, masked count, tasks (+devices with type and room), item tasks, executions (latest final result per task and device), observations (verdict and feedback per card) |
| `POST /v1/cards/{id}/reactions` | §11.7 |
| `PUT /v1/hub/households/{hid}/devices` | The same device `id` twice in one list → 422 `validation_error` (`details.path` = the second one). Revision lower than stored → 409 `stale_revision`; equal → 200 no change; higher → store. Plans already published keep their `devices_revision` (the hub checks delegation at run time) |
| `GET /v1/hub/plans?household=` | Latest version of every episode that §11.3 says is still pulled + `paused` + `devices_revision` |
| `POST /v1/hub/plans/{plan_id}/ack` | Every accepted ack answers `204` (`hub.yaml`). Same `plan_version` already acked with the same body → 204, nothing else; with a different body → 204, ignored (the first ack stands). Unknown `plan_version` → 404. `plan_version` older than the latest → stored on that version only; never changes tasks of a newer version. Unknown task ids in `rejected_tasks` → 422. `status: rejected` (whole plan unreadable) → every task of that version that is new in it fails; otherwise only the listed tasks fail. A failed task → `dropped` (`rejected`), line `failed` with `rejected_note`, never re-planned. An ack arriving after `ack_timeout_min` for the latest version: lines failed only by the timeout and whose trigger is still ahead go back to `live` |
| `POST /v1/hub/events` | The outer body is validated as an object with an `events` array (else 422). **Each element is validated on its own** with `event.json` + `validate` (no whole-body model): invalid (schema, unknown device, other household) → `rejected` with code (an element without a usable `event_id` is reported by its array index); valid → one transaction per event (§2.4): duplicate → accepted, skip; else store, then `package.brought_in` → §12.4, others → S7 (§13). `plans_changed` = a new version was published while handling the batch |
| `POST /v1/hub/executions` | Duplicate `result_id` → `{duplicate: true}`. Else, in one transaction: store; `task_id` must be a task of that `plan_version` and `device`/`cmd` one of its actions, else 422; set `started_at` / `start_uncertain` (§5.2); late start of a cancelled task → restore true and a new version (§11.3); recompute the line (§11.5); pass to S7. A result for an older `plan_version` updates its task's state and observation the same way (results are per task, not per version); it never re-lives a cancelled task |

### 12.3 Household type check

Port of SPIRA_KB `spira/household.py` `rule_level` (the installed `spira-kb` package does not ship `config/lists`, so the server reads `contracts/kb/household_types.json`). `kb/household.py`:

```python
def min_people(t: set[str]) -> int:
    n = (2 if "부부·커플" in t else 1) + sum(c in t for c in CHILD_TYPES) + (1 if "부모 + 성인 자녀" in t else 0)
    return max(n, 3) if "3대 함께" in t else n

def rule_level(types: list[str]) -> str | None:        # "blocked" / "rare" / None
    t = set(types); size = next((s for s in SIZES if s in t), None); kids = {c for c in CHILD_TYPES if c in t}
    need, cap = min_people(t), SIZE_MAX.get(size)
    if cap is not None and need > cap: return "blocked"
    if "룸메이트·셰어하우스" in t and (t & {"부부·커플", "부모 + 성인 자녀", "3대 함께"} or kids): return "blocked"
    if "맞벌이" in t and "부부·커플" not in t: return "blocked"
    if "은퇴·노년" in t and t & {"맞벌이", "재택근무"}: return "blocked"
    if "대학생" in t and ("맞벌이" in t or kids or "재택근무" in t): return "rare"
    if "은퇴·노년" in t and kids: return "rare"
    if {"1인": 1, "2인": 2, "3~4인": 3, "5인 이상": 5}.get(size, 1) - need >= 2: return "rare"
    return None
```

Also 422 when a value is not one of the 20 types or a "pick one" axis (size, life stage) has more than one value. `rare` is accepted. A test runs both implementations on every combination the KB sampler can produce when SPIRA_KB is available (§17).

### 12.4 Package brought in (HUB-12)

1. Household lock. Find the household's most recent episode (by `shared_at`) with any **live** task whose trigger is `{event: package.brought_in, released: false}` — per-item tasks and situation standby / notice tasks alike. Cancelled, dropped and held tasks do not count.
2. None → store the event only.
3. Else set every such live task of that episode to `{event: package.brought_in, released: true, at: event.at}`; increment `care_notices_shown` for released fridge notices; publish a version; `plans_changed: true` — all in the event's transaction.
4. Several packages of one order group: everything is released at the first one (known limit).

---

## 13. S7 Observation and this-home memory

**Purpose.** For each card, judge from what happened whether the intent was right, record each line's final state, and write one this-home memory row. No LLM.

### 13.1 Windows (one per card, Q6)

- **Created with the card** (§11.1) as `pending`, so every card gets feedback. `scheduled_start` / `end_due` are set when the card has a time (`end_due` = schedule end + `end_fallback_min`) and updated by re-runs.
- `pending` → `open` at the first confirmed start (`running` / `completed`) of a situation task of the card (`start_at` = that time), or at `scheduled_start` if nothing ran (`start_at` = `scheduled_start`).
- **Closes** (`close_windows`, and right away on the events below), first match:
  - card stopped and no task of the card is running → close now (also for held cards: verdict `stopped`, feedback from the lines as they are);
  - an `event_end` of the household between `scheduled_start` and `end_due` → close at that event;
  - `end_due` passed;
  - held card whose tasks were all dropped (expiry) → close with verdict `unconfirmed`, memory `ineligible`.
- **Linking events to a window**: device events only if the source device is one of the card's devices; home events (`guest_arrived`, `event_end`, source `hub`) by household and time within [`scheduled_start − guest_window_before_min`, `end_due`]. If two windows of the household overlap in time, events in the overlap are linked to neither (known limit). An `event_end` closes only the windows whose bounds contain it.

### 13.2 Confirmation signals (from the plan, by code)

| Task | Signal |
| --- | --- |
| `standby` | an event `{device type}.started` with `by: user` on that device inside the window |
| run with an event trigger | that event (e.g. `guest_arrived`) inside the window |
| run with a time trigger | none (running as planned is not evidence) |

Lines switched off are skipped.

### 13.3 Verdict (per card, first match)

1. Card stopped → `stopped`.
2. Any signal seen → `match`.
3. Otherwise → `unconfirmed`.

### 13.4 Task feedback (per line, at close)

| Value | Condition | Extra |
| --- | --- | --- |
| `off` | final `checked = false` | `when` = `before_run` if the task never started else `during_run`; `at` = date of `checked_changed_at` |
| `changed` | after the task ran, inside the window, a `{type}.changed` with `by: user` on one of its devices, or a restore item `skipped_user_changed` | `changes[] = {device_type, property, to, after_start_minutes}` (minutes from schedule start to the change) |
| `kept` | otherwise | — |

`actions` = action keys of the task. Unchecking then re-checking before the run ends as `kept`.

### 13.5 This-home memory

At close of each window, if the card had situation lines and the intent is not `unclassified`, insert one `cases` row (server DB) and set `windows.memory = written` in the same transaction; otherwise `memory = ineligible`:

| Column | Value |
| --- | --- |
| `case_id` | `home_{household_id}_{episode_id}_{n}` (n = card `ordinal`, never reused) |
| `source` | `this_home` |
| `items` | every unmasked item type of the order, sorted (가나다), no quantities |
| `intent_id`, `intent_text`, `situation` | from S3 |
| `when` | `{weekday of executed_at, calendar_tags, executed_at}`; `executed_at` = window `start_at` (schedule start if nothing ran). Contract shape unchanged; the occasion start used for habits stays in `windows.scheduled_start` (§10.3) |
| `household` | `{types: household_types}` |
| `basket_emb` | `embed_basket(items)` (column is NOT NULL) |
| `kb_version` | null |
| `household_id`, `home_did` (`[{task_id, line, way, actions, ran}]`), `verdict`, `task_feedback` | as above |

Shape: `contracts/schemas/case_row.json`, example `contracts/fixtures/ep_9031/case_row.json`.

`GET /v1/households/{hid}/memory` groups rows by same intent (intent id + tag set): `episodes` (case id, date, verdict), `off_lines` (line, `until` = off date + 180 days, case id), `changed` (device type, display text, case id), `habit_time` (the §10.3 habit result, else null). `DELETE …/memory/{case_id}` deletes that row (and with it its stop, off lines and changes).

Per-item tasks are never written to memory. Writing fails (e.g. embedding error) → window `closed` with `memory = pending`; `close_windows` retries every pending row, and the episode stays open until it succeeds (§11.8).

### 13.6 Example

`ep_9031`: window 13:30 → 17:50 (event_end; cleaning was switched off on Friday, so the first run is child safety); signals: oven started by user 14:20, guest_arrived 13:52 → `match`; feedback: clean off (before_run, 10-16), safety kept (protective, released at the observed event_end), mood changed (light color_temp 2700 K, 70 min after 14:00), oven kept → `contracts/fixtures/ep_9031/case_row.json` and `memory.json`.

---

## 14. Re-run rules

A re-run judges the episode again from S2 with the current items, calendar and devices. Only tasks **not started yet** change; started tasks keep running, keep their ids and lines, and are part of the result.

| Trigger | Episodes re-run | Steps | Card |
| --- | --- | --- | --- |
| New capture within 8 h after judging (S1) | that episode | read new images only, merge, re-run | same card(s) updated, `notify: false` |
| Same order number with new items (S1) | the episode owning that order number | merge, re-run | as above |
| Order edit `PUT /v1/episodes/{id}/order` (APP-07) | that episode | apply edits (below), re-run | as above |
| Calendar change (§8.5) | episodes of the household with held tasks, or with situation tasks none of which started, judged within 14 days; never episodes judged with no intent | re-run | as above; held → time found: `notify: true` once |
| Pause (APP-10) | every open episode | cancel not-started tasks; no re-run | lines `cancelled` |

Re-run procedure:
1. Household paused → no re-run.
2. Run S2 → S4 outside the lock (§2.4). Exclusions given to S4 (§10.1–10.2): intents of stopped cards of this episode; actions of lines currently `checked: false` on the same-intent card.
3. Lock the household and the episode. **Keep** every started task (§5.2) with its id and line. A new draft equal to a kept task (same device, cmd, value) is discarded. Every not-started live or held task is replaced: if a new draft equals it in device, cmd, value and trigger, the existing task stays as it is (same id, no change); a **held** task whose new draft equals it in device, cmd and value keeps its id and takes the draft's trigger and end (it was never sent, so no hub sees a change of meaning; `ep_9120/plan.v2.json`); otherwise the old task is cancelled and the draft becomes a new task with a new number `n`. A cancelled id never comes back (§11.3).
4. Map bundles to cards by `intent_id`:
   - same intent → same card; lines = kept started lines first, then new lines in `needs` order, ≤ `max_lines` in total; a line whose action keys equal an unchecked line keeps `checked: false` (and its task is not sent);
   - intent gone → the card's not-started lines `cancelled`; if it still has started tasks it stays controllable (Stop works) until they end, then `archived`; otherwise `archived` now;
   - new intent → new card (`notify: true`) only while the episode has fewer than 2 non-archived cards; otherwise the new bundle with the lowest number of items is not carded (its situation tasks are dropped `card_limit`).
   - a stopped card never gets new lines.
5. S5 (§11.1) and publish one version with the result.

Order edit: items with `item_id` keep their id; a changed `name` or a new item gets type, group and sensitivity from one LLM call (`retype`, schema `{items: [{name, type, group, sensitive_kind}]}`, `sensitive_kind` with the same five categories and definitions as S1 — `retype_system.txt` includes them). Failure or timeout → that item is stored **masked** (name/type null) and leaves S2–S4, the app shows it in `masked_count`; the user can edit it again. The `sensitive_words` net runs on every edited name. `qty` from the request; label and masking as §7.4. Items missing from the request are deleted.

---

## 15. Evaluation switches and call log

Set in `.env`; read at start (restart to change).

| Switch | Values | Effect |
| --- | --- | --- |
| `KB_MODE` | on / off | off: no KB search; `[비슷한 다른 집 주문]` block omitted |
| `HOME_CONTEXT` | on / off | off: no household types, unusual items or calendar in S3, and no context bonus in the KB ranking |
| `KB_SAMPLE` | 0 < x ≤ 1 | Search only cases with `sha256(case_id)` first 8 hex digits / 2³² < x (§8.4). Same x → same cases; a smaller x is a subset of a larger one. Service: 1.0 |

Order time is always given. Conditions: C0 = off/off, C1 = on/off, C2 = on/on.

For the evaluation (separate plan, not part of this spec) the server also:
- writes every LLM call to `llm_calls` (stage, provider, model, tokens, latency, attempts, outcome);
- stores the S2 output in `episodes.context`, and exposes `spira_server.pipeline.s3_intent.judge_from_context(context, items, llm)` so the same context can be fed to several models without searching again.

---

## 16. Extension points and not implemented

### 16.1 Extension points

| Change | Where |
| --- | --- |
| New device type | Nothing in code. Hub sends it in the device list; add a display name to `device_names.yaml`, its safe commands to `command_policy.yaml` (otherwise they are dropped `unsafe_cmd`); per-item rules in `item_tasks.yaml` if needed |
| New per-item task | `item_tasks.yaml` (+ `label_table.yaml` if a group becomes `care`) |
| New intent | KB list (`contracts/kb/intents.json`, KB-14 rules); prompts read it at start |
| New holiday | `holiday_calendar.yaml` |
| New trigger kind (e.g. departure / return) | `contracts/enums.json` `trigger_event`, `contracts/schemas/plan.json`, `contracts/rules.md` (with the hub, HUB-02); S4 schema `Trigger.kind` and `s4_system.txt` [실행의 시점]; §10.4 trigger mapping; §13.2 signal |
| Different LLM | `LLM_PROVIDER`, `LLM_MODEL` |

### 16.2 Not implemented (do not build)

- Other homes' real records (`other_home`, `OTHER_HOME=on`) — extension 1.
- Linking orders more than 8 h apart into one event — extension 2.
- Queue (SQS/Redis), SSE for cards, calendars other than Google, mydata order intake, real door camera, passing confirmed habits to S3, routine filtering against usual usage — extension 3.
- First wash / first dishwasher run / detergent settings / dehumidifying / pet mode / new-appliance routines / device-event triggers / caution notices — extension 4.
- Re-notifying right before running (COM-13, on hold).
- Push server (FCM): the app shows local notifications from `notify` (APP-14).

---

## 17. Acceptance tests

pytest, LLM `mock` (§6.1), `EMBED_MODE=mock` (§3.1), DB = Postgres with pgvector (docker compose service or testcontainers). Clock fixed by `clock.now` override. Fixture paths are under `contracts/fixtures/`.

| # | Test | Expect |
| --- | --- | --- |
| T1 | `/health` before and after the model loads | 503 then 200 `{"status": "ok"}` |
| T2 | S1: two captures 64 s apart, same household | same `episode_id`; one LLM call after 10 quiet minutes |
| T3 | S1: same `source_id` twice | 200, same episode, no LLM call |
| T4 | S1: mocked output of `ep_9031` | 9 items; labels 딸기/휘핑크림 care, 로션 clue; 고깔모자 qty 6 |
| T5 | S1: 1+1 qty 1 / 2+1 qty 1 / 2+1 qty 2 / no deal | 2 / 3 / 6 / unchanged |
| T6 | S1: sensitive item (LLM kind, and word list only); 치약 | masked, name/type null, `masked_count` 1, absent from S3 message; 치약 not masked, 감기약 masked |
| T7 | S1: zero items | `read_failed` |
| T8 | S2: < 10 past orders / all usual / list | the three statuses |
| T9 | S2: KB < 5 similar | `note` only, S3 message has the "거의 없다" line |
| T10 | S2: `KB_SAMPLE` 0.25 ⊂ 0.5 | sampled case ids nested, deterministic |
| T11 | S2: kb_version kb-v2 search includes kb-v1 cases | yes |
| T12 | Calendar tagging of `ep_9031/calendar.json` (mock) | tags as §8.5; titles not stored |
| T13 | S3 message for `ep_9031` (C2) | equals `tests/expected/s3_message_ep_9031.txt`; C0 has no "다른 집"/"이 집" text |
| T14 | S3 format errors (item in two bundles; field missing from text) | one retry; second failure → no intent |
| T15 | S3 field without basis | that field null, no retry |
| T16 | S4 `find_time`: calendar / holiday / habit (2 matches same slot) / none | window or held |
| T17 | S4 for `ep_9031` (mock) | tasks equal `ep_9031/plan.v1.json` tasks (ids per §10.4 numbering, triggers, ends, values; needs the fixture renumbering in `contracts/`) |
| T18 | S4 second birthday after `ep_9031` memory | no cleaning task (switched off), child-safety task present, light uses color_temp 2700 |
| T19 | S4 stopped before / later match | no situation tasks / tasks again |
| T20 | S4 unclassified bundle | no run tasks |
| T21 | S4 value out of range after retry | task dropped |
| T22 | S5 card for `ep_9031` | equals `ep_9031/card.v1.json` (ignoring timestamps) |
| T23 | S5 safety net: quiet hours, room mismatch, never cmd | dropped with reason |
| T24 | S5 fridge notices: 4 notices, one repeated twice | 3 shown, order intent > prep > storage |
| T25 | Reactions: line_off before start → v2 equals `ep_9031/plan.v2.json` | cancelled restore false |
| T26 | Reactions: line_on after start | 409 |
| T27 | Reactions: stop while running | cancelled restore true; later reactions 200 ignored |
| T28 | Hub pull after package event | `plans_changed: true`; pull equals `ep_9031/pull.json` |
| T29 | Executions and events of `ep_9031` in order, and in a shuffled order (late `running` after `completed`) | final card equals `ep_9031/card.final.json` both times |
| T30 | Duplicate event / result | accepted once / `duplicate: true` |
| T31 | Ack with a rejected task | line failed, not re-planned |
| T32 | Window close for `ep_9031` | verdict match, feedback and row equal `ep_9031/case_row.json` (except `basket_emb`, `created_at`) |
| T33 | Memory API | equals `ep_9031/memory.json`; delete removes the row |
| T34 | `ep_9120`: held card, calendar PUT | `card.held.json` → `card.found.json` (`notify: true`), plan v2 equals fixture; unknown device type `speaker` accepted |
| T35 | `ep_9150`: groceries | no card, plan equals `ep_9150/plan.v1.json`, episode `judged` |
| T36 | Pause | not-started tasks cancelled, new order `paused_skip` |
| T37 | Order edit | not-started tasks replaced, started kept, card `notify: false` |
| T38 | Held expiry after 14 days | lines dropped |
| T39 | Household types | blocked combination 422; rare accepted; equals SPIRA_KB `rule_level` on all sampled combinations when SPIRA_KB is importable |
| T40 | Every response body | validates with `spira_contracts.validate` |
| T41 | Auth | missing token 401, other household's key 403 |
| T42 | `DEMO_MODE=1` | quiet exactly 30 s, cleaning exactly 3 min before (even if S4 wrote 90), fallback exactly +10 min, notice after door exactly 2 min |
| T43 | Crash after an event insert but before commit; then resend | effects applied once |
| T44 | Restart during S1 (images read, items not stored) and during S2–S5 | episode resumes from its last stage; no image lost before items are stored |
| T45 | Stop the last not-started task | a cancellation-only version is pulled until acked |
| T46 | Stop, then a late `running` result of that task | new version with `restore: true`; a duplicate of the result changes nothing |
| T47 | Re-run after line off / Stop / pause | off line stays off, stopped card gets no tasks, paused home gets nothing |
| T48 | Re-run with a started task | task kept with its id and line; no duplicate task |
| T49 | Two episodes of one household confirmed at the same time, same device | one task wins by priority; the loser cancelled in its own episode |
| T50 | Stale ack (older version), whole-plan rejection, repeated ack | as §12.2 |
| T51 | Two actions, one `completed`, one without result | line `running`, not `done` |
| T52 | No ack within `ack_timeout_min`; standby never used | lines `failed`; standby ends at its `or_time` |
| T53 | Memory write fails at window close | `memory = pending`, retried, episode not closed meanwhile |
| T54 | Two calendar PUTs, the first tagging finishes last | first result discarded |
| T55 | All items masked | no S3 call, episode `judged`, `masked_count` only |
| T56 | Order edit, `retype` timeout | edited item masked, not in S3 |
| T57 | KB DB timeout | `judged` with `error.stage = s2`, nothing prepared |
| T58 | Trigger already past by more than `late_grace_min` (re-run, late package); holiday window earlier today | task dropped `late`; next holiday occurrence used |
| T59 | LLM proposes `oven.start` as standby | dropped `unsafe_cmd` |
| T60 | Ack / execution with another household's `plan_id`; events batch with one bad element | 403; valid events accepted, bad one in `rejected` |
| T61 | Paused household, same `source_id` twice | same `paused_skip` episode |
| T62 | `event_end`-triggered task: one `event_end` both starts it and anchors `end {on: event_end, after: 60m}` (shared fixture with the hub) | plan carries that end; `end_tasks` does not end the task at that same event, ends it 60 min later and expects the restore result; no second `event_end` needed |
| T63 | Hub unreachable for more than `ack_timeout_min`, then acks the old version and pulls | lines failed by timeout whose trigger is still ahead go back to `live`; past ones stay `failed`; no duplicate effects |
| T64 | S5 for `ep_9031` | `t_safe#2` has `protective: true`, `t_mood#3` has no `protective` |
| T65 | Protective task, restore result `withheld_end_not_observed` at `or_time` | task ended, line `end_state` `withheld` with the note; no 24 h wait |
| T66 | S4 notice text containing `situation.theme` or a calendar tag | notice dropped (`public_text`); a text with only a weekday is kept |

---

## Appendix A. Coverage of the Notion spec

| Notion | Item | Here |
| --- | --- | --- |
| 0 | Role split, II mapping, scope rule (two moments), no-time handling | §0, §10.3 |
| III-A 1–2 | Platform, Python 3.12, stack | §2, §3.2 |
| III-A 3 | Dev machine (MacBook Air M4, Docker, Python 3.12.13) | §3.3 (commands); machine details stay in Notion (paper) |
| III-A 4 | Cost estimate | not needed for implementation; call log §15 |
| III-B | Libraries, references | §3.2; references stay in Notion (paper) |
| IV intro | Never ask, example scenario | header, §0, §6.2 |
| S1 | Receive, 8 h group, 10 min quiet, MAX_IMAGES, source_id, pause, prompts ①②③, schema, retry text, label table, sensitive (5 kinds + words), required fields, failure table, numbers | §7, §4.1–4.2, §4.5, prompts `s1_*` |
| S2 | order_time, this_home (types, unusual 3 states, calendar), KB search (floor, min, bonus, reps), calendar tagging prompts ①②③, rules, numbers, failure table, `KB_SAMPLE` | §8, §15, prompts `cal_*` |
| S3 | Message blocks per condition, system prompt (F1–F5), schema, format check, retry text, rules (labels, unclassified, times by code), failure table | §9, prompts `s3_*` |
| S4 | Stop check, find_time, ITEM_TASKS, LLM (F6–F7), way table, schema, post-processing, reactions table, numbers, failure table | §10, §4.3–4.4, prompts `s4_*` |
| S5 | Safety net, merge priority, fridge notices, cards and checkboxes, reactions comparison, re-run table, held 14 days, failure table | §11, §14 |
| S6 | Pull-only, ack, executions, English codes, brought-in linking, rationale, memory API, failure table | §12, `contracts/` |
| S7 | Windows, ITEM_TASK_END, signals, verdict, task feedback, memory row, memory API, failure table | §13, §4.3 |
| Extensions 1–4 | | §16.2 |
| Appendix B | DB tables, indexes, KB / server DB split | §5, `migrations/0001` |

## Appendix B. Decisions made in this spec

Not yet in the Notion server spec (synchronised in one pass later). B.2 lists the decisions from the external review.

| # | Decision | Where |
| --- | --- | --- |
| Q1 | KB versions are cumulative: search `kb_version` number ≤ `KB_VERSION` number | §8.4 |
| Q2 | All stored and sent values use English codes (`contracts/enums.json`); S4 schema `way` run/standby/notice, notice `kind` prep/storage | §6.3, §10.6 |
| Q3 | Episode status uses the APP-11 values only | §5.2 |
| Q4 | Draft tasks use the contract `end` shape | §10.4 |
| Q5 | `task_id = t_{slug}#{n}`; the LLM writes `slug`; `n` is per episode and never reused | §10.4, `s4_system.txt` [문구] |
| Q6 | Verdict, observation window and memory row are per card (intent); case id `home_{hid}_{ep}_{n}` | §13 |
| Q7 | Memory row has no `episode_id` column | §13.5 |
| Q8 | `off` feedback `when` is `before_run` / `during_run` | §13.4 |
| G7 | Holiday calendar: fixed-date tags only, 2026–2027 dates, default windows | §4.4 |
| G8 | Habit slot = same weekday, start ± 1 h, ≥ 2 matches, median start; tag match = both empty or overlap | §10.2–10.3 |
| G9 | `KB_SAMPLE` via SHA-256 of `case_id`; iterative scan on pgvector 0.8 | §8.4 |
| G10 | Bulk = qty ≥ 3 or ≥ 1 kg in the name; styler course from material table | §4.3, §4.5 |
| G11 | Starting sensitive word list; `core_noun` rule | §4.5, §7.4 |
| G12 | Order edit re-types changed names with one small LLM call | §14 |
| G13 | Device display names from `device_names.yaml` | §4.5 |
| G14 | Card text templates with fallbacks | §11.4 |
| G15 | Quiet hours for noisy time triggers by the server (event triggers by the hub); overlap priority; name dedupe without order number; episode end rule | §11.1, §11.8, §7.2 |
| G16 | 60 s for every LLM call; Claude Opus 5.5 for development | §4.1, §6.1 |
| D1 | Docker build context is the repository root (the server reads `contracts/`) | §3.3 |
| D2 | Household combination rules ported from SPIRA_KB `spira/household.py` (package does not ship the lists) | §12.3 |
| D3 | Hub API key = `hk_` + 64 hex, stored as SHA-256 | §12.2 |
| D4 | Device list stored whole (`device_lists`); `intent_labels` and `holiday_calendar` are files, not tables | §5.1 |
| D5 | Per-item tasks assume command names `super_freeze`, `set_course_standby` (styler, shoe care), `mode: deodorize` and events `fridge.super_freeze_done`, `purifier.odor_normal`; used only if a hub registers such devices (not in the fixtures; to agree with the hub owner when needed) | §4.3 |
| D6 | Cleaning-only tasks end with `restore: false`; other run tasks `restore: true` | §10.4 |
| D7 | `LLM` call log table `llm_calls`; `judge_from_context` for evaluation | §15 |

### B.2 From the external review (11-17)

| # | Decision | Where |
| --- | --- | --- |
| R1 | A version made only of cancellations stays in the pull until acked; a late start of a cancelled task republishes it with `restore: true` | §11.3 |
| R2 | Re-runs keep started tasks (ids, lines), keep unchecked lines off, never revive stopped cards; at most 2 non-archived cards, extra bundles not carded | §14 |
| R3 | Server-side command allow list per `way` (`command_policy.yaml`), fail closed | §4.5, §11.1 |
| R4 | Hub auth resolves `plan_id` to its household | §12.1 |
| R5 | One transaction per input; household lock before episode locks; stages committed and resumable | §2.4 |
| R6 | Line-on gives the task a **new id**; `tasks` and `cancelled` never share an id (open question 1) | §11.7 |
| R7 | Unused standby ends at its `or_time` / `standby_max_min`; no ack within `ack_timeout_min` → line failed (open question 2) | §11.8, §12.2 |
| R8 | Per-item tasks only when exactly one matching device; standby targets one device (open question 3) | §4.3, §10.4 |
| R9 | Triggers more than `late_grace_min` in the past are dropped `late` (open question 4) | §11.1 |
| R10 | Intent change on re-run: the old card stays controllable while its tasks run (open question 5) | §14 |
| R11 | `started` means a `running` / `completed` result; `blocked` never | §5.2 |
| R12 | Durations are integers with unit suffixes; demo values exact; demo replaces `before_start` minutes | §4.1, §10.4 |
| R13 | Calendar: HMAC fingerprint for change detection, revision guard for async tagging | §8.5 |
| R14 | Habit time from the occasion start (`windows.scheduled_start`), not the first run | §10.3 |
| R15 | Windows created with the card; home events linked by time bounds; memory retried until written | §13 |
| R16 | Masking before cross-pass dedupe; all-masked orders skip S2–S5; failed retype → masked | §7.2, §14 |
| R17 | Event batches validated per element; `/health` 503 uses `health.json` | §12 |

### B.3 From the hub spec review (11-19, hub PR #19)

| # | Decision | Where |
| --- | --- | --- |
| R18 | `protective` tasks (child lock, power cut) from `command_policy.yaml`; released only on an observed end or a cancellation; at a time fallback the hub reports `withheld_end_not_observed` → `end_state` `withheld` | §4.5, §11.3, §11.5, §11.8 |
| R19 | Shared-screen notices never name the occasion, guests or theme (prompt + code check) | §10.1 step 9, §10.6 |
| R20 | `ep_9031`: the line switched off on Friday is cleaning, not child safety (hub owner's choice) | examples, T18 |

### B.4 From the implementation plan (11-19)

| # | Decision | Where |
| --- | --- | --- |
| R21 | Unused standby with a time trigger ends at the schedule end (`or_time`); `ep_9031` fixtures carry it (contracts PR) | §10.4, T17 |
| R22 | A held task keeps its id when its time is found (never sent to the hub) | §11.6, §14, T34 |
| R23 | `summary.waiting_for` only after the trigger window opens | §11.2, T22 |
| R24 | `EMBED_MODE=mock` for tests; `spira-kb[embed]` is an optional extra | §3.1, §3.2, §17 |
| R25 | Draft tasks are never stored (wording aligned with §5.2) | §10 |
| R26 | Duplicate items: same name, and qty and order_no each equal or missing on one side; same rule inside a pass and across passes (11-19, 서진) | §7.2, T4 |
| R27 | `order_items` pk (`episode_id`, `id`): `it_n` is numbered inside the episode | §5.1 |
| R28 | Room check per action: only the actions in another room are removed (recorded in `meta.room_removed`, not on the card); the task is dropped only when none remain (11-19, 서진) | §11.1, T23 |
| R29 | `pick_reps`: when the list is already full, `none` (share ≥ `none_min`) takes the last place | §8.3 |
| R30 | Calendar tagging: ids missing from the LLM answer get `[]` with `tagged = true` (not retried); the retry text is `s1_retry.txt` | §8.5, T12 |
| R31 | `episodes.stage` stays `s2` after S3 and S4 (their results live in `intent`); S5 sets `done` when it commits | §2.4, T44 |
| R32 | A held run task carries the end `{on: event_end, restore: true}` (cleaner only: `false`) until its time is found (§14) | §10.4, §11.6 |
| R33 | A situation `notice` task uses the fridge rule of `item_tasks.yaml`: trigger `package.brought_in` (released false) and the fridge end | §10.4 |
| R34 | Shared-screen word check (`public_text`): words = every bundle's `intent_text`, intent name, `situation.event` / `guests` / `theme` and calendar tags | §10.4, T66 |
| R35 | Drops are kept: S4 drops in `episodes.intent.s4` (`dropped`, `skipped_bundles`); S5 drops as `tasks` rows with status `dropped` and `drop_reason` (shown in the rationale) | §10.9, §11.9 |
| R36 | `finalize` reads `now` after the household lock (card `updated_at` vs the poll's `server_time`) | §11.1, §12.2 |
| R37 | Line state: an ack rejection is checked before the task status (`dropped` + `rejected` → `failed`) | §11.5, T31 |
| R38 | Ack answers 204 as `hub.yaml` says (the spec said 200 for a repeat); a different body for an acked version is ignored; duplicate device ids → 422; unencoded `+` in `since` accepted (11-19, 서진) | §12.2, T50 |
| R39 | Build order (11-19, 서진): S1–S5 → dry run tool → S6 minimal API (households, profile, calendar, cards, devices, plan pull, ack) → dry run A/B → review → rest of S6 and S7 → hub integration 11/27 | §12, §13 |
| R40 | S1 reads carts and product pages as well as order screens (tests and demos share a temporary cart); unchecked, sold-out and recommended items are skipped; `qty` / `order_no` null when not shown (11-21, 서진) | §0, §7, `s1_*.txt` |
| R41 | Anthropic calls use JSON outputs (`output_config.format`), not forced tool use; the enforced schemas (S1, calendar, S3) stay within the documented strict-schema limits (16 unions, 24 optional fields; test). Found in dry run A (11-21) | §6.1, §3.2 |
| R42 | S4 runs without an enforced schema: the schema is sent as prompt text and the stage validates (its schema grows with the devices; Anthropic refused it as too large in dry run A). `s4_system.txt` [답의 형식] states the format; prose or code fences around the JSON are cut away (11-21, 서진) | §6.1, §10.8 |
| R43 | S3 format check: situation values are compared with `intent_text` ignoring spaces and the list marks `,` `·` `/`, and the key word is split on them too (a theme "하츄핑, 공주, 핑크" written as "하츄핑·공주·핑크" was retried in dry run A, 11-21) | §9.5 |
| R44 | S3 links a calendar event only if its tags share one of the intent's `related_tags` (intents with related tags only): one retry, then the link is removed and the bundle kept. Prompt: no link to an event of another occasion; `intent_text` repeats the fields' words (dry run A 02: birthday items linked to "가족 모임"; a reworded activity caused a retry, 11-21, 서진) | §9.2, §9.5 |
| R45 | S1 `테마` is written only for decorating goods (party and event supplies, decorations, cakes, gift wrap); colour and size options of clothes, shoes, accessories and household goods are not a theme (dry run A 08 and 04/06/07: "화이트", "그레이+블랙" read as themes, 11-21, 서진) | §7, `s1_system.txt` |
| R46 | S4 fridge notices for items that arrive frozen: no thaw, wipe or chill advice on arrival; without an intent no notice (freezing is obvious; 11-21 서진: notices only for what people miss), with an intent `intent_change` says to move it to the fridge the day before (one notice at arrival, no separate thaw task). Prompt examples for both (dry run A 04/06/07: frozen 삼겹살 and 고등어 were told to be wiped and chilled, 11-21, 서진) | §10.8, `s4_system.txt` |
| R47 | S4 `[관리법 문구가 필요한 물건]` lines carry the item attributes (`[가공: 냉동, 보관: 냉동]`); without them the R46 frozen rule could not apply (dry run A 04/06/07 rerun: frozen 삼겹살 and 고등어 still told to chill, the block showed no attributes, 11-21, 서진) | §10.8, `s4_blocks.yaml`, `s4_tasks.py` |
| R48 | KB neighbours: `sim_floor` 0.6 → 0.70 (start value, tuned) and intent counts shown with the KB base rate (`share`, `base_share`, `base_total`; `none` always listed); the S3 KB block says to prefer what came up "more than usual" and to read `none` only when above its usual share. No thresholds or labels: S3 compares the two shares. Context bonuses kept (household bonus conditions left to tuning). Dry run B (kb-v1, 2,080 cases): cases sharing 0–1 items scored 0.58–0.69, all 200 were above 0.6 for the birthday order, the kept cases followed the KB's 64 % `none`, bonuses moved 8–26 of 50; no KB case shared 2+ items with the test orders (11-21, 서진) | §8.3, §8.6, §9.3, `s3_blocks.yaml`, `numbers.yaml` |
| R49 | S3 KB examples drop the line "이번 주문과 겹치는 물건: N개 중 K개" and the rule "fewer shared items = less alike"; the how-to says example items may be the same item under another name. Exact names undercounted (B8: 28 of the 31 kept cases shared 0 names, yet were the right kid birthday cases); an embedding match per item name was measured and rejected, same and different items overlap (나무젓가락 0.92, 생일 초 0.67 vs 클라이밍 초크 0.71, 케이크 0.76). S3 sees both item lists and judges itself; search and counts unchanged (11-22, 서진) | §8.3, §9.3, `s3_blocks.yaml`, `s2_context.py` |
| R50 | S1 `type` keeps an occasion or use word from the product name ("타요풍선 생일파티세트" → 생일 풍선, "생일초 공룡초 케이크 초" → 생일 초) and drops flavour, colour and character (theme attribute only); same product, same type. Dry run B8/B9 (same cart photo): S1 read 생일 풍선 / 포도맛 탄산음료 once and 풍선 세트 / 탄산음료 once; the whole similarity band moved about 0.025 and the KB neighbours above 0.70 went from 31 to 2 (KB block off). Shortening names (dropping modifiers) was rejected: occasion words are search cues and the theme already has its own attribute (11-22, 서진) | §7, `s1_system.txt` |
