# Fixture Server specification

**Status:** ACTIVE. This file defines the live fixture replay. The Hub's
[integration requirements](../../spec.md#h10-contract-fixture-server-test-support-only)
and the Server's [App read views](../../../server/spec.md#122-route-behavior)
define the surrounding behavior and contract.

**FX-R1.** A live order MUST be readable immediately after acceptance. The
episode MUST publish item counts and items at S1. Rationale MUST answer
`404 not_found` before S2, then expose recorded evidence at S2 and recorded
intents and the no-intent reason, when applicable, at S3. The episode MUST
stay in `reading` while judgment is in progress. The public reads MUST have
empty task lists, no card IDs and no observations before S5. S5 MUST publish
the episode's item tasks, rationale tasks, card links, cards and plans
together. A scene without a recorded rationale MUST keep returning 404 for
that read.

**FX-R2.** The default live replay MUST use fixed, sequential stage gaps on
the fixture's story clock. Rehearsal controls MUST remain available to set
the pace, hold or release a stage, and run all stages with zero delay. Static
replays MUST continue to serve their committed snapshots.

## Acceptance

| ID | Action | Expected result | Requirement |
| --- | --- | --- | --- |
| FX-AT1 | Share a birthday or groceries order and read both views through S5 | The episode exists immediately. Items appear before rationale, evidence before intents, and task and card data at S5 | FX-R1 |
| FX-AT2 | Set every gap to zero and share again | All recorded judgment fields are present on the first read | FX-R2 |
