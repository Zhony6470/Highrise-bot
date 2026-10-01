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


def save_config(config):
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


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


def get_monitor(sct):
    return sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]


def grab_monitor(sct):
    monitor = get_monitor(sct)
    shot = sct.grab(monitor)
    frame = np.array(shot)
    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    return frame, monitor["left"], monitor["top"]


def screenshot(sct, region):
    if region is None:
        return grab_monitor(sct)

    shot = sct.grab(region)
    origin_x = region["left"]
    origin_y = region["top"]

    frame = np.array(shot)
    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    return frame, origin_x, origin_y


def select_region(sct):
    frame, origin_x, origin_y = grab_monitor(sct)
    window = "Highrise Ghost Detector - Seleccionar zona"

    state = {
        "start": None,
        "end": None,
        "dragging": False,
        "finished": False,
    }

    display = frame.copy()

    def mouse_callback(event, x, y, flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["start"] = (x, y)
            state["end"] = (x, y)
            state["dragging"] = True

        elif event == cv2.EVENT_MOUSEMOVE and state["dragging"]:
            state["end"] = (x, y)

        elif event == cv2.EVENT_LBUTTONUP and state["dragging"]:
            state["end"] = (x, y)
            state["dragging"] = False
            state["finished"] = True

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setMouseCallback(window, mouse_callback)

    print("[GHOST] Selecciona con el mouse la zona de Highrise que quieres analizar.")
    print("[GHOST] Arrastra desde una esquina hasta la esquina opuesta.")
    print("[GHOST] ENTER confirma | ESC cancela | R reinicia la selección.")

    while True:
        display = frame.copy()

        if state["start"] is not None and state["end"] is not None:
            x1, y1 = state["start"]
            x2, y2 = state["end"]
            cv2.rectangle(display, (x1, y1), (x2, y2), (255, 255, 255), 3)

            width = abs(x2 - x1)
            height = abs(y2 - y1)
            label = f"Zona: {width} x {height} px"
            cv2.putText(
                display,
                label,
                (min(x1, x2) + 10, max(25, min(y1, y2) - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

        cv2.putText(
            display,
            "ARRASTRA para seleccionar | ENTER confirmar | ESC cancelar | R reiniciar",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        cv2.imshow(window, display)
        key = cv2.waitKey(20) & 0xFF

        if key == 27:
            cv2.destroyWindow(window)
            print("[GHOST] Selección cancelada.")
            return None

        if key in (ord("r"), ord("R")):
            state["start"] = None
            state["end"] = None
            state["dragging"] = False
            state["finished"] = False

        if key in (13, 10) and state["start"] and state["end"]:
            x1, y1 = state["start"]
            x2, y2 = state["end"]

            left = min(x1, x2) + origin_x
            top = min(y1, y2) + origin_y
            right = max(x1, x2) + origin_x
            bottom = max(y1, y2) + origin_y

            width = right - left
            height = bottom - top

            if width < 100 or height < 100:
                print("[GHOST] La zona es demasiado pequeña. Selecciona al menos 100x100 px.")
                continue

            region = {
                "left": int(left),
                "top": int(top),
                "width": int(width),
                "height": int(height),
            }

            cv2.destroyWindow(window)
            return region


def find_candidates(frame, config):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    mask = cv2.inRange(
        np.dstack([hsv[:, :, 0], saturation, value]),
        np.array([0, 70, 130], dtype=np.uint8),
        np.array([179, 255, 255], dtype=np.uint8),
    )

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

        candidates.append(
            {
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "area": area,
                "cx": x + w // 2,
                "cy": y + h // 2,
            }
        )

    return candidates, mask


def classify_size(candidate):
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


def run(debug=False, select=False):
    config = load_config()

    if config.get("click_enabled"):
        raise RuntimeError(
            "click_enabled=true is blocked in this initial calibration build. "
            "Validate detection first."
        )

    with mss.mss() as sct:
        if select:
            region = select_region(sct)
            if region is None:
                return

            config["capture_region"] = region
            save_config(config)

            print(f"[GHOST] Zona guardada: {region}")
            print("[GHOST] Esa zona se usará en los próximos arranques.")

        region = config.get("capture_region")
        templates = load_templates()

        print(f"[GHOST] templates cargadas: {len(templates)}")
        print("[GHOST] modo calibración: NO hace clic.")

        if region:
            print(f"[GHOST] capturando solamente: {region}")
        else:
            print("[GHOST] capturando monitor completo.")

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
    parser.add_argument(
        "--select-region",
        action="store_true",
        help="selecciona con el mouse la zona de pantalla que analizará el detector",
    )
    args = parser.parse_args()
    run(debug=args.debug, select=args.select_region)


if __name__ == "__main__":
    main()
