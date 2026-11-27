#!/usr/bin/env bash
# One terminal for the whole live demo (server/README.md "Demo with the hub and the Simulator"):
# MQTT, server (DEMO_MODE=1), Simulator, hub and demo shell, with each log line prefixed by its process.
# Ctrl+C stops all of them.
#
#   server/scripts/demo_live.sh            from the repository root, after scripts/demo_home.py (out/demo.env)
#   server/scripts/demo_live.sh --fresh    also forget the Simulator's device states and the hub's plans
#
# First run: makes simulator/.venv (Simulator, hub and demo shell share it) and out/operator.token.
# Ports: SERVER_PORT (8000), SIM_PORT (8730), HUB_PORT (8088), SHELL_PORT (8733), MQTT_PORT (1883).

set -euo pipefail
export PYTHONUNBUFFERED=1          # log lines show up as they happen

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
OUT="$ROOT/server/out"
SERVER_VENV="${SERVER_VENV:-$ROOT/server/.venv}"
PEERS_VENV="${PEERS_VENV:-$ROOT/simulator/.venv}"
SERVER_PORT="${SERVER_PORT:-8000}"
SIM_PORT="${SIM_PORT:-8730}"
HUB_PORT="${HUB_PORT:-8088}"
SHELL_PORT="${SHELL_PORT:-8733}"
MQTT_PORT="${MQTT_PORT:-1883}"
TMP="${DEMO_TMP:-/private/tmp}"
[ -d "$TMP" ] || TMP=/tmp

say() { printf '\033[1m[live]\033[0m %s\n' "$*"; }
die() { say "$*"; exit 1; }

[ -f "$OUT/demo.env" ] || die "server/out/demo.env 이 없어요: cd server && python scripts/demo_home.py --home dev/home.yaml 먼저"
# shellcheck disable=SC1091
source "$OUT/demo.env"
[ -x "$SERVER_VENV/bin/uvicorn" ] || die "서버 가상환경이 없어요: $SERVER_VENV"

MOSQUITTO="$(command -v mosquitto || true)"
for p in /opt/homebrew/sbin/mosquitto /usr/local/sbin/mosquitto /usr/sbin/mosquitto; do
  [ -n "$MOSQUITTO" ] || { [ -x "$p" ] && MOSQUITTO="$p"; }
done
[ -n "$MOSQUITTO" ] || die "mosquitto 가 없어요: brew install mosquitto"

busy() { (echo >"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
for port in "$SERVER_PORT" "$SIM_PORT" "$HUB_PORT" "$SHELL_PORT"; do
  busy "$port" && die "포트 $port 를 이미 쓰고 있어요. 따로 켜 둔 서버·허브·시뮬레이터·demo-shell 을 먼저 꺼 주세요"
done

if [ ! -x "$PEERS_VENV/bin/python" ]; then
  say "처음 한 번: 시뮬레이터·허브·demo-shell 가상환경을 만들어요 (몇 분)"
  python3.12 -m venv "$PEERS_VENV"
  "$PEERS_VENV/bin/pip" install -q -e contracts/generated/python -e 'simulator[dev]' -r demo-shell/design/requirements.txt \
    -r hub/requirements.txt -r demo-shell/requirements.txt
fi
"$PEERS_VENV/bin/python" -c "import fastapi, httpx, multipart, yaml, uvicorn" 2>/dev/null \
  || "$PEERS_VENV/bin/pip" install -q -r demo-shell/requirements.txt            # demo shell in the same venv
[ -f "$OUT/operator.token" ] || { umask 077; openssl rand -hex 16 > "$OUT/operator.token"; }
OPERATOR_TOKEN="$(cat "$OUT/operator.token")"

SIM_DB="$TMP/spira-$SPIRA_HOUSEHOLD_ID.db"
HUB_DB="$TMP/spira-hub-$SPIRA_HOUSEHOLD_ID.sqlite3"
if [ "${1:-}" = "--fresh" ]; then
  say "집 상태를 처음으로: 시뮬레이터·허브 저장 파일을 지워요"
  rm -f "$SIM_DB" "$SIM_DB"-* "$HUB_DB" "$HUB_DB"-* "$HUB_DB.lock"
fi

(cd server && "$SERVER_VENV/bin/python" scripts/demo_peers.py --home "${DEMO_HOME_YAML:-dev/home.yaml}" \
  --household "$SPIRA_HOUSEHOLD_ID")

SERVER="http://127.0.0.1:$SERVER_PORT"
LOGS="$OUT/live"
mkdir -p "$LOGS"
trap 'trap - INT TERM EXIT; say "모두 끄는 중"; kill 0 2>/dev/null; wait 2>/dev/null' INT TERM EXIT

run() {   # run NAME FUNCTION : log lines as "[NAME] ...", also kept in server/out/live/NAME.log
  local name="$1"
  ("$2" 2>&1 | while IFS= read -r line; do printf '[%s] %s\n' "$name" "$line"; done | tee "$LOGS/$name.log") &
}

mqtt() { exec "$MOSQUITTO" -p "$MQTT_PORT"; }
server() {
  cd server && DEMO_MODE=1 exec "$SERVER_VENV/bin/uvicorn" spira_server.main:app --host 127.0.0.1 --port "$SERVER_PORT"
}
sim() {
  cd simulator && WORLD_PROFILE="$OUT/peers/profile.json" WORLD_DB="$SIM_DB" WORLD_OPERATOR=1 \
    WORLD_OPERATOR_TOKEN="$OPERATOR_TOKEN" MQTT_PORT="$MQTT_PORT" \
    WORLD_PLANS_URL="$SERVER/v1/hub/plans?household=$SPIRA_HOUSEHOLD_ID" WORLD_PLANS_TOKEN="$SPIRA_HUB_KEY" \
    WORLD_HUB_STATE_URL="http://127.0.0.1:$HUB_PORT/state" \
    exec "$PEERS_VENV/bin/uvicorn" spira_simulator.api:app --host 127.0.0.1 --port "$SIM_PORT"
}
hub() {
  SPIRA_SERVER_URL="$SERVER" SPIRA_HOUSEHOLD="$SPIRA_HOUSEHOLD_ID" SPIRA_HUB_KEY="$SPIRA_HUB_KEY" \
    SPIRA_DEMO_CLOCK_URL="$SERVER/v1/demo/clock" SPIRA_MQTT_PORT="$MQTT_PORT" PYTHONPATH=contracts/generated/python \
    exec "$PEERS_VENV/bin/python" -m hub.spira_hub --installation "$OUT/peers/installation.json" --db "$HUB_DB" \
    --port "$HUB_PORT"
}
shell() {
  DEMO_SERVER_URL="$SERVER" DEMO_APP_TOKEN="$SPIRA_APP_TOKEN" DEMO_HOUSEHOLD="$SPIRA_HOUSEHOLD_ID" \
    DEMO_HUB_URL="http://127.0.0.1:$HUB_PORT" DEMO_SIMULATOR_URL="http://127.0.0.1:$SIM_PORT" \
    DEMO_OPERATOR_TOKEN="$OPERATOR_TOKEN" DEMO_NUMBERS_PATH="$ROOT/server/config/numbers.yaml" \
    exec "$PEERS_VENV/bin/uvicorn" demo:app --app-dir demo-shell --host 127.0.0.1 --port "$SHELL_PORT"
}

if busy "$MQTT_PORT"; then
  say "MQTT 는 이미 켜져 있어요 (포트 $MQTT_PORT)"
else
  run mqtt mqtt
fi
run server server
for _ in $(seq 1 60); do busy "$SERVER_PORT" && break; sleep 1; done
busy "$SERVER_PORT" || die "서버가 뜨지 않았어요: server/out/live/server.log 를 보세요"
run sim sim
run hub hub
run shell shell

for _ in $(seq 1 30); do busy "$SHELL_PORT" && break; sleep 1; done
say "준비됐어요: http://127.0.0.1:$SHELL_PORT/demo   (끄기: Ctrl+C, 로그: server/out/live/)"
wait
