import argparse
import json
import time
from pathlib import Path

import cv2
import mss
import numpy as np


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
TEMPLATE_DIR = ROOT / "templates"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_templates():
    templates = []
    if not TEMPLATE_DIR.exists():
        return templates

    for path in sorted(TEMPLATE_DIR.glob("*.png")):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        templates.append((path.stem, image))

    return templates


def screenshot(sct, region):
    if region is None:
        shot = sct.grab(sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0])
        origin_x = shot.left
        origin_y = shot.top
    else:
        shot = sct.grab(region)
        origin_x = region["left"]
        origin_y = region["top"]

    frame = np.array(shot)
    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    return frame, origin_x, origin_y


def find_candidates(frame, config):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # The event ghosts have a luminous outline/body. This mask is deliberately
    # broad for the first calibration pass; color-specific filtering comes later.
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    mask = cv2.inRange(
        np.dstack([hsv[:, :, 0], saturation, value]),
        np.array([0, 70, 130], dtype=np.uint8),
        np.array([179, 255, 255], dtype=np.uint8),
    )

    # Favor connected luminous shapes rather than isolated UI pixels.
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    min_area = config["min_area"]
    max_area = config["max_area"]

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue

        x, y, w, h = cv2.boundingRect(contour)
        if w < 25 or h < 25:
            continue

        ratio = w / float(h)
        if ratio < 0.45 or ratio > 1.9:
            continue

        candidates.append({
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "area": area,
            "cx": x + w // 2,
            "cy": y + h // 2,
        })

    return candidates, mask


def classify_size(candidate):
    # Temporary classification. It will be calibrated from real full-screen
    # captures once the large ghost examples are available.
    area = candidate["w"] * candidate["h"]
    return "large" if area >= 9000 else "small"


def draw_candidates(frame, candidates):
    output = frame.copy()
    for candidate in candidates:
        x, y, w, h = (
            candidate["x"],
            candidate["y"],
            candidate["w"],
            candidate["h"],
        )
        kind = classify_size(candidate)
        cv2.rectangle(output, (x, y), (x + w, y + h), (255, 255, 255), 2)
        cv2.putText(
            output,
            f"{kind} {w}x{h}",
            (x, max(20, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    return output


def run(debug=False):
    config = load_config()

    # The detector is intentionally disabled for live clicking until its
    # detections are calibrated against complete game screenshots.
    if config.get("click_enabled"):
        raise RuntimeError(
            "click_enabled=true is blocked in this initial calibration build. "
            "Validate detection first."
        )

    region = config.get("capture_region")
    templates = load_templates()
    print(f"[GHOST] templates cargadas: {len(templates)}")
    print("[GHOST] modo calibración: NO hace clic.")

    with mss.mss() as sct:
        while True:
            frame, origin_x, origin_y = screenshot(sct, region)
            candidates, mask = find_candidates(frame, config)

            if candidates:
                print(
                    "[GHOST] candidatos:",
                    [
                        {
                            "screen": (
                                c["cx"] + origin_x,
                                c["cy"] + origin_y,
                            ),
                            "size": classify_size(c),
                            "box": (c["w"], c["h"]),
                        }
                        for c in candidates
                    ],
                )

            if debug:
                preview = draw_candidates(frame, candidates)
                cv2.imshow("Highrise Ghost Detector - DEBUG", preview)
                cv2.imshow("Highrise Ghost Detector - MASK", mask)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break

            time.sleep(0.02)

    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    run(debug=args.debug)


if __name__ == "__main__":
    main()
