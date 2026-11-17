# State mapping

How the server turns plans, acks and hub results into card line states, and what each state leaves in this home's memory. The server computes it; the app only displays it. (C-7, APP-04, APP-11, HUB-08)

## Card line `state`

| state | When (what the server saw) | Memory (S7) |
| --- | --- | --- |
| `held` | Waiting for a time; not sent to the hub | — |
| `scheduled` | Sent, ack admitted, trigger not reached | — |
| `running` | A result `running` (e.g. cleaning) | — |
| `done` | Every action of the line `completed` | kept, ran |
| `partial` | Some `completed`, others `failed` / `unknown` / `unverifiable` / `blocked` | kept, ran |
| `failed` | No `completed` and some `failed`, or ack rejected the task | kept, not ran |
| `unknown` | No `completed`; only `unknown` / `unverifiable` | kept, not ran |
| `blocked` | No `completed`; `blocked` (reason in `note`, incl. `plan_unconfirmed`) | kept, not ran |
| `user_changed` | After the run, a `by: user` change on a device of the line | changed |
| `off` | Line switched off | off |
| `stopped` | Stop pressed | verdict stopped |
| `cancelled` | Cancelled before start by pause, order edit or calendar change | — |
| `dropped` | Held for 14 days without a time ("not prepared") | — |

- Priority when several apply: `off`, `stopped` > `user_changed` > `done`, `partial` > `running` > `failed`, `unknown`, `blocked` > `scheduled`.
- The verdict (`match` / `stopped` / `unconfirmed`) comes from confirmation signals (S7), not from these states.

## Card line `end_state` (after the end, from the restore result)

| end_state | When |
| --- | --- |
| `restored` | Every item `restored` or `not_needed` |
| `kept_user_change` | At least one `skipped_user_changed` |
| `restore_failed` | At least one `failed` / `unknown` |
| `none` | The task does not restore (`end.restore: false`) |

`null` until the line has ended.

## Card `summary`

- `done` = lines in `done`, `partial`, `user_changed`.
- `total` = lines minus `off`, `stopped`, `cancelled`.
- `waiting_for` = an event trigger not seen yet (e.g. `guest_arrived`), else `null`.
- Display: "2/4 준비 · 손님 도착을 기다리는 중".

## Episode `status` (APP-11)

| status | Meaning |
| --- | --- |
| `received` | Captures stored, waiting for the 10-minute quiet time |
| `reading` | Reading screenshots and judging |
| `read_failed` | No item could be read from any capture (one notification) |
| `judged` | Judged; no card (no intent or nothing to prepare). Item tasks may still exist |
| `notified` | A card exists |
| `held` | Intent found, every preparation line waits for a time |
| `closed` | Observation over, memory written |
| `paused_skip` | Arrived while paused; stored only |
