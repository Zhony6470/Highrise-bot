import ctypes
import tkinter as tk


USER32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
LWA_COLORKEY = 0x00000001
SW_SHOWNOACTIVATE = 4

try:
    GET_EXSTYLE = USER32.GetWindowLongPtrW
    SET_EXSTYLE = USER32.SetWindowLongPtrW
except AttributeError:
    GET_EXSTYLE = USER32.GetWindowLongW
    SET_EXSTYLE = USER32.SetWindowLongW


class GhostOverlay:
    """Transparent, topmost, click-through Windows overlay."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Highrise Ghost Detector Overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="magenta")

        # Windows color-key transparency: magenta pixels are invisible.
        self.root.wm_attributes("-transparentcolor", "magenta")

        self.canvas = tk.Canvas(
            self.root,
            bg="magenta",
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self.hwnd = self.root.winfo_id()
        self._make_click_through()

        self.region = None
        self._visible = False
        self.root.withdraw()
        self.root.update_idletasks()

    def _make_click_through(self):
        style = GET_EXSTYLE(self.hwnd)
        style |= (
            WS_EX_LAYERED
            | WS_EX_TRANSPARENT
            | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE
        )
        SET_EXSTYLE(self.hwnd, style)

        # Ensure the layered window uses the same transparent color.
        USER32.SetLayeredWindowAttributes(
            self.hwnd,
            0x00FF00FF,  # magenta COLORREF
            0,
            LWA_COLORKEY,
        )

    def set_region(self, region):
        self.region = region
        self.root.geometry(
            f"{int(region['width'])}x{int(region['height'])}"
            f"+{int(region['left'])}+{int(region['top'])}"
        )
        self.root.update_idletasks()

    def show(self):
        if self.region is None:
            return
        self.root.deiconify()
        USER32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        USER32.SetWindowPos(
            self.hwnd,
            -1,  # HWND_TOPMOST
            int(self.region["left"]),
            int(self.region["top"]),
            int(self.region["width"]),
            int(self.region["height"]),
            0x0010 | 0x0004,  # SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
        self.root.update_idletasks()
        self._visible = True

    def hide_for_capture(self):
        if self._visible:
            self.root.withdraw()
            self.root.update_idletasks()
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

            # Small label just above the box.
            label = candidate.get("label", kind)
            if y >= 20:
                self.canvas.create_text(
                    x + 2,
                    y - 4,
                    text=label,
                    anchor="sw",
                    fill=outline,
                    font=("Segoe UI", 9, "bold"),
                )

        self.root.update_idletasks()

    def close(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
