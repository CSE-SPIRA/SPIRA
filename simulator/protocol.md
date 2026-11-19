# Hub ↔ Simulator device protocol

This document is the normative device protocol for both `hub/` and
`simulator/`. `MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative. It defines
the device boundary only; it does not replace the C-1–C-4 Server contracts in
[`contracts/`](../contracts/README.md). The Hub owns conversion between this
protocol and generated Server-contract models.

Protocol version: `spira.device.v1`.

**Placement.** Team rules put values shared between parts in `contracts/`. This
protocol is read only by `hub/` and `simulator/`, so it lives here and the Hub
references it. If the Server or the App ever reads it, it moves to `contracts/`
(agreed with the Server, 2026-11-19).

## 1. Boundary and actor rule

The boundary has three layers:

1. **Control:** Hub discovery, read, and command requests plus Simulator replies.
2. **Signal:** state reports, raw device/sensor events, and availability.
3. **Truth-side:** World actor truth and judge state, internal to the Simulator.

Only control and signal messages use the Hub device connection. Every
Hub-readable message and diagnostic MUST omit `actor`, `ground_truth_actor`,
`provenance`, and Server-contract `by`. The truth journal and judge MUST NOT be
reachable with the Hub device connector's access.

The protocol conveys command correlation and local-operation detection, not
identity:

- `operation_id` identifies an effect caused by one Hub command.
- `local_operation` says that a Class A device detected operation at the device;
  it never identifies the person.
- `local_operation_reporting` advertises whether the device can produce that
  signal.

The Hub, not the device, derives Server-contract `by`.

## 2. MQTT channels

Let `P` be the configured isolated MQTT prefix.

| Topic | Direction | Payload |
| --- | --- | --- |
| `P/discover` | Hub → Simulator | discovery request |
| `P/read` | Hub → Simulator | fresh read request for one target |
| `P/command` | Hub → Simulator | command with operation identity and optional expected revisions |
| `P/reply/{hub_id}/{request_id}` | Simulator → Hub | discovery/read response or command acknowledgement |
| `P/events` | Simulator → Hub | `state_report` or `event_signal` |
| `P/availability` | Simulator → Hub | retained World process availability |

Requests and events MUST use QoS 1 and `retained=false`.
`P/availability` MUST use QoS 1 and `retained=true`. The device protocol has no
demo-clock control; product and demo operation use wall time and Server
`DEMO_MODE` under COM-15.

Requests use unique `request_id`; commands additionally use unique
`operation_id`; pushed signals use unique `signal_id`. Receivers MUST tolerate
QoS duplicates. Reconnection MUST mark an observation gap and MUST NOT claim that
missing events were reconstructed.

## 3. Common message rules

- JSON messages MUST contain `"schema": "spira.device.v1"`.
- Times MUST be ISO 8601 with an offset, using the same wall clock as the rest of
  the demo.
- `target` is the native target bound by the Hub. It is not assumed to equal the
  logical device ID sent to the Server.
- `world_revision` is a monotonic transition order. Property `revisions` are
  opaque conditional-write witnesses; neither substitutes for the other.
- A response MUST repeat the request's `request_id`. A command acknowledgement
  MUST also repeat its `operation_id`.

## 4. Discovery

Request:

```json
{
  "schema": "spira.device.v1",
  "request_id": "rq_001",
  "reply_to": "spira/g0/reply/hub_01/rq_001"
}
```

Response:

```json
{
  "schema": "spira.device.v1",
  "request_id": "rq_001",
  "data": {
    "devices": [
      {
        "target": "mqtt:oven_01",
        "device_type": "oven",
        "room": "kitchen",
        "available": true,
        "substrate": "virtual",
        "local_operation_reporting": true,
        "assumption": "Virtual LG local-operation reporting",
        "capabilities": {
          "commands": ["set_cook_standby"],
          "properties": ["preset", "in_use"]
        }
      }
    ]
  }
}
```

Every discovered device MUST carry `local_operation_reporting`:

| Value | Class | Meaning |
| --- | --- | --- |
| `true` | A | Device reports detected local operation; for gate G0 this is an explicit assumption and `assumption` MUST describe it |
| `false` | B | Device never asserts `local_operation=true`; `assumption` MAY be absent |

Virtual LG appliances and the virtual light panel are Class A under the displayed
assumption. The physical Tapo light is Class B. Matter virtual devices are Class
B for the tested matter.js 0.18 profile: an unmatched attribute report is not
proof of local human operation.

Discovery reports capability only. It MUST NOT grant Hub delegation or physical
qualification.

## 5. Command and acknowledgement

The Hub sends a complete desired property set and MAY include opaque expected
property revisions for a conditional write:

```json
{
  "schema": "spira.device.v1",
  "request_id": "rq_017",
  "reply_to": "spira/g0/reply/hub_01/rq_017",
  "operation_id": "op_017",
  "target": "mqtt:oven_01",
  "desired": {"preset": {"temp_c": 180, "minutes": 20}},
  "expected": {"preset": "pr_008"}
}
```

The Simulator MUST validate every target, property, value, availability state,
and supplied expected witness before applying any part of a command. The same
`operation_id` MUST return the first durable acknowledgement and MUST NOT produce
a second effect.

Acknowledgement:

```json
{
  "schema": "spira.device.v1",
  "request_id": "rq_017",
  "data": {
    "status": "ACCEPTED",
    "operation_id": "op_017",
    "job_id": null
  }
}
```

`status` is one of `ACCEPTED`, `REJECTED`, `UNAVAILABLE`, `UNSUPPORTED`,
`CONFLICT`, `PROHIBITED`, or `UNKNOWN`. `job_id` is non-null only for a
long-running job. An acknowledgement MUST NOT include state, actor information,
or `by`. `ACCEPTED` is not proof of an effect.

## 6. Read and state report

Read request:

```json
{
  "schema": "spira.device.v1",
  "request_id": "rq_018",
  "reply_to": "spira/g0/reply/hub_01/rq_018",
  "target": "mqtt:oven_01"
}
```

Read replies and pushed state changes use the same `state_report` shape. A pushed
change appears directly on `P/events`; a read reply places the report in `data`.

```json
{
  "schema": "spira.device.v1",
  "kind": "state_report",
  "signal_id": "sig_104",
  "target": "mqtt:oven_01",
  "event_type": "oven.started",
  "world_revision": 104,
  "values": {
    "preset": {"temp_c": 180, "minutes": 20},
    "in_use": true
  },
  "revisions": {"preset": "pr_009", "in_use": "pr_005"},
  "occurred_at": "2026-10-17T14:20:00+09:00",
  "observed_at": "2026-10-17T14:20:00+09:00",
  "available": true,
  "substrate": "virtual",
  "job_id": null,
  "operation_id": null,
  "local_operation": true
}
```

Rules:

1. A report MUST contain `operation_id`, with a string or `null`, and
   `local_operation`, with a boolean.
2. `operation_id` MUST be non-null only on the report for an effect caused by
   that exact Hub command. An unrelated transition, later read, device-self
   transition, or external change MUST use `null`. IDs MUST NOT be guessed from
   matching values.
3. `local_operation=true` is valid only for a Class A device transition detected
   at the device. Resident, child, or guest operation may produce it; external
   automation, device-self transition, and Hub command effects MUST use `false`.
4. Class B devices MUST always report `local_operation=false`.
5. `operation_id` and `local_operation=true` MUST NOT occur together.
6. `event_type` and `occurred_at` identify the changed-device fact. A pure read
   MAY use `event_type: null`; `observed_at` still records the fresh read time.
7. Equal-value independent writes MUST replace the affected property witness.
8. Missing, stale, and unavailable reads MUST be explicit; the Hub MUST NOT use
   an old matching value as fresh effect evidence.

For a long-running job, `job_id` remains stable across running and completed
reports. A completion report MUST refer to the same current job and MUST use
`operation_id: null` when completion is a later device-self transition.

## 7. Raw event signal

Sensor and home-observation facts that are not state reports use `event_signal`:

```json
{
  "schema": "spira.device.v1",
  "kind": "event_signal",
  "signal_id": "sig_201",
  "target": "mqtt:sim_camera",
  "event_type": "camera.package_removed",
  "occurred_at": "2026-10-17T13:55:00+09:00",
  "payload": {"removed_count": 1, "remaining_count": 0}
}
```

An `event_signal` MUST describe only the observed fact and MUST NOT carry actor
truth or `by`. The Hub applies plan/source/window rules to raw camera, doorbell,
door-lock, and device signals before it creates contract events such as
`package.brought_in`, `guest_arrived`, or `event_end`. This protocol defines no
fixed window and no protection-release policy.

## 8. Availability

World process availability is a retained last-will message:

```json
{
  "schema": "spira.device.v1",
  "status": "online",
  "world_epoch": "we_07"
}
```

`status` is `online` or `offline`. Per-device unavailability appears in discovery
and state reports. Receiving `online` MUST NOT close a prior event gap or make an
old read fresh.

## 9. Hub attribution semantics

For each device event that becomes C-3, the Hub derives `payload.by` in this
order:

1. A valid `local_operation=true` report from a device that discovered
   `local_operation_reporting=true` becomes `user`.
2. Otherwise, a non-null `operation_id` that matches the Hub's recorded command
   for the same target becomes `spira`.
3. Otherwise the result is `unknown`.

Door, camera, presence, proximity, schedule, and value similarity MUST NOT be
used to upgrade attribution. A Class B person's change, external automation,
device-self change, ambiguous report, or gap therefore remains `unknown`.

Attribution and protection are separate. When a transition is not the confirmed
effect of the Hub's operation, the Hub relinquishes affected-property ownership
whether `by` is `user` or `unknown`; `unknown` is not a person's learning signal.

## 10. Simulator-internal truth and judge

Truth-side data is not part of the MQTT protocol. The Simulator privately keeps
the actual actor, device, event type, occurrence time, and before/after state for
each relevant transition. Its public signal projection strips the actor and adds
only the fields allowed above.

The judge reads the C-3 record that `hub/tests/fixture_server` actually received.
It MUST NOT accept a Hub audit projection as a substitute. It joins on logical
device ID (taken from the Simulator household configuration, which uses the
same logical IDs as the Hub registry), event type, and occurrence time; the fixture Server's C-3 `source`,
`type`, and `at` are the received side of that join.

The operator-side result vocabulary is:

| Result | Meaning |
| --- | --- |
| `match` | Received `by` matches the signal limit for resident, SPIRA, external automation, or device-self truth |
| `person-reported-unknown` | A person acted but the received event says `unknown`, as expected for a Class B or otherwise unreported local operation |
| `non-person-reported-user` | SPIRA, external automation, or a device-self transition was reported as `user` |
| `person-not-decision-maker` | The actor was a child or guest, although the Hub can at most report a person at the device |

The judge MUST expose truth and results only on the operator side. It MUST NOT
feed its verdict to Hub execution, C-3 creation, or Server memory.

## 11. Default `h_042` profile

In the [default profile](spira_simulator/profiles/ep_9031.json), the Hub MUST bind
each logical device to `mqtt:<logical_id>` and use these mappings when sending
fixture commands as desired properties on `P/command`. Use the fresh read's
property witnesses for conditional writes.

| Logical device | Fixture command | Desired properties |
| --- | --- | --- |
| `cleaner_01` | `clean` | `clean: {room}` starts a job. `clean: null` with the current `clean` witness stops a running job. |
| `light_01` | `color`, `color_temp` | `color: {hue, saturation, brightness}` or `color: {kelvin}`. Both modes share the same witness. |
| `display_01` | `play_mood`, `off` | `play_mood: {scene}` or `play_mood: null`. |
| `cooktop_01` | `child_lock` | `child_lock: true`. |
| `oven_01` | `set_cook_standby` | `preset: {temp_c, minutes}`. Actual cooking starts with a local device action. |
| `fridge_01` | `show_notice` | `show_notice: <text>`. The display slot holds the latest notice. Opening the door emits `fridge.door_opened`. |
| `plug_kettle` | `off` | `power: false`. |
| `air_purifier_01` | `mode`, `wind_strength` | `mode` accepts `CLEAN`, `AUTO`, `CIRCULATOR`, `DUAL_CLEAN`. `wind_strength` accepts `LOW`, `MID`, `HIGH`, `AUTO`, `POWER`. |
| `dishwasher_01` | `set_course_standby`, `delayed_start` | `course` accepts the [fixture's course enum](../contracts/fixtures/ep_9031/devices.json). `delay_hours` accepts relative hours from 1 to 12. A saved `null` clears the corresponding setting on restore. |
| `washer_01` | `set_course_standby` | `course` accepts `NORMAL` or `DELICATES`. A saved `null` clears the setting on restore. |
| `plug_iron` | `off` | `power: false`. |
| `plug_router` | None | `power` can be read by the Hub. A Hub write to it returns `PROHIBITED`. The household can operate the plug locally or through the appliance app. |

The purifier, dishwasher, washer, and plugs emit `<device_type>.changed` on
property changes. The purifier uses device type `purifier`. The purifier,
dishwasher, and washer use the Class A panel assumption. The plugs are Class B.
Dishwasher and washer course settings are standby presets. The dishwasher
delay stores a relative-hour setting. Both machines prohibit Hub start and
have no automatic job transitions in these profiles.

The default profile's operator controls MUST emit these raw observations as
`event_signal` messages.

| Control | Native target and event |
| --- | --- |
| Bring package inside | `mqtt:sim_camera` · `camera.package_removed` with `removed_count: 1`, `remaining_count: 0` |
| Guests arrive | `mqtt:sim_doorbell` · `doorbell.pressed`, `mqtt:sim_door_lock` · `door_lock.opened`, and `mqtt:sim_presence` · `presence.room_occupied` |
| Event ends | `mqtt:sim_presence` · `presence.room_empty` |

## 12. `h_051` profile

In the [family-gathering profile](spira_simulator/profiles/ep_9120.json), bind
each logical device to `mqtt:<logical_id>`. The cleaner, oven, fridge, and
purifier use the mappings above. The cleaner also accepts `침실` as a room
value. The home controls emit the same raw observations as in `h_042`.

| Logical device | Fixture command | Desired properties |
| --- | --- | --- |
| `speaker_01` | `play`, `stop` | `play: {playlist, volume}` or `play: null`. Both use the same property witness. |
| `air_purifier_01` | `mode`, `wind_strength` | `mode: <mode>` or `wind_strength: <strength>`, with the same enums and `purifier.changed` event as `h_042`. |

Both fields are required for playback. `playlist` is `calm`, `party`, or
`family`. `volume` is a number from 0 through 100. The virtual speaker emits
`speaker.changed` for playback changes and reports
`local_operation_reporting: false`.
