# Generated models

Do not edit. Made from `../schemas/` and `../enums.json` by `../codegen/generate.sh`; CI fails if they are out of date.

| Folder | For | Use |
| --- | --- | --- |
| `python/spira_contracts/` | server, hub (pydantic v2) | `pip install -e contracts/generated/python` → `from spira_contracts.plan import Plan`, `from spira_contracts.common import Way` |
| `python/spira_contracts/validate.py` | tests, edges | `validate(payload, "plan.json")` checks rules models do not express |
| `dart/spira_contracts.dart` | app | copy or import; `Card.fromJson(...)`, `Plan.fromJson(...)` |
