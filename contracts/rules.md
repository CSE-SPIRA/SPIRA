# Common rules

Rules every part follows when it sends or reads the shapes in `schemas/`. (COM-02, COM-04, COM-15, HUB-01, HUB-04, HUB-15, HUB-16, APP-04, APP-05, APP-10)

## IDs (COM-04)

| ID | Format | Made by | Notes |
| --- | --- | --- | --- |
| household | `h_042` | server | |
| episode = plan | `ep_9031` | server | One order (all captures within 8 h). `plan_id` is the episode id |
| card | `nc_331` | server | One card = one preparation = one intent. At most 2 per episode |
| task | `t_{name}#{n}` | server | `n` is the order inside the episode; it never changes across plan versions. A re-judged task gets a new `n` |
| device | `{type}_{nn}`, plugs `plug_{purpose}` | hub | Nobody parses it. The server tells devices apart by `type` (+ plug `label`) |
| event | `ev_…` | hub | Globally unique; the same id when resent |
| result | `rs_…` | hub | Globally unique; the same id when resent |
| operation | `op_…` | hub | One dispatch; `running` and `completed` of one run share it |
| item | `it_…` | server | Item inside an episode |
| case | `syn_{batch}_{nnnn}` / `home_{household}_{episode}_{n}` | KB / server | `n` = card order in the episode |

## Time

- Every timestamp is ISO 8601 with an offset: `2026-10-17T14:00:00+09:00`. The household time zone is Asia/Seoul. A date alone is `YYYY-MM-DD`.
- Durations are `{n}m` or `{n}h` (`30m`, `2h`).
- The server fills absolute times; the hub waits with its wall clock (NTP). The simulator's virtual clock is only for standalone tests (COM-15).

## Values are run as they are (HUB-01)

- The server sends device ids, numbers, enum values and absolute times. The hub does not interpret or re-plan (no "pink", no "a bit warmer").
- Text values exist only for commands whose `value_schema` is `"text"` (`show_notice`).
- Every parameter in a command's `value_schema` is filled, inside its range or enum.
- Enum strings come from `enums.json` (or the generated code). Display text is written by the app or server separately.

## Plans and versions (HUB-03, HUB-04, HUB-12, HUB-15, HUB-16)

- The hub pulls `GET /v1/hub/plans` every 15 s, at once when an event response says `plans_changed: true`, and once right before running anything. The server never calls the hub.
- A plan version replaces the previous one. Ignore a `plan_version` equal to or lower than the one you hold.
- `tasks` = every live task. `cancelled` = every cancelled task so far; `restore: true` means it had started, so undo it.
- Line off, Stop and pause reach the hub only this way: a new version with `cancelled`, and `paused` in the pull response.
- Item tasks wait with `released: false`. After `package.brought_in` the server links the package to the latest waiting order and sends a version with `released: true` and `at`. Run only released tasks.
- After taking a new version, send `POST /v1/hub/plans/{plan_id}/ack`. Reject only a malformed task (unknown device, unsupported cmd, value out of range, schema), never because of the house state. Other tasks are still taken. The server shows a rejected line as `failed` and does not re-plan.
- Right before a run: if the pull fails, start nothing new and report `blocked: plan_unconfirmed`. Safety and restore of effects already running continue.
- Right before a run the hub also checks that the cmd is still delegated at the current devices revision; otherwise `blocked: not_delegated`.

## Execution results (HUB-08)

- One result per action (device). `completed` needs a fresh read-back; an ACK alone is not completion (`unverifiable`).
- A device "in use by a person" (`blocked: in_use_by_person`) means a job a person started is running (oven or cooktop cooking, cleaner cleaning). Lights and screens that are on are still run.
- At the end, restore only what SPIRA still owns. A property a person changed after SPIRA is not restored (`skipped_user_changed`).

## Events (HUB-07)

- Home events: `package.brought_in`, `guest_arrived`, `event_end` (source `hub`). Device events: `{device type}.{device event}` (source = device id).
- Every device event carries `payload.by`: `user` (a person, another app, a wall switch), `spira` (the hub ran it), `unknown`. The server never counts `unknown` as a person's change.
- `{type}.changed` also carries `property`, `from`, `to`.
- Send in time order; batching is allowed. Rejected events come back in `rejected`; fix and resend with the same id.

## Idempotency

| Key | Rule |
| --- | --- |
| `event_id` | Stored once; a resend is accepted and ignored |
| `result_id` | Stored once; response `duplicate: true` |
| order `source_id` | Same share source returns the same `episode_id` with 200, no new LLM call |
| card notification | The app shows one local notification per (`card_id`, `updated_at`) with `notify: true` |

## App polling and reactions (APP-04, APP-05, APP-10, APP-14)

- Cards: `GET /v1/households/{hid}/cards?since=` every 30 s; the next `since` is `server_time` of the last response. Results reach the app only through cards (no result API).
- `notify: true` only for a new card and when a held card found its time. Everything else is a silent update.
- `line_off` / `line_on`: one line. `line_on` only before the task starts (else 409 `line_started`). Switching off every line is not Stop.
- `stop`: the intent of that card was wrong. Cancels and undoes every preparation line of that card only. Per-item notices stay. After Stop, other reactions are ignored (200).
- `pause`: cancels tasks not started yet in every order, keeps running effects, stores new orders without judging.

## Clock and demo mode (COM-15)

`DEMO_MODE=1` on the server shortens starting values so the scenario fits a presentation. Calendar events are then entered as "now + n minutes".

| Value | Normal | DEMO_MODE |
| --- | --- | --- |
| Quiet time before judging captures | 10 min | 30 s |
| Cleaning before the schedule | 90 min | 3 min |
| Guest-arrival window opens before the schedule | 30 min | 1 min |
| Schedule end + fallback when `event_end` never comes | 3 h | 10 min |
| Fridge notice after the first door opening | 2 h | 2 min |

## Errors (COM-05)

Every 4xx / 5xx body is `{"code", "message", "details"?}` (`schemas/error.json`); codes in `enums.json` `error_code`.

## Secrets (COM-07)

No connection URLs or keys in this repository. The hub API key is created by `POST /v1/households`, passed once by the app to the hub's local setup route, and kept in the hub's local secret store (HUB-14).
