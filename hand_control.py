"""
HandControl - control your real Windows windows with hand gestures.

* Runs in the system tray. It starts OFF; toggle it with Ctrl+Alt+H or the tray menu.
* When ON it opens the camera and draws a click-through overlay over your screen.
* Point with your index finger (other fingers curled) in the RIGHT half of the view.
  Three dots appear top-right: red = Close, yellow = Minimise, green = Maximise/Restore.
  Aim at one (it lights up and shows which window it will act on), then flick your
  finger sharply downward to confirm.
* The action is applied to the window that was in the foreground.

Windows only.
"""
import argparse
import ctypes
import math
import os
import sys
import threading
import time

# ---------------------------------------------------------------- tuning ----
MARGIN = 0.08          # ignore this much of each camera edge so screen edges are reachable
DOT_R = 22             # dot radius (px)
DOT_Y = 84             # dot centre y, below the title-bar buttons of maximised windows
DOT_RIGHT = 40         # distance of the green dot from the right screen edge
DOT_GAP = 56           # centre-to-centre spacing
HIT_PAD = 18           # extra hit radius around each dot
POINT_HOLD = 0.12      # s you must be pointing before anything highlights
AIM_EXTEND = 1.0       # aim point projected this many finger-lengths past the fingertip
MIN_HOVER = 0.35       # s you must stay on a dot before a flick can confirm it
HOVER_MEMORY = 0.6     # s a flick still counts for the dot you just left
FLICK_WINDOW = 0.28    # s over which the downward flick is measured
FLICK_DROP = 0.55      # flick distance, in hand-sizes
COOLDOWN = 1.5         # s between confirmations
DOTS_GRACE = 0.8       # s the dots stay visible after your hand leaves the right half

DOT_LABELS = ["Close", "Minimise", "Resize"]
DOT_COLORS = ["#ff5f57", "#febc2e", "#28c840"]
KEY = "#010203"        # transparent colour key for the overlay


# ------------------------------------------------------------- gestures ----
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def is_pointing(lm):
    """Index clearly straight; middle, ring and pinky clearly curled."""
    def r(t, p):
        return dist(lm[t], lm[0]) / (dist(lm[p], lm[0]) or 1e-6)
    return r(8, 6) > 1.2 and r(12, 10) < 1.08 and r(16, 14) < 1.08 and r(20, 18) < 1.08


EMPTY = {"dots_visible": False, "pointing": False, "hot": None, "label": "", "aim": None,
         "ray": None, "toast": None, "fired": None, "shapes": []}


class Engine:
    """Turns hand landmarks into pointer state and confirmed actions. No OS or camera code."""

    def __init__(self, W, H, get_target, perform, skeleton=False, always_dots=False):
        self.W, self.H = W, H
        self.get_target, self.perform = get_target, perform
        self.skeleton, self.always_dots = skeleton, always_dots
        self.centers = [(W - DOT_RIGHT - (2 - i) * DOT_GAP, DOT_Y) for i in range(3)]
        self.reset()

    def reset(self):
        self.point_since = None
        self.aim = None
        self.hist = []
        self.hover_idx = None
        self.hover_since = 0.0
        self.last_hover = None
        self.last_fire = -1e9
        self.dots_until = 0.0
        self.toast = None
        self.fired = None

    def to_screen(self, x, y):
        m = MARGIN
        sx = (1 - x - m) / (1 - 2 * m)      # camera is mirrored
        sy = (y - m) / (1 - 2 * m)
        return sx * self.W, sy * self.H

    def hit(self, p):
        best, idx = 1e9, None
        for i, (cx, cy) in enumerate(self.centers):
            d = math.hypot(p[0] - cx, p[1] - cy)
            if d < DOT_R + HIT_PAD and d < best:
                best, idx = d, i
        return idx

    def detect_flick(self):
        if len(self.hist) < 3:
            return False
        last = self.hist[-1]
        recent = [h for h in self.hist if last[0] - h[0] <= FLICK_WINDOW]
        top = min(reversed(recent), key=lambda h: h[2])   # highest point; latest one on ties
        dt = last[0] - top[0]
        if dt <= 0:
            return False
        dy = (last[2] - top[2]) / last[3]
        dx = abs(last[1] - top[1]) / last[3]
        return dy > FLICK_DROP and dy > 1.5 * dx

    def update(self, hands, now):
        W = self.W
        pointing = tracked = None
        right_seen = False
        shapes = []
        for lm in hands:
            if self.skeleton:
                shapes.append([self.to_screen(*p) for p in lm])
            sx, _ = self.to_screen(*lm[8])
            if sx > W / 2:
                right_seen = True
                if tracked is None:
                    tracked = lm
                if pointing is None and is_pointing(lm):
                    pointing = lm
        if right_seen:
            self.dots_until = now + DOTS_GRACE

        # flick history follows the pointing hand (or any hand in the right half)
        trk = pointing or tracked
        if trk:
            self.hist.append((now, trk[8][0], trk[8][1], dist(trk[0], trk[9]) or 0.1))
            while self.hist and now - self.hist[0][0] > FLICK_WINDOW + 0.06:
                self.hist.pop(0)
        else:
            self.hist.clear()

        # aiming
        hot = aim = ray = None
        if pointing:
            if self.point_since is None:
                self.point_since = now
            tip, mcp = pointing[8], pointing[5]
            ax, ay = self.to_screen(tip[0] + (tip[0] - mcp[0]) * AIM_EXTEND,
                                    tip[1] + (tip[1] - mcp[1]) * AIM_EXTEND)
            ax = min(max(ax, 0), self.W)
            ay = min(max(ay, 0), self.H)
            if self.aim is None:
                self.aim = (ax, ay)
            else:
                self.aim = (self.aim[0] + (ax - self.aim[0]) * 0.5, self.aim[1] + (ay - self.aim[1]) * 0.5)
            aim, ray = self.aim, self.to_screen(*mcp)
            if now - self.point_since >= POINT_HOLD:
                hot = self.hit(aim)
        else:
            self.point_since = None
            self.aim = None

        label = ""
        if hot is not None:
            if self.hover_idx != hot:
                self.hover_idx, self.hover_since = hot, now
            target = self.get_target()
            self.last_hover = {"idx": hot, "t": now, "held": now - self.hover_since, "target": target}
            label = f"{DOT_LABELS[hot]}: {target[1][:34]}" if target else f"{DOT_LABELS[hot]}: no window"
        else:
            self.hover_idx = None

        # flick to confirm
        lh = self.last_hover
        if (lh and now - lh["t"] < HOVER_MEMORY and lh["held"] >= MIN_HOVER
                and now - self.last_fire > COOLDOWN and self.detect_flick()):
            self.last_fire = now
            self.hist.clear()
            self.last_hover = None
            self.hover_idx = None
            msg = self.perform(lh["idx"], lh["target"])
            self.toast = (msg + " - done", now + 1.6)
            self.fired = (lh["idx"], now)

        toast = self.toast[0] if self.toast and now < self.toast[1] else None
        return {"dots_visible": self.always_dots or pointing is not None or now < self.dots_until,
                "pointing": pointing is not None, "hot": hot, "label": label, "aim": aim, "ray": ray,
                "toast": toast, "fired": self.fired, "shapes": shapes}


# ---------------------------------------------------------------- win32 ----
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                 "XamlExplorerHostIslandWindow"}
WM_CLOSE, WM_HOTKEY = 0x0010, 0x0312
SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x20, 0x80000, 0x80, 0x08000000


class Win32:
    def __init__(self):
        from ctypes import wintypes
        self.wt = wintypes
        u = self.u = ctypes.windll.user32
        u.GetForegroundWindow.restype = wintypes.HWND
        for name, args in {"IsWindow": [wintypes.HWND], "IsWindowVisible": [wintypes.HWND],
                           "IsZoomed": [wintypes.HWND],
                           "ShowWindowAsync": [wintypes.HWND, ctypes.c_int],
                           "PostMessageW": [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
                           "GetClassNameW": [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int],
                           "GetWindowTextW": [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int],
                           "GetWindowThreadProcessId": [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]}.items():
            getattr(u, name).argtypes = args

    def screen_size(self):
        return self.u.GetSystemMetrics(0), self.u.GetSystemMetrics(1)

    def get_target(self):
        u = self.u
        hwnd = u.GetForegroundWindow()
        if not hwnd or not u.IsWindow(hwnd) or not u.IsWindowVisible(hwnd):
            return None
        pid = self.wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return None
        buf = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, buf, 256)
        cls = buf.value
        if cls in SHELL_CLASSES:
            return None
        u.GetWindowTextW(hwnd, buf, 256)
        return hwnd, (buf.value or cls)

    def perform(self, idx, target):
        if not target:
            return "No window to control"
        hwnd, title = target
        u = self.u
        if not u.IsWindow(hwnd):
            return "Window is gone"
        if idx == 0:
            u.PostMessageW(hwnd, WM_CLOSE, 0, 0)       # polite close: apps may ask to save
        elif idx == 1:
            u.ShowWindowAsync(hwnd, SW_MINIMIZE)
        else:
            u.ShowWindowAsync(hwnd, SW_RESTORE if u.IsZoomed(hwnd) else SW_MAXIMIZE)
        return f"{DOT_LABELS[idx]}: {title[:40]}"

    def make_click_through(self, tk_widget):
        u = self.u
        hwnd = u.GetParent(tk_widget.winfo_id()) or tk_widget.winfo_id()
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                         | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)


# ------------------------------------------------------------------ app ----
def make_tray_image(on):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(23, 28, 36, 255),
              outline=(74, 222, 128, 255) if on else (110, 118, 130, 255), width=4)
    cols = [(255, 95, 87), (254, 188, 46), (40, 200, 64)] if on else [(110, 118, 130)] * 3
    for i, c in enumerate(cols):
        cx = 18 + i * 14
        d.ellipse((cx - 5, 27, cx + 5, 37), fill=c + (255,))
    return img


class App:
    def __init__(self, args):
        self.args = args
        self.win = Win32()
        self.W, self.H = self.win.screen_size()
        self.enabled = threading.Event()
        self.stop = threading.Event()
        self.snap = EMPTY
        self.engine = Engine(self.W, self.H, self.win.get_target, self.win.perform,
                             skeleton=args.skeleton, always_dots=args.always_dots)
        self.icon = None

    # tray / toggling
    def notify(self, msg):
        try:
            if self.icon:
                self.icon.notify(msg, "Hand Control")
        except Exception:
            pass

    def refresh_tray(self):
        if self.icon:
            on = self.enabled.is_set()
            self.icon.icon = make_tray_image(on)
            self.icon.title = "Hand Control: " + ("ON" if on else "off") + " (Ctrl+Alt+H)"
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def toggle(self, *_):
        if self.enabled.is_set():
            self.enabled.clear()
        else:
            self.enabled.set()
        self.refresh_tray()

    def quit(self, *_):
        self.stop.set()

    def start_tray(self):
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("Hand control on  (Ctrl+Alt+H)", self.toggle, default=True,
                             checked=lambda i: self.enabled.is_set()),
            pystray.MenuItem("Draw hand skeleton", lambda *_: setattr(self.engine, "skeleton", not self.engine.skeleton),
                             checked=lambda i: self.engine.skeleton),
            pystray.MenuItem("Quit", self.quit))
        self.icon = pystray.Icon("HandControl", make_tray_image(False), "Hand Control: off (Ctrl+Alt+H)", menu)
        self.icon.run_detached()

    # global hotkey (Ctrl+Alt+H)
    def hotkey_loop(self):
        u = ctypes.windll.user32
        if not u.RegisterHotKey(None, 1, 0x0002 | 0x0001 | 0x4000, 0x48):
            self.notify("Ctrl+Alt+H is taken by another app; use the tray menu to toggle.")
            return
        msg = self.win.wt.MSG()
        while not self.stop.is_set():
            if u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1) and msg.message == WM_HOTKEY:
                self.toggle()
            else:
                time.sleep(0.05)
        u.UnregisterHotKey(None, 1)

    # camera + model thread
    def tracker_loop(self):
        cap = hands = None
        cv2 = mp = None
        while not self.stop.is_set():
            if not self.enabled.is_set():
                if cap:
                    cap.release(); cap = None
                if hands:
                    hands.close(); hands = None
                self.snap = EMPTY
                self.engine.reset()
                time.sleep(0.15)
                continue
            try:
                if cap is None:
                    if cv2 is None:
                        import cv2 as _cv2
                        import mediapipe as _mp
                        cv2, mp = _cv2, _mp
                    cap = cv2.VideoCapture(self.args.camera, cv2.CAP_DSHOW)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    if not cap.isOpened():
                        cap.release(); cap = None
                        raise RuntimeError(f"Could not open camera {self.args.camera} (in use or blocked in Windows privacy settings?)")
                    hands = mp.solutions.hands.Hands(max_num_hands=2, model_complexity=1,
                                                     min_detection_confidence=0.5, min_tracking_confidence=0.5)
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.02)
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                res = hands.process(rgb)
                lms = [[(p.x, p.y) for p in h.landmark] for h in (res.multi_hand_landmarks or [])]
                self.snap = self.engine.update(lms, time.monotonic())
            except Exception as e:      # camera/model problem: switch off and tell the user
                self.enabled.clear()
                self.refresh_tray()
                self.notify(str(e)[:200])
                if cap:
                    cap.release(); cap = None
                if hands:
                    hands.close(); hands = None
        if cap:
            cap.release()

    # overlay (tkinter, main thread)
    def run(self):
        import tkinter as tk
        root = self.root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=KEY)
        root.attributes("-transparentcolor", KEY)
        root.geometry(f"{self.W}x{self.H}+0+0")
        self.canvas = tk.Canvas(root, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        root.update_idletasks()
        self.win.make_click_through(root)
        self.shown = False

        self.start_tray()
        threading.Thread(target=self.hotkey_loop, daemon=True).start()
        threading.Thread(target=self.tracker_loop, daemon=True).start()
        if self.args.on:
            self.enabled.set()
            self.refresh_tray()
        else:
            self.notify("Hand control is OFF. Press Ctrl+Alt+H or use the tray icon to turn it on.")
        self.tick()
        root.mainloop()

    def tick(self):
        if self.stop.is_set():
            if self.icon:
                self.icon.stop()
            self.root.destroy()
            return
        on = self.enabled.is_set()
        if on != self.shown:
            self.shown = on
            if on:
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self.win.make_click_through(self.root)
            else:
                self.canvas.delete("all")
                self.root.withdraw()
        if on:
            self.draw(self.snap)
        self.root.after(33, self.tick)

    def draw(self, s):
        c, W, H = self.canvas, self.W, self.H
        c.delete("all")
        now = time.monotonic()
        # camera-on indicator
        c.create_rectangle(W / 2 - 80, 8, W / 2 + 80, 32, fill="#10161d", outline="#2a3340")
        c.create_oval(W / 2 - 68, 16, W / 2 - 60, 24, fill="#4ade80", outline="")
        c.create_text(W / 2 - 52, 20, anchor="w", fill="#e6edf3", font=("Segoe UI", 9, "bold"),
                      text="Hand control ON")
        for pts in s["shapes"]:
            for a, b in ((0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),
                         (9,13),(13,14),(14,15),(15,16),(13,17),(17,18),(18,19),(19,20),(0,17)):
                c.create_line(*pts[a], *pts[b], fill="#4ade80", width=2)
        if s["dots_visible"]:
            for i, (cx, cy) in enumerate(self.engine.centers):
                hot = s["hot"] == i
                r = DOT_R * (1.35 if hot else 1.0)
                if hot:
                    c.create_oval(cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6, outline="#ffffff", width=3)
                c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=DOT_COLORS[i], outline="#101010", width=2)
            if s["fired"]:
                i, t = s["fired"]
                age = now - t
                if age < 0.45:
                    cx, cy = self.engine.centers[i]
                    r = DOT_R + age * 120
                    c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#ffffff", width=3)
            if s["hot"] is not None and s["label"]:
                cx, cy = self.engine.centers[s["hot"]]
                tw = 7 * len(s["label"]) + 20
                x1 = min(max(cx - tw / 2, 6), W - tw - 6)
                c.create_rectangle(x1, cy + DOT_R + 22, x1 + tw, cy + DOT_R + 46, fill="#10161d", outline="#2a3340")
                c.create_text(x1 + tw / 2, cy + DOT_R + 34, fill="#ffffff", font=("Segoe UI", 9, "bold"),
                              text=s["label"])
        if s["aim"]:
            ax, ay = s["aim"]
            col = "#ffffff" if s["hot"] is not None else "#facc15"
            if s["ray"]:
                c.create_line(*s["ray"], ax, ay, fill=col, width=3, dash=(8, 8))
            c.create_oval(ax - 12, ay - 12, ax + 12, ay + 12, outline=col, width=3)
        if s["toast"]:
            c.create_rectangle(W / 2 - 170, H - 90, W / 2 + 170, H - 52, fill="#10161d", outline="#4ade80", width=2)
            c.create_text(W / 2, H - 71, fill="#ffffff", font=("Segoe UI", 11, "bold"), text=s["toast"])


def main():
    ap = argparse.ArgumentParser(description="Control real Windows windows with hand gestures.")
    ap.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    ap.add_argument("--on", action="store_true", help="start with hand control already ON")
    ap.add_argument("--skeleton", action="store_true", help="draw the hand skeleton on the overlay")
    ap.add_argument("--always-dots", action="store_true", help="show the three dots whenever hand control is on")
    args = ap.parse_args()
    if sys.platform != "win32":
        sys.exit("HandControl controls real windows through the Windows API, so it only runs on Windows.")
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # screen px == real px
    except Exception:
        pass
    App(args).run()


if __name__ == "__main__":
    main()
