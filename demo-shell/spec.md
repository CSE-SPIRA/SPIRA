# Demo shell specification

**ACTIVE** · This file defines the presentation shell's behaviour. The
[App specification](../app/spec.md) defines the embedded App and the
[integration contracts](../contracts/) define Server payloads.

## Phone and presenter flow

- The phone frame MUST embed the real App web build at phone size when
  `GET /demo/api/config` supplies `app_url`. Without a URL, the frame MUST show
  `앱 미리보기를 켜 주세요`.
- The launcher MUST build the App with `flutter build web` by default and reuse
  a complete cached build for unchanged App sources and build settings.
  `--app-web DIR` MUST serve a supplied build, and `--no-app` MUST skip the App.
  The launcher MUST start no browser.
- The App preview proxy and the shell MUST use the same Server peer in both
  fixture and existing-Server runs. The App owns order submission and display,
  cards, reactions and calendar memory. Presenter cues MUST leave App
  navigation and lifecycle to the App.
- The presenter MUST be able to choose 집까지 or 계획까지 for the run.
  Each accepted press of 공유 MUST submit the selected sample once through
  `POST /v1/orders`. An order submitted in the App MUST be eligible for the
  shell to pick up through the Server's episode feed.

## Server stages, house and record

- The right side MUST show the Server's persisted results for extraction,
  context, intent, tasks and plan. Live stages MUST show a skeleton while
  data is pending and advance on presenter input. An unavailable export MUST
  leave its stage empty with a notice.
- A house run MUST offer 집으로 after the Server has supplied a card and the
  Hub has received the active episode's plan at or after that episode's share
  time. A plan run MUST end at 계획.
- The house MUST show observed World values and verified device read-backs.
  기록 MUST end on the house record, using the Server's exported verdict and
  line feedback when available. Missing verdicts MUST remain visibly pending
  or unavailable.
- Presenter presses and recorded playback presses MUST act without a fixed
  dwell. Live readiness depends on data and observations. Recorded stages
  and house moments use the saved run.

## Acceptance

| Check | Expected behaviour |
| --- | --- |
| Launch the fixture stack, then launch it again with the same App | The phone embeds the preview with the running fixture as its peer. The second launch reuses the build. |
| Launch with an existing Server | The shell and App preview use that Server. Missing exports stay empty. |
| Launch with `--no-app` or `--app-web DIR` | The first shows the placeholder. The second embeds the supplied build. Neither builds the App. |
| Press 공유 once, or submit an order from the App | The shell follows the Server episode. A presenter press sends one order request. |
| Reach 계획 with a missing card or Hub receipt | 집으로 is unavailable until both arrive for this episode. |
| Play the house and press 기록 | The right side opens the house record. App navigation stays under the audience's control. |
| Press next during recording playback | The next saved stage or moment appears immediately. |
