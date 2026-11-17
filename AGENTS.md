# AGENTS.md

Rules for AI coding agents working in this repository. Humans: see `README.md` and `.github/CONTRIBUTING.md`.

## Read first

1. `docs/architecture.md`: how the parts connect.
2. `contracts/README.md` and `contracts/rules.md`: values shared between parts.
3. The `README.md` and `spec.md` of the folder you are changing. `spec.md` is the source of truth for that part.

## Hard rules

- **Stay in your folder.** Change only the part folder the task is about. Another part's folder needs its owner (`.github/CODEOWNERS`).
- **Never edit `contracts/` together with code.** Contract changes are their own PR. Never edit `contracts/generated/` by hand; run `bash contracts/codegen/generate.sh`.
- **Use the generated models** (`spira_contracts`) for request and response bodies. Do not redefine contract shapes.
- **Values are English codes** (enums in `contracts/enums.json`). Korean only in user-facing text and prompts.
- **No secrets in git.** Connection URLs, passwords and API keys go in a local `.env`; `.env.example` lists names only.
- **Server: the LLM never makes times or runs devices.** Times come from `find_time`; numbers come from `server/config/numbers.yaml`, not from code literals.
- Do not change migration `0001` columns of `cases`; add a new migration instead.

## Commands

| Where | Check |
| --- | --- |
| `contracts/` | `pip install -r contracts/check/requirements.txt && python contracts/check/check.py` |
| `server/` | `pip install -e ../contracts/generated/python -e ".[dev]" && pytest` (LLM `mock`) |
| `hub/`, `app/`, `simulator/` | See the folder's `README.md` |

## Pull requests

- Branch `<part>/<topic>` from `develop`; PR into `develop`; squash merge.
- CI `contracts` must pass.
- Code, comments and commit messages in English.
