# SPIRA design

`tokens.json` defines the palette, radii, spacing, type scale, and shared
motion values. `vocabulary.json` defines Korean device and room names, App
icons, and short state labels. Short labels and App labels preserve wording
already used in those contexts.

[`fonts/`](fonts) is the shared `spira_fonts` package with the IBM Plex Sans KR
OpenType files and licence. The App uses that package directly. The Simulator
serves generated WOFF2 copies and the licence from its `ui/house/fonts/` directory.

From the repository root, install the font build dependencies in your Python
environment with `python3 -m pip install -r design/requirements.txt`. Run
`python3 design/build.py` after editing the tokens, vocabulary, or fonts. Commit
the generated files alongside the source. Run `python3 design/build.py --check`
to check them without writing. Each part's test suite also checks its own outputs.

## Writing

- Use polite conversational Korean (해요체) in person-facing copy. Use
  familiar words for devices and their behavior. Keep internal IDs such as
  `h_042` and `ep_9031`, and terms like 부류, 가상, and substrate in operator
  diagnostics.
- Show moments in the household time zone (Asia/Seoul) as weekday and 24-hour
  time, for example `토 11:16`. Include the date when it matters, such as
  a card header with `11월 21일 (토) 11:19`. Relative triggers can use words
  such as `손님이 오면`. The Simulator's demo story clock uses the same
  notation for its projected times.
- Wrap Korean at word boundaries with `word-break: keep-all` on the web and
  `KoreanText` in Flutter. Honor the system reduced-motion preference on
  every surface.
