# Simulator

Owner: Yejoon Kim

Virtual household with independent device state (MQTT) and a 2D viewer. Generates events such as `package.brought_in`, `guest_arrived`, `event_end`.
See [`spec.md`](spec.md) for the complete target.

The current walking skeleton owns an independent SQLite world with one virtual
light, opaque property witnesses, an ordered transition journal, a bounded
operator route, and a read-only viewer. It deliberately does not implement MQTT,
Hub integration, scenario replay, or physical-device equivalence yet.

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
WORLD_DB=.local/world.db WORLD_OPERATOR=1 \
  .venv/bin/uvicorn spira_simulator.api:app --port 8730
```
