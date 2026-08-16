# Dart Scorer

Tap what you scored. It keeps 501, the legs, the checkouts and the stats.

A static web app — no server, no accounts, no build step. Open it, add it to your
home screen, and it works on the sofa, at the pub, or on a plane.

**Play it: https://inasjackw321.github.io/darts-scoring/**

---

## What it does

- **Tap-to-score keypad.** Single/Double/Treble, then the number. The
  multiplier resets after each dart, so a stray "treble" can't silently ruin a
  turn. 25, Bull and Miss have their own keys.
- **501, 301, 170 or count-up**, one to four players, any number of legs.
  Double-out on by default; double-in optional.
- **Proper x01 rules.** Going below zero, leaving 1, or hitting zero without a
  double all bust and revert the turn. Legs alternate who throws first.
- **Live checkout routes.** On 141 it says `T20 · T19 · D12`, and updates after
  every dart.
- **Fix mistakes.** *Undo* removes the last dart. Tapping any dart in the
  current turn re-enters it — the score, the leg and the bust all recompute.
- **Stats whenever you want them**, not only at the end: averages, first-9,
  180s and 140+ counts, checkout percentage, darts at a double, a chart of the
  leg, and a board showing where your darts actually went.
- **Keyboard shortcuts** if one's to hand: digits to score, `d`/`t` for
  double/treble, `b` bull, `m` miss, `Backspace` undo.
- **Nothing is lost.** The game saves after every dart and is restored when you
  come back, offline included.

## Stats, and what they honestly mean

Most are self-explanatory. Two are definitions rather than measurements, and the
app says so rather than implying more precision than it has:

- **Darts at a double** counts darts thrown while a *one-dart finish was
  available*. Whether you were truly aiming at that double is not something a
  score can reveal.
- **Where the darts went** shades each *region* of the board by how often it was
  hit. Tapping "T20" records the treble-20 bed, not a point inside it, so there
  is no dot-per-dart scatter — that would be invented precision. The two single
  areas of a number are one region for the same reason.

## Running it

It is a folder of static files. Any of these work:

```bash
# straight from the filesystem
open docs/index.html

# or over http, which is what a phone will use
cd docs && python3 -m http.server 8000
```

GitHub Pages serves `docs/` from the `main` branch — that is the whole
deployment.

## Development

```bash
node --test "tests-js/*.test.js"     # 37 tests, no dependencies
```

No package.json, no bundler, no framework. `docs/js/engine.js` is written so the
same file runs in the browser and under Node, which is what lets the rules be
tested directly.

| File | Job |
| --- | --- |
| `docs/js/engine.js` | The rules: darts, x01, busts, legs, checkout routes |
| `docs/js/stats.js` | Match statistics computed from the turn record |
| `docs/js/charts.js` | Progression line chart and board heatmap, as inline SVG |
| `docs/js/app.js` | Keypad, rendering, storage |

**The one design decision worth knowing:** a game is stored as the flat list of
darts thrown, and *everything* — whose turn it is, each score, legs won, whether
that dart busted — is derived by replaying it. Undo is a pop, correcting a dart
is a splice, and neither can leave the score out of step with the history. That
class of bug cannot occur.

## History: the camera version

This began as an automatic scorer — a phone camera, OpenCV dart detection, a
homography from pixels to board millimetres, and a vision model as a secondary
check. It worked; it scored real throws end to end. It was also a great deal of
apparatus around a problem a keypad solves in one tap, and it demanded a
calibration step, a TLS certificate, and a phone kept awake for a whole game.

That code isn't gone, just not here. It's in the history at commit `36dc92d`
and comes back with:

```bash
git checkout 36dc92d -- app tests tools start.bat requirements.txt
```
