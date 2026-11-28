# SPIRA Server

Owner: Seojin Lee

Reads a shared order, retrieves similar cases from the knowledge base, judges the intent, creates tasks, confirms the plan, and serves the App and Home Hub APIs (S1–S7). See [`spec.md`](spec.md).

## Layout

| Path | What |
| --- | --- |
| `spira_server/` | Application code (FastAPI): `settings`, `clock`, `config`, `db/`, `api/`, `llm/`, `kb/`, `pipeline/` |
| `migrations/` | Alembic migrations (`0001` cases, `0002` core tables) |
| `config/` | Tables and starting values as YAML |
| `spira_server/prompts/` | LLM prompts (Korean originals) |
| `tests/` | pytest (LLM `mock`, `EMBED_MODE=mock`, local Postgres) |

## Run locally

```bash
cp .env.example .env          # fill in values locally; never commit .env
docker compose up --build     # api on :8000, postgres + pgvector on :5432 (build context = repository root)
docker compose exec api alembic upgrade head
curl localhost:8000/health    # 503 until the DB and the embedding model are ready
```

The first start downloads BGE-M3 (~2 GB) into the `hf-cache` volume.

## Tests

Python 3.12. Tests need only the Postgres container; no API keys, no model download.

```bash
docker compose up -d db
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ../contracts/generated/python -e ".[dev]"
pytest
```

Tests create and wipe their own databases `spira_test` and `spira_kb_test` on the same Postgres (override with `TEST_DATABASE_URL`, `TEST_KB_DATABASE_URL`). They set every environment variable themselves, so `server/.env` does not affect them.

## Dry run (S1–S5 without the hub)

`scripts/dry_run.py` sends one folder of order screenshots through S1–S5 with the settings in `server/.env`
(real LLM, `EMBED_MODE=bge`, local Postgres) and writes `out/<folder>/` with the result of every stage and `checks.txt`.

```bash
docker compose up -d db
pip install -e ../contracts/generated/python -e ".[dev,embed]"
cp dev/home.example.yaml dev/home.yaml
python scripts/dry_run.py --images orders/01_birthday --home dev/home.yaml --kb off
```

| Option | Use |
| --- | --- |
| `--kb on` | KB search (needs `KB_DATABASE_URL`, `KB_VERSION`). Also writes `kb_search.tsv` and `kb_sweep.txt` (below) |
| `--now 2026-11-20T21:00:00+09:00` | Run as if at that time (calendar dates in `home.yaml` are relative to it) |
| `--split` | Post each image as its own share (grouping) |
| `--resend` | Post the first share again with the same `source_id` |

Each order folder holds 1–3 jpg/png screenshots (names, addresses and phone numbers cut out: the images go to the
LLM provider) and optionally `answer.txt`:

```text
딸기 · 2
컵케이크 믹스 · ?
감기약 · 1 · 가림
제외: 위쪽 배송지 영역은 가림
```

With `--kb on`, `checks.txt` has "S2 KB searched" (fails when the KB search failed: S2 then closes the episode as
`judged`, which otherwise looks like a correct "no intent"), and two more files help check the search numbers
(`sim_floor`, `max_use`, `w_cal`, `w_house`):

| File | Content |
| --- | --- |
| `kb_search.tsv` | Every searched case in sim order: sim, calendar and household bonus, score, above the floor, rank among the used cases, representative, intent, items, situation, an empty `ox` column for marking "really similar?" |
| `kb_sweep.txt` | Sim by rank, cases above the floor, sim range of the used cases, cases in the used set only because of the bonus, best sim per intent; what S3 saw against the KB base rate; the same cases summarised again for floors 0.5–0.75 × caps 20–200; the same search at `KB_SAMPLE` 0.25 and 0.5 (two more read-only queries, no LLM) |

`orders/`, `out/` and `dev/home.yaml` are git-ignored. The household in `home.yaml` is deleted and written again on
every run.

## Demo with the hub and the Simulator (S6–S7)

With `DEMO_MODE=1` the server runs a story clock (`spec.md` §12.6) that the hub follows, and the demo shell's
house view moves it. After `scripts/demo_home.py` (keys in `out/demo.env`), one terminal from the repository root:

```bash
server/scripts/demo_live.sh            # add --fresh for a house that starts from the beginning
```

It writes the hub installation and the Simulator profile from the demo home (`scripts/demo_peers.py`, into
`out/peers/`), then starts MQTT (unless one is already on 1883), the server, the Simulator, the hub and the demo
shell, each log line prefixed (`[server]`, `[hub]`, …) and kept in `out/live/`. Ctrl+C stops all of them. The first
run makes `simulator/.venv` (Simulator, hub and demo shell) and `out/operator.token`. It also rebuilds the App in the phone (`app/scripts/demo-shell-web`, needs `flutter`) when `app/build/web` is missing, older than `app/lib`, or built for another address; `DEMO_APP_BUILD=0` skips that. Ports: `SERVER_PORT` 8000,
`SIM_PORT` 8730, `HUB_PORT` 8088, `SHELL_PORT` 8733. The Simulator keeps device states and the hub its plans in
`/private/tmp/spira-{household}…`; `--fresh` deletes both.

## Migrations

The same migrations create the `cases` table in two databases.

| Target | Command | URL variable |
| --- | --- | --- |
| Server DB (default) | `alembic upgrade head` | `DATABASE_URL` |
| Knowledge base DB (Neon, owner account, Seojin only) | `alembic -x db=kb upgrade head` | `KB_MIGRATION_URL` |

`0002` runs on the server DB only (skipped with `-x db=kb`).
