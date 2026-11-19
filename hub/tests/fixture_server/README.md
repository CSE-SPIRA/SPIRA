# Live scene controls

The contract fixture is non-inference test support. On `127.0.0.1`, start the
fixture with `DEMO_MODE=1` and `--scene-controls` to start with no published
episode. Existing fixed-date replay remains the default.

Use the App's Bearer placeholder for
`POST /_fixture/scene/next-order` and send `{"episode_id":"ep_9031"}` or
`{"episode_id":"ep_9150"}`. Both use `h_042`. The next successful new
`POST /v1/orders` activates the selected replay and replaces the current
snapshot in this single-active-episode fixture. An invalid, duplicate, or
paused upload leaves the selection queued. This is a fixture selector and the
image contents do not select an episode. The upload response is still the
contract acknowledgement.

The birthday schedule starts 65 seconds after activation and lasts 30 seconds.
The test control accepts integer `starts_in_seconds` and `duration_seconds`
in the range 1–3600. The fixture publishes absolute plan and card times using
the Server's COM-15 offsets. Cancel cleaning before starting the Hub if the
chosen start offset puts cleaning in the past. Live receipts use wall time.
The historical final card and memory transition belongs to fixed transcript
replay.

`GET /_fixture/scene/acks` uses the fixture Hub key. It returns the current
replay's received acknowledgements by version. `GET /_fixture/receipts`
retains its original shape.
