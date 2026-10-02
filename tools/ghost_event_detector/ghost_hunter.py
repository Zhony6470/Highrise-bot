import argparse
import json
import time
from pathlib import Path

import cv2
import mss
import numpy as np

from overlay import GhostOverlay


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


def screenshot(sct, region, overlay=None):
    # El overlay permanece visible durante la captura. Sus rectángulos
    # son blancos (saturación baja), así que la máscara HSV los ignora.
    if region is None:
        frame, origin_x, origin_y = grab_monitor(sct)
    else:
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
    }

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

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setMouseCallback(window, mouse_callback)

    print("[GHOST] Selecciona la zona de Highrise.")
    print("[GHOST] Arrastra con el mouse y pulsa ENTER para confirmar.")
    print("[GHOST] ESC cancela | R reinicia.")

    while True:
        display = frame.copy()

        if state["start"] is not None and state["end"] is not None:
            x1, y1 = state["start"]
            x2, y2 = state["end"]
            cv2.rectangle(display, (x1, y1), (x2, y2), (255, 255, 255), 3)

            width = abs(x2 - x1)
            height = abs(y2 - y1)
            cv2.putText(
                display,
                f"Zona: {width} x {height} px",
                (min(x1, x2) + 10, max(25, min(y1, y2) - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

        cv2.putText(
            display,
            "ARRASTRA | ENTER confirmar | ESC cancelar | R reiniciar",
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
                print("[GHOST] La zona debe ser de al menos 100x100 px.")
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

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        np.ones((3, 3), np.uint8),
    )
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        np.ones((7, 7), np.uint8),
    )

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

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

    return candidates


def classify_size(candidate):
    area = candidate["w"] * candidate["h"]
    return "large" if area >= 9000 else "small"


def make_overlay_candidates(candidates, config):
    result = []
    for candidate in candidates:
        kind = classify_size(candidate)
        result.append(
            {
                **candidate,
                "kind": kind,
                "label": f"{kind} {candidate['w']}x{candidate['h']}",
            }
        )
    return result


def print_candidates(candidates, origin_x, origin_y):
    if not candidates:
        return

    data = []
    for candidate in candidates:
        data.append(
            {
                "screen": (
                    candidate["cx"] + origin_x,
                    candidate["cy"] + origin_y,
                ),
                "size": classify_size(candidate),
                "box": (candidate["w"], candidate["h"]),
            }
        )
    print("[GHOST] candidatos:", data)


def run(overlay_enabled=True, select=False):
    config = load_config()

    if config.get("click_enabled"):
        raise RuntimeError(
            "click_enabled=true está bloqueado en esta fase. "
            "Primero valida la detección."
        )

    overlay = GhostOverlay() if overlay_enabled else None
    last_print = 0.0

    try:
        with mss.mss() as sct:
            if select:
                region = select_region(sct)
                if region is None:
                    return

                config["capture_region"] = region
                save_config(config)

                print(f"[GHOST] Zona guardada: {region}")

            region = config.get("capture_region")
            templates = load_templates()

            print(f"[GHOST] templates cargadas: {len(templates)}")
            print("[GHOST] modo calibración: NO hace clic.")
            print("[GHOST] overlay:", "ACTIVO" if overlay_enabled else "DESACTIVADO")

            if region:
                print(f"[GHOST] capturando solamente: {region}")
                if overlay:
                    overlay.set_region(region)
            else:
                print("[GHOST] capturando monitor completo.")
                if overlay:
                    monitor = get_monitor(sct)
                    overlay.set_region(
                        {
                            "left": monitor["left"],
                            "top": monitor["top"],
                            "width": monitor["width"],
                            "height": monitor["height"],
                        }
                    )

            while True:
                frame, origin_x, origin_y = screenshot(
                    sct,
                    region,
                    overlay=overlay,
                )
                candidates = find_candidates(frame, config)

                now = time.monotonic()
                if candidates and now - last_print >= 0.5:
                    print_candidates(candidates, origin_x, origin_y)
                    last_print = now

                if overlay:
                    overlay.draw(make_overlay_candidates(candidates, config))
                    overlay.show()

                time.sleep(0.03)

    except KeyboardInterrupt:
        print("\n[GHOST] Detector detenido.")
    finally:
        if overlay:
            overlay.close()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(
        description="Detector local de fantasmas para pruebas en Highrise."
    )
    parser.add_argument(
        "--select-region",
        action="store_true",
        help="selecciona nuevamente la zona de captura.",
    )
    parser.add_argument(
        "--console-only",
        action="store_true",
        help="desactiva el overlay y deja solo la salida de consola.",
    )
    args = parser.parse_args()

    run(
        overlay_enabled=not args.console_only,
        select=args.select_region,
    )


if __name__ == "__main__":
    main()
