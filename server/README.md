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

## Migrations

The same migrations create the `cases` table in two databases.

| Target | Command | URL variable |
| --- | --- | --- |
| Server DB (default) | `alembic upgrade head` | `DATABASE_URL` |
| Knowledge base DB (Neon, owner account, Seojin only) | `alembic -x db=kb upgrade head` | `KB_MIGRATION_URL` |

`0002` runs on the server DB only (skipped with `-x db=kb`).
