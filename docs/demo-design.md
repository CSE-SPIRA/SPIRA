# Demo design decisions

**ACTIVE** · Presentation design for the App's main lifecycle, the Simulator's house, and the optional demo shell (`/demo`). Each part defines its behaviour in its specification and README. The integration contracts govern the Server interfaces.

## Stage

1. **The phone stays large; the Server's stages run beside it; the house takes that place at stage 6.** The audience follows one product (the phone) while the Server's reasoning is shown next to it: 추출 → 맥락 → 의도 → 할 일 → 계획 → 집 → 기록. Agreed at the 11/24 team meeting.
2. **Live stages show a skeleton and fill it as Server data arrives.** The presenter advances through the live stages. Recording playback advances immediately using saved data.
3. **A stage the Server does not export stays empty.** It reads "서버가 아직 이 단계를 내보내지 않아요". Fixture data is never mixed into a real-Server run. "If stage 2 is blocked, it must really be blocked" (11/24).
4. **The house opens in a whole-house view.** Markers show where changes happened. Select a marker for a close-up and its callout. Select it again or advance to return to the whole house.

## House

5. **The house draws only what the World observed.** Device states, people, the package and guests come from World observations and Hub read-backs, not from the plan. Planned state is shown separately and marked as planned. The house is a witness, so it must not show what did not happen.
6. **Judgment data does not reach the Simulator.** The shell chooses decorations from its own closed lists; the Server's judgment never sets what the house looks like. This keeps "the judgment does not make the household's day" true.
7. **TV and fridge screens use templates, not generated images.** A text tagger picks a template, palette and motif from closed lists, using the card line's text. The fridge art is text-free, and the observed notice is laid over it. A screen appears only after the device read-back confirms it is on. Templates cost nothing per run and look the same in a recording. They are turned off for real-Server runs.
8. **The Home Hub sits on the TV console.** Its placement shows where the home adapter runs.

## Time

9. **The Server's times are kept; the presenter moves the clock.** Tasks run at their real scheduled times (12:30 cleaning, 13:30 safety, 14:00 oven, 17:50 end). The presenter presses 다음 시연 시각 to jump to the next moment. Moving the party closer to the share was rejected (11/24: "click and see each time come round").

## Video

10. **Every run is recorded.** The shell saves what arrived and when. `/demo?recording=<id>` uses the saved order of events and story times. The final video is cut from a recorded run.

## App

11. **The App centres on the main lifecycle.** The order sits above the execution-plan cards. The App shows preparation, execution, intervention, and the move to calendar memory. Reasoning stays on the Server stage screens.
12. **The App reads home data only from the Server.** Hub communication belongs to the Server. This applies to home inventory and onboarding as well as cards.

## Shared

13. **One design source.** `design/` holds the tokens, vocabulary and font (IBM Plex Sans KR). `design/build.py` generates the App, Hub and Simulator files, and `--check` keeps them in step.
14. **The shell is optional.** Nothing in `app/`, `hub/` or `simulator/` depends on `demo-shell/`. Each part runs and is tested without it.
15. **The shell's phone shows the simplified App in step with the stages.** Sharing starts extraction, the order list appears with extracted items, and the plan stage brings the card notification. Opening the card takes the right side to the house while the phone tracks execution. The final memory opens from a calendar dot.
