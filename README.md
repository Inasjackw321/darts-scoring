# AI Vision Dart Scorer

Automatic darts scoring: a phone films the board, a Python server on your
Windows desktop works out where each dart landed, and the score updates live.

The scoring itself is **not** done by a vision model. It is OpenCV plus
geometry:

| Step | How | Cost |
| --- | --- | --- |
| Find the dart tip in the frame | Frame diff vs. the clear board, contour filtering, principal-axis tip pick | ~10 ms |
| Pixel → board millimetres | Homography from a one-time calibration | pure maths |
| Millimetres → `T20` | Polar geometry against standard board dimensions | pure maths |
| "Do you also see 3 darts?" | Ollama (`llama3.2-vision`), on request only | seconds |

The vision model is a **second opinion**, never the scorer. Vision models are
unreliable at precise spatial localisation, which is the entire problem here —
so the model is asked only how many darts it can see, and disagreements are
surfaced as a warning rather than silently overriding the score.

---

## Quick start (Windows desktop)

1. Clone the repo and double-click **`start.bat`**. It creates the virtual
   environment, installs dependencies, checks Ollama, prints your LAN IP and
   starts the server.
2. **Windows Firewall will prompt on the first run.** Tick *Private networks*
   and allow it, or your phone cannot reach the server.
3. On your phone (same Wi-Fi), open the address `start.bat` printed, e.g.
   `https://192.168.1.20:8000`. Your phone will warn that the certificate is
   untrusted — it is your own PC, self-signing. Tap *Advanced → Proceed*, once
   per device.
4. In the browser menu choose **Add to Home Screen** for a tap-to-launch icon.

**Why HTTPS?** Browsers only expose the camera in a "secure context" — HTTPS or
localhost. Over plain `http://192.168.x.x` the camera API is not merely blocked,
it is absent, so the app cannot start at all. `start.bat` therefore generates a
self-signed certificate for your LAN address (`data/lan-cert.pem`) and serves
over HTTPS. It regenerates automatically if your router hands out a new IP.

Ollama is optional. Without it, everything except the *Verify (AI)* button
works. With it:

```
ollama pull llama3.2-vision
```

## Two screens, one game

There is only ever **one game**. It lives on the desktop server; every browser
window is a view of it. What differs is the role each device plays:

- **The phone is the camera.** Mounted, facing the board, camera running. The
  first device to send a frame claims the camera role.
- **Any other screen is a scoreboard.** Its *Start camera* button greys out to
  "Camera on another device", and in place of its own (empty) video it shows
  the phone's live view — annotated with the calibrated board outline and a red
  circle on each detected dart tip. A desktop monitor makes a far better
  scoreboard than a phone propped across the room.

That live view is the fastest way to diagnose a misread: if the outline does
not sit on the outer wire, recalibrate; if the circles are on the flights
rather than the points, the camera is behind the board rather than in front.

The camera role is released after 15 seconds of silence, so if the phone dies
mid-game another device can simply start its camera and take over.

## Using it

**Calibrate once** (and again if the camera is bumped):

1. Mount the phone so the whole board is in frame, with no darts in it.
2. Open the **Calibrate** tab → *Freeze frame*.
3. Tap the four listed points in order. Each is where a number's centre wire
   crosses the **outside** of the double ring: top of the **20**, right of the
   **6**, bottom of the **3**, left of the **11**.
4. *Save calibration.* A green outline appears — it should sit on the outer
   wire. If it is skewed, tap *Clear points* and redo it.

Calibration persists in `data/calibration.json` until the camera moves.

**Play:**

- **Start camera** — the first frame is stored as the clear-board reference.
- Throw. Motion detection on the phone fires a capture, the server scores it,
  the dart appears on the scoreboard and the board diagram.
- **Pull your darts out, then tap Next turn** — in that order. Next turn banks
  the turn and re-takes the clear-board reference from what the camera can see
  at that moment, so the board must already be empty when you tap it.
- **Tap any dart** in the turn to correct it. **Undo dart** removes the last
  one. Bounce-outs and darts the camera could not see go in with **Add
  manually** — expect to need this occasionally; no hybrid pipeline is perfect.
- **Verify (AI)** asks the vision model to count darts and warns if it
  disagrees with OpenCV.

## Configuration

The phone stores the server address and its own settings in `localStorage`
(Settings tab): game mode, players, motion threshold, cooldown.

The server reads environment variables — no code edits needed:

| Variable | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `llama3.2-vision` | Swap for e.g. `qwen3-vl:8b` |
| `DARTS_DIFF_THRESHOLD` | `28` | Pixel difference that counts as changed |
| `DARTS_MIN_CONTOUR_AREA` | `120` | Smallest blob treated as a possible dart |
| `DARTS_MIN_ELONGATION` | `1.8` | How thin a blob must be to be a dart, not a hand |
| `DARTS_DUPLICATE_RADIUS_MM` | `12` | Tips this close count as the same dart |
| `DARTS_BOUNDARY_WARN_MM` | `3` | Flag scores landing this close to a wire |
| `DARTS_CAMERA_MOVED_FRACTION` | `0.25` | Frame change fraction that means "camera moved" |
| `DARTS_ALLOWED_ORIGINS` | GitHub Pages + localhost | Extra CORS origins |
| `DARTS_DEBUG_LOG` | `1` | Write frames/masks/results to `data/debug/` |
| `DARTS_DATA_DIR` | `./data` | Where calibration, certificate and logs live |

For scale on that last threshold: three darts change well under 1% of the
frame, a bumped camera changes 30%+.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /status` | Health, calibration state, Ollama availability, full game state |
| `POST /frame` | Score a frame; `set_reference: true` stores it as the clear board |
| `POST /calibrate` | Clicked points → homography (persisted) |
| `GET /calibration` | Stored calibration + board outline in pixels |
| `POST /verify` | Ask the vision model to count darts (advisory) |
| `POST /reset` | New game, clears the reference frame |
| `POST /turn/next` | Bank the turn, re-take the reference |
| `POST /dart`, `PATCH /dart`, `POST /dart/undo` | Manual add / correct / undo |
| `GET /preview.jpg` | Newest annotated camera frame, for scoreboard-only screens |
| `GET /board` | Board geometry constants |

Interactive docs at `https://<desktop>:8000/docs`.

## Frontend on GitHub Pages

`docs/` is a static site with no build step. Point Pages at the `docs/` folder
and it publishes to `https://<user>.github.io/darts-scoring/`.

**Use the desktop-served copy (`https://<desktop>:8000/`) to actually play.**
It is the same files, and being same-origin it avoids two problems the Pages
copy has: the browser blocks an HTTPS page from calling a LAN server whose
self-signed certificate it has not been shown, and CORS then has to be widened
for an origin that gains nothing. The Pages copy is useful for showing the UI
without the desktop running.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q          # 109 tests, no hardware needed
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

The test suite builds synthetic dartboard images and draws darts on them
(`tests/synthetic.py`), so detection, calibration, scoring and the whole API
round trip are testable without a camera or a board.

`tools/e2e_browser_check.py` goes further: it renders a fake camera video in
which darts appear over time, feeds it to Chromium, and drives the real
frontend through calibration and live scoring. It needs Playwright:

```bash
pip install playwright && playwright install chromium
python tools/e2e_browser_check.py            # or pass a base URL
```

Debug output for real misreads lands in `data/debug/` — the raw frame, the diff
mask, an annotated copy and the JSON result for every scored throw.

## Known limitations

- Darts that land behind another dart, or bounce out, need manual entry.
- Very heavy occlusion (a hand in front of the board) is flagged, not solved.
- The camera must not move after calibration; large frame changes raise a
  recalibration warning.
- One board, one game, in memory — restarting the server resets the game (but
  not the calibration).
- The LAN certificate is self-signed, so each phone shows a one-time warning.
  Service workers are refused on certificate-warning origins, so the app
  installs to the home screen but does not cache offline; it loads from the
  desktop each time, which it needs anyway to score.
