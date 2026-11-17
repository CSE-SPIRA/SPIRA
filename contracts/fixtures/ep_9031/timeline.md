# ep_9031 timeline (HUB-17)

Kid birthday on Sat 2026-10-17 14:00–17:00. Household h_042, devices in `devices.json`. All times +09:00.

| Time | Who | What | File |
| --- | --- | --- | --- |
| Thu 10-15 21:00:08, 21:01:12 | app → server | Two screenshots shared (`POST /v1/orders`) | `episode.json` (items) |
| 21:11:40 | server | Judged after 10 quiet minutes; plan v1, card with 4 lines, notify | `plan.v1.json`, `card.v1.json` |
| 21:11:55 | hub → server | Pulls v1 and acks | `ack.v1.json` |
| Fri 10-16 08:40 | app → server | User switches off the child-safety line → plan v2 (`t_safe#2` cancelled, not started) | `reactions.json`, `plan.v2.json` |
| 18:05:10 | hub → server | `package.brought_in` → server releases the fridge notices → v3 | `events.json` ev_9101, `plan.v3.json`, `pull.json` |
| 18:05:20 | hub → server | Fridge shows the strawberry and whipping-cream notices | `executions.json` rs_5001–5002 |
| 18:07:44 | hub → server | Fridge door opened (notices end 2 h later) | ev_9102 |
| Sat 10-17 12:30 | hub | Living-room cleaning runs and completes 12:58 | ev_9201–9202, rs_5003–5004 |
| 13:52:31 | hub | `guest_arrived` → display `kids_party`, light hue 330 / sat 45 / bri 70 | ev_9303–9305, rs_5011–5012 |
| 14:00 | hub | Oven set to 170 °C / 20 min (standby) | rs_5020 |
| 14:20:02 | person | Starts the oven (confirmation signal) | ev_9350 |
| 15:10:05 | person | Changes the light to 2700 K → line `user_changed` | ev_9410 |
| 17:50:00 | hub | `event_end` → display restored, light kept (user changed) | ev_9500–9501, rs_5090, `card.final.json` |
| 17:50 | server | Observation closed: verdict match; feedback clean kept · safety off · mood changed · oven kept | `case_row.json`, `memory.json`, `rationale.json` |
