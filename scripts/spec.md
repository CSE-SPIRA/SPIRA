# Demo launcher specification

**Status:** ACTIVE. This file defines how `demo-up` starts a local fixture or
connects the App and Home to an existing Server.

**DL-R1.** In Server mode the launcher MUST use the demo household from
`server/out/demo.env`. Missing configuration MUST name `SPIRA_HOUSEHOLD_ID`,
`SPIRA_HUB_KEY` and `SPIRA_APP_TOKEN` in that order and explain how to generate
and source the file. The launcher MUST leave calendar submission to the App.
Startup MUST explain that the birthday runs in real minutes under the
Server's `DEMO_MODE`.

**DL-R2.** With `--phone`, the launcher MUST build and cache a debug APK
using the web App's Dart defines for the same run. The API URL MUST be the
loopback port forwarded by ADB. `--first-run` MUST select the onboarding
variant. With one ready ADB device, the launcher MUST reverse the port,
install the APK, and print the App data reset command. Otherwise it MUST
print the APK path and the commands for manual installation and reset.

## Acceptance

| ID | Action | Expected result | Requirement |
| --- | --- | --- | --- |
| DL-AT1 | Launch with each required Server value omitted, then with the sourced demo environment | The setup guide lists the expected values. Startup uses the demo household and sends no calendar | DL-R1 |
| DL-AT2 | Launch with one ready device or without a ready device | The APK is installed through ADB or its path and commands are printed. Both cases show how to reset App data | DL-R2 |
| DL-AT3 | Repeat a phone build, then switch to first-run | Identical inputs reuse the APK. The first-run defines select a separate build | DL-R2 |
