"""End-to-end check of the real frontend, with no camera and no dartboard.

Renders a fake webcam video in which darts appear in the board over time, hands
it to Chromium as a capture device, and drives the actual UI: calibration by
clicking reference points, then the live motion-triggered scoring loop.

    pip install playwright && playwright install chromium
    python -m uvicorn app.main:app --port 8011 &
    python tools/e2e_browser_check.py

Requires: playwright, and a server already running (default http://127.0.0.1:8011).
"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.request
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import board  # noqa: E402
from tests import synthetic  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
WORK = Path(tempfile.mkdtemp(prefix="darts-e2e-"))


def write_y4m(path: Path, frames, fps: int = 15) -> Path:
    """Chromium's fake capture device reads raw Y4M."""
    with open(path, "wb") as handle:
        handle.write(f"YUV4MPEG2 W{synthetic.WIDTH} H{synthetic.HEIGHT} F{fps}:1 Ip A1:1 C420mpeg2\n".encode())
        for image in frames:
            handle.write(b"FRAME\n")
            handle.write(cv2.cvtColor(image, cv2.COLOR_BGR2YUV_I420).tobytes())
    return path


def build_video() -> Path:
    """4 seconds of clear board, then a T20 lands, then a 19."""
    clear = synthetic.clear_board()
    one = synthetic.add_dart(clear, *board.point_for_score(20, board.RING_TREBLE))
    two = synthetic.add_dart(one, *board.point_for_score(19, board.RING_OUTER_SINGLE))
    return write_y4m(WORK / "sequence.y4m", [clear] * 60 + [one] * 75 + [two] * 105)


def find_chromium() -> str | None:
    """Playwright's bundled Chromium, wherever this machine keeps it."""
    for root in filter(None, [Path.home() / ".cache/ms-playwright", Path("/opt/pw-browsers")]):
        for candidate in sorted(root.glob("chromium-*/chrome-linux/chrome")):
            return str(candidate)
        for candidate in sorted(root.glob("chromium-*/chrome-win/chrome.exe")):
            return str(candidate)
    return None


def post(path: str, payload: dict) -> dict:
    import ssl

    request = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    # The LAN certificate is self-signed by design, and a LAN address must
    # never be routed through a configured HTTP proxy.
    unverified = ssl._create_unverified_context()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=unverified)
    )
    return json.loads(opener.open(request).read())


def main() -> int:
    from playwright.sync_api import sync_playwright

    video = build_video()
    failures: list[str] = []
    errors: list[str] = []

    launch_args = [
        "--no-sandbox",
        "--no-proxy-server",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-video-capture={video}",
    ]
    executable = find_chromium()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable, args=launch_args)
        context = browser.new_context(viewport={"width": 390, "height": 844}, permissions=["camera"],
                                      ignore_https_errors=True)
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_timeout(1000)

        if "dot-green" not in (page.get_attribute("#conn-dot", "class") or ""):
            failures.append("connection indicator never went green")

        # --- calibration, through the real click handlers -------------------
        page.click('.tab[data-view="calibrate"]')
        page.click("#btn-freeze")
        page.wait_for_timeout(2500)
        canvas = page.evaluate("() => { const c = document.getElementById('calib-canvas'); return [c.width, c.height]; }")
        rect = page.evaluate(
            "() => { const r = document.getElementById('calib-canvas').getBoundingClientRect();"
            " return [r.x, r.y, r.width, r.height]; }"
        )
        if canvas[0] != synthetic.WIDTH:
            failures.append(f"frozen frame was {canvas}, expected {synthetic.WIDTH}x{synthetic.HEIGHT}")

        for reference in board.DEFAULT_REFERENCE_POINTS:
            px, py = synthetic.board_to_pixel(reference["x_mm"], reference["y_mm"])
            page.mouse.click(rect[0] + px * rect[2] / canvas[0], rect[1] + py * rect[3] / canvas[1])
            page.wait_for_timeout(120)

        page.click("#btn-send-calibration")
        page.wait_for_timeout(1500)
        print("calibration:", page.inner_text("#calib-status"))
        page.screenshot(path=str(WORK / "calibrate.png"))

        # --- live scoring loop ---------------------------------------------
        post("/reset", {})
        page.click('.tab[data-view="play"]')
        if page.inner_text("#btn-start-camera").strip().lower().startswith("stop"):
            page.click("#btn-start-camera")  # freeze already started it
            page.wait_for_timeout(500)
        page.click("#btn-start-camera")

        scored: list[str] = []
        for _ in range(25):
            page.wait_for_timeout(1000)
            scored = page.eval_on_selector_all(
                ".dart-slot:not(.empty)", "els => els.map(e => e.querySelector('small') ? e.childNodes[0].textContent : '')"
            )
            if len(scored) >= 2:
                break

        print("auto-scored:", scored, "| total:", page.inner_text("#total-score"))
        page.screenshot(path=str(WORK / "play.png"))
        if scored[:2] != ["T20", "19"]:
            failures.append(f"expected the camera loop to score T20 then 19, got {scored}")

        browser.close()

    if errors:
        failures.append(f"javascript errors: {errors}")
    print("screenshots in", WORK)
    if failures:
        print("\nFAILED:")
        for failure in failures:
            print(" -", failure)
        return 1
    print("\nPASSED — calibration and the live scoring loop both work end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
