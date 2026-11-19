# Build context is the repository root (spec §3.3, D1): the server reads contracts/kb and the generated models.
#   docker compose up --build        (from server/; compose sets context: ..)
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /repo
COPY contracts/kb contracts/kb
COPY contracts/generated/python contracts/generated/python
COPY server/pyproject.toml server/pyproject.toml
COPY server/spira_server server/spira_server

WORKDIR /repo/server
RUN pip install --no-cache-dir -e ../contracts/generated/python -e ".[embed]"

COPY server/alembic.ini alembic.ini
COPY server/migrations migrations
COPY server/config config

EXPOSE 8000
CMD ["uvicorn", "spira_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
