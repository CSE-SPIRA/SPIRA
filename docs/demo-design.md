# Demo design decisions

**ACTIVE** · The presentation decisions behind the live demo surfaces: the App's order story, the Simulator's house, and the optional demo shell (`/demo`). Each entry says what we chose and why. Behaviour is defined by each part's `spec.md` and README; this page explains the choices. It is not a contract and does not bind the Server.

## Stage

1. **The phone stays large; the Server's stages run beside it; the house takes that place at stage 6.** The audience follows one product (the phone) while the Server's reasoning is shown next to it: 추출 → 맥락 → 의도 → 할 일 → 계획 → 집 → 기록. Agreed at the 11/24 team meeting.
2. **Stages advance when the data arrives, never on a timer alone.** Each stage holds briefly so it can be read (items 2.2 s, evidence and intent 1.6 s). If the Server is slow, the strip says what it is waiting for and for how long.
3. **A stage the Server does not export stays empty.** It reads "서버가 아직 이 단계를 내보내지 않아요". Fixture data is never mixed into a real-Server run. "If stage 2 is blocked, it must really be blocked" (11/24).
4. **Text belongs to the stages; the house speaks in scenes.** In the house, only the moment's devices show a callout, which fades after about ten seconds. Devices that are off carry no label (11/24: "the house looked like only one thing changed").

## House

5. **The house draws only what the World observed.** Device states, people, the package and guests come from World observations and Hub read-backs, not from the plan. Planned state is shown separately and marked as planned. The house is a witness, so it must not show what did not happen.
6. **Judgment data does not reach the Simulator.** The shell chooses decorations from its own closed lists; the Server's judgment never sets what the house looks like. This keeps "the judgment does not make the household's day" true.
7. **TV and fridge screens use templates, not generated images.** A text tagger picks a template, palette and motif from closed lists, using the card line's text. The fridge art is text-free, and the observed notice is laid over it. A screen appears only after the device read-back confirms it is on. Templates cost nothing per run and look the same in a recording. They are turned off for real-Server runs.
8. **The house is recognisably an LG home.** An LG ThinQ hub stands on the TV console, in the place the Home Hub stands for (11/24).

## Time

9. **The Server's times are kept; the presenter moves the clock.** Tasks run at their real scheduled times (12:30 cleaning, 13:30 safety, 14:00 oven, 17:50 end). The presenter presses 다음 시연 시각 to jump to the next moment. Moving the party closer to the share was rejected (11/24: "click and see each time come round").

## Video

10. **Every run is recorded.** The shell saves what arrived and when, and `/demo?recording=<id>` replays it with the same timing. The final video is cut from a good real run instead of being staged by hand (11/24).

## App

11. **The order story replaces the long WHY page.** One scroll tells what was read, why, what the house did, and what was checked afterwards. Full evidence is one tap away.
12. **우리 집 reads the home's Hub, read-only.** This matches the phone ↔ Hub arrow agreed on 11/24, like a ThinQ app. Judgment data still comes only from the Server.

## Shared

13. **One design source.** `design/` holds the tokens, vocabulary and font (IBM Plex Sans KR). `design/build.py` generates the App, Hub and Simulator files, and `--check` keeps them in step.
14. **The shell is optional.** Nothing in `app/`, `hub/` or `simulator/` depends on `demo-shell/`. Each part runs and is tested without it.
