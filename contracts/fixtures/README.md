# Fixtures

Example payloads, one folder per scenario. Use them as test inputs and expected outputs in every part; the simulator script uses the same values (HUB-17). Each folder's `manifest.json` says which schema each file follows, and `check/check.py` validates them.

| Folder | Scenario | Shows |
| --- | --- | --- |
| [`ep_9031/`](ep_9031) | Kid birthday, h_042, 7 devices ([timeline](ep_9031/timeline.md)) | The full flow: card → line off → package → guests → person starts the oven → person changes the light → end and restore → memory |
| [`ep_9120/`](ep_9120) | Family gathering, h_051, 4 devices incl. type `speaker` | Another household and an unknown device type; lines held without a calendar, time found when the calendar arrives |
| [`ep_9150/`](ep_9150) | Plain groceries, h_042 | No intent, no card; only a per-item notice (most orders) |

Not here: screenshots and LLM outputs (server-internal, see `server/spec.md`).
