import ctypes
import tkinter as tk


USER32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

try:
    GET_EXSTYLE = USER32.GetWindowLongPtrW
    SET_EXSTYLE = USER32.SetWindowLongPtrW
except AttributeError:
    GET_EXSTYLE = USER32.GetWindowLongW
    SET_EXSTYLE = USER32.SetWindowLongW


class GhostOverlay:
    """Windows overlay transparente, siempre encima y click-through."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="magenta")

        # Tkinter/Windows hace transparente únicamente el color magenta.
        # No usamos SetLayeredWindowAttributes porque en algunas versiones
        # de Tk/Windows puede volver invisible toda la ventana.
        self.root.wm_attributes("-transparentcolor", "magenta")

        self.canvas = tk.Canvas(
            self.root,
            bg="magenta",
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self.root.update()
        self.hwnd = self.root.winfo_id()
        self._make_click_through()

        self.region = None
        self._visible = False

    def _make_click_through(self):
        style = GET_EXSTYLE(self.hwnd)
        style |= WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        SET_EXSTYLE(self.hwnd, style)

    def set_region(self, region):
        self.region = {
            "left": int(region["left"]),
            "top": int(region["top"]),
            "width": int(region["width"]),
            "height": int(region["height"]),
        }

        self.root.geometry(
            f"{self.region['width']}x{self.region['height']}"
            f"+{self.region['left']}+{self.region['top']}"
        )
        self.root.update()

    def show(self):
        if self.region is None:
            return

        self.root.deiconify()
        self.root.update()

        USER32.SetWindowPos(
            self.hwnd,
            HWND_TOPMOST,
            self.region["left"],
            self.region["top"],
            self.region["width"],
            self.region["height"],
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        USER32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self.root.update()
        self._visible = True

    def hide_for_capture(self):
        if self._visible:
            self.root.withdraw()
            self.root.update()
            self._visible = False

    def draw(self, candidates):
        self.canvas.delete("all")

        for candidate in candidates:
            x = int(candidate["x"])
            y = int(candidate["y"])
            w = int(candidate["w"])
            h = int(candidate["h"])
            kind = candidate.get("kind", "candidate")

            if kind == "large":
                outline = "#00FF66"
            elif kind == "small":
                outline = "#FFD400"
            else:
                outline = "#FFFFFF"

            self.canvas.create_rectangle(
                x,
                y,
                x + w,
                y + h,
                outline=outline,
                width=3,
            )

            if candidate.get("show_label", False) and y >= 20:
                self.canvas.create_text(
                    x + 2,
                    y - 4,
                    text=candidate.get("label", kind),
                    anchor="sw",
                    fill=outline,
                    font=("Segoe UI", 9, "bold"),
                )

        self.root.update()

    def close(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
