#!/usr/bin/env python3
"""Smooth mouse-wheel scrolling for Wayland/Hyprland.

Grabs physical mice, re-emits motion/buttons unchanged, and turns each
wheel detent into a decaying burst of REL_WHEEL_HI_RES events.

Config: ~/.config/omarchy/smooth-scroll.json
"""
from __future__ import annotations

import array
import fcntl
import json
import os
import select
import signal
import struct
import sys
import time
from pathlib import Path

HOME = Path.home()
CONFIG_PATH = Path(os.environ.get("OMARCHY_SMOOTH_SCROLL_CONFIG") or (HOME / ".config/omarchy/smooth-scroll.json"))
LOCK_PATH = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "stillpilot-smooth-scroll.lock"
VIRTUAL_NAME = "Omarchy Smooth Scroll"

EVENT_FMT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FMT)

EV_SYN, EV_KEY, EV_REL, EV_MSC, EV_ABS = 0, 1, 2, 4, 3
SYN_REPORT, SYN_DROPPED = 0, 3
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL = 0, 1, 6, 8
REL_HWHEEL_HI_RES, REL_WHEEL_HI_RES = 12, 11
MSC_SCAN = 4
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
BTN_SIDE, BTN_EXTRA, BTN_FORWARD, BTN_BACK, BTN_TASK = 0x113, 0x114, 0x115, 0x116, 0x117
INPUT_PROP_POINTER = 0

WHEEL_CODES = {REL_WHEEL, REL_HWHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES}
PASSTHROUGH_BUTTONS = [
    BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA, BTN_FORWARD, BTN_BACK, BTN_TASK,
]


def _ioc(dir_, typ, nr, size=0):
    return (dir_ << 30) | (size << 16) | (typ << 8) | nr


def _ior(nr, size, typ=ord("E")):
    return _ioc(2, typ, nr, size)


def _iow(nr, size, typ=ord("E")):
    return _ioc(1, typ, nr, size)


def _io(nr, typ=ord("U")):
    return _ioc(0, typ, nr, 0)


EVIOCGNAME = _ior(0x06, 255)
EVIOCGRAB = _iow(0x90, 4)
UI_DEV_CREATE = _io(1)
UI_DEV_DESTROY = _io(2)
UI_DEV_SETUP = _iow(3, 92, ord("U"))
UI_SET_EVBIT = _iow(100, 4, ord("U"))
UI_SET_KEYBIT = _iow(101, 4, ord("U"))
UI_SET_RELBIT = _iow(102, 4, ord("U"))
UI_SET_MSCBIT = _iow(104, 4, ord("U"))
UI_SET_PROPBIT = _iow(110, 4, ord("U"))

DEFAULTS = {
    "enabled": True,
    "natural": True,
    "damping": 65,
    "acceleration": 35,
}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def load_config():
    data = dict(DEFAULTS)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update(raw)
    except (OSError, json.JSONDecodeError):
        pass
    data["enabled"] = bool(data.get("enabled", True))
    data["natural"] = bool(data.get("natural", True))
    data["damping"] = int(clamp(int(data.get("damping", 65)), 0, 100))
    data["acceleration"] = int(clamp(int(data.get("acceleration", 35)), 0, 100))
    return data


def save_config(data):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = load_config()
    payload.update(data)
    payload["enabled"] = bool(payload["enabled"])
    payload["natural"] = bool(payload["natural"])
    payload["damping"] = int(clamp(int(payload["damping"]), 0, 100))
    payload["acceleration"] = int(clamp(int(payload["acceleration"]), 0, 100))
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    return payload


def device_name(fd):
    buf = array.array("B", [0] * 256)
    fcntl.ioctl(fd, EVIOCGNAME, buf)
    return bytes(buf).split(b"\x00", 1)[0].decode("utf-8", "replace")


def evbit(fd, ev, length=64):
    buf = array.array("B", [0] * length)
    fcntl.ioctl(fd, _ior(0x20 + ev, length), buf)
    return int.from_bytes(buf.tobytes(), "little")


def is_mouse_path(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        name = device_name(fd)
        if name == VIRTUAL_NAME:
            return False
        lowered = name.lower()
        if any(s in lowered for s in ("keyboard", "consumer control", "system control", "touchpad")):
            return False
        rel = evbit(fd, EV_REL)
        has_move = bool(rel & (1 << REL_X))
        has_wheel = bool(rel & ((1 << REL_WHEEL) | (1 << REL_WHEEL_HI_RES)))
        return has_move and has_wheel
    except OSError:
        return False
    finally:
        os.close(fd)


def list_mice():
    return [p for p in sorted(Path("/dev/input").glob("event*")) if is_mouse_path(str(p))]


def pack_event(etype, code, value):
    now = time.time()
    sec = int(now)
    usec = int((now - sec) * 1_000_000)
    return struct.pack(EVENT_FMT, sec, usec, etype, code, int(value))


class UInput:
    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        for ev in (EV_SYN, EV_KEY, EV_REL, EV_MSC):
            fcntl.ioctl(self.fd, UI_SET_EVBIT, ev)
        for code in PASSTHROUGH_BUTTONS:
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        for code in (REL_X, REL_Y, REL_WHEEL, REL_HWHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES):
            fcntl.ioctl(self.fd, UI_SET_RELBIT, code)
        fcntl.ioctl(self.fd, UI_SET_MSCBIT, MSC_SCAN)
        fcntl.ioctl(self.fd, UI_SET_PROPBIT, INPUT_PROP_POINTER)
        setup = struct.pack("HHHH80sI", 0x03, 0x0001, 0x0001, 1, VIRTUAL_NAME.encode().ljust(80, b"\x00"), 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.05)

    def write(self, etype, code, value):
        os.write(self.fd, pack_event(etype, code, value))

    def syn(self):
        self.write(EV_SYN, SYN_REPORT, 0)

    def close(self):
        if self.fd < 0:
            return
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self.fd)
        self.fd = -1


class GrabbedMouse:
    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.name = device_name(self.fd)
        fcntl.ioctl(self.fd, EVIOCGRAB, 1)
        self.wheel = 0
        self.hires = 0
        self.hwheel = 0
        self.hhires = 0

    def ungrab(self):
        try:
            fcntl.ioctl(self.fd, EVIOCGRAB, 0)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = -1


class Smoother:
    def __init__(self):
        self.cfg = load_config()
        self.cfg_mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else 0
        self.vy = 0.0
        self.vx = 0.0
        self.acc_y = 0.0
        self.acc_x = 0.0
        self.last_tick = 0.0

    def reload(self):
        try:
            mtime = CONFIG_PATH.stat().st_mtime
        except OSError:
            return False
        if mtime == self.cfg_mtime:
            return False
        self.cfg_mtime = mtime
        self.cfg = load_config()
        return True

    def impulse(self, hires_y, hires_x, now):
        dt = now - self.last_tick if self.last_tick else 1.0
        self.last_tick = now
        flick = 1.0
        if dt < 0.08:
            flick = 1.0 + (self.cfg["acceleration"] / 100.0) * 2.0 * (1.0 - dt / 0.08)
        sign = -1 if self.cfg["natural"] else 1
        self.vy += sign * hires_y * flick
        self.vx += sign * hires_x * flick

    def step(self, dt):
        tau = 0.025 + (self.cfg["damping"] / 100.0) * 0.225
        decay = pow(0.5, dt / max(0.008, tau))
        emitted = []
        for attr, acc_attr, hi_code in (
            ("vy", "acc_y", REL_WHEEL_HI_RES),
            ("vx", "acc_x", REL_HWHEEL_HI_RES),
        ):
            vel = getattr(self, attr)
            if abs(vel) < 0.4:
                setattr(self, attr, 0.0)
                continue
            chunk = vel * (1.0 - decay)
            setattr(self, attr, vel * decay)
            acc = getattr(self, acc_attr) + chunk
            hi = int(acc)
            setattr(self, acc_attr, acc - hi)
            if hi:
                emitted.append((hi_code, hi))
        return emitted


class Engine:
    def __init__(self):
        self.ui = None
        self.mice = []
        self.smoother = Smoother()
        self.running = True
        self.active = False
        self.last_hypr_natural = None

    def log(self, msg):
        sys.stderr.write(f"smooth-scroll: {msg}\n")
        sys.stderr.flush()

    def set_hypr_natural(self, value):
        if self.last_hypr_natural is value:
            return
        self.last_hypr_natural = value
        flag = "true" if value else "false"
        os.spawnlp(
            os.P_NOWAIT,
            "hyprctl",
            "hyprctl",
            "eval",
            f"hl.config({{ input = {{ natural_scroll = {flag} }} }})",
        )

    def start_grab(self):
        if self.active:
            return
        paths = list_mice()
        if not paths:
            self.log("no wheel mice found")
            return
        try:
            self.ui = UInput()
        except OSError as exc:
            self.log(f"uinput failed: {exc}")
            return
        grabbed = []
        try:
            for path in paths:
                grabbed.append(GrabbedMouse(str(path)))
        except OSError as exc:
            for mouse in grabbed:
                mouse.ungrab()
            self.ui.close()
            self.ui = None
            self.log(f"grab failed: {exc}")
            return
        self.mice = grabbed
        self.active = True
        self.set_hypr_natural(False)
        names = ", ".join(m.name for m in self.mice)
        self.log(f"active on {names}")

    def stop_grab(self):
        for mouse in self.mice:
            mouse.ungrab()
        self.mice = []
        if self.ui:
            self.ui.close()
            self.ui = None
        was_active = self.active
        self.active = False
        self.smoother.vy = self.smoother.vx = 0.0
        if was_active:
            self.set_hypr_natural(bool(self.smoother.cfg["natural"]))
            self.log("idle")

    def handle_device(self, mouse: GrabbedMouse):
        try:
            data = os.read(mouse.fd, EVENT_SIZE * 64)
        except BlockingIOError:
            return
        except OSError:
            return
        for offset in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
            _sec, _usec, etype, code, value = struct.unpack_from(EVENT_FMT, data, offset)
            if etype == EV_REL and code in WHEEL_CODES:
                if code == REL_WHEEL:
                    mouse.wheel += value
                elif code == REL_WHEEL_HI_RES:
                    mouse.hires += value
                elif code == REL_HWHEEL:
                    mouse.hwheel += value
                elif code == REL_HWHEEL_HI_RES:
                    mouse.hhires += value
                continue
            if etype == EV_SYN and code == SYN_REPORT:
                hires_y = mouse.hires if mouse.hires else mouse.wheel * 120
                hires_x = mouse.hhires if mouse.hhires else mouse.hwheel * 120
                if hires_y or hires_x:
                    self.smoother.impulse(hires_y, hires_x, time.monotonic())
                mouse.wheel = mouse.hires = mouse.hwheel = mouse.hhires = 0
            if etype == EV_SYN and code == SYN_DROPPED:
                mouse.wheel = mouse.hires = mouse.hwheel = mouse.hhires = 0
                continue
            if self.ui:
                try:
                    os.write(self.ui.fd, struct.pack(EVENT_FMT, _sec, _usec, etype, code, value))
                except OSError:
                    pass

    def loop(self):
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "running", False))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "running", False))
        last = time.monotonic()
        while self.running:
            self.smoother.reload()
            want = bool(self.smoother.cfg["enabled"])
            if want and not self.active:
                self.start_grab()
            elif not want and self.active:
                self.stop_grab()
            timeout = 0.008
            fds = [m.fd for m in self.mice if m.fd >= 0]
            if fds:
                readable, _, _ = select.select(fds, [], [], timeout)
                for mouse in self.mice:
                    if mouse.fd in readable:
                        self.handle_device(mouse)
            else:
                time.sleep(timeout)
            now = time.monotonic()
            dt = now - last
            last = now
            if self.active:
                chunks = self.smoother.step(dt)
                if chunks and self.ui:
                    for code, value in chunks:
                        if value:
                            self.ui.write(EV_REL, code, value)
                    self.ui.syn()
        self.stop_grab()


def acquire_lock():
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        print("smooth-scroll: already running", file=sys.stderr)
        sys.exit(0)
    os.write(fd, str(os.getpid()).encode())
    return fd


def cmd_get():
    print(json.dumps(load_config(), indent=2))


def cmd_set(args):
    if len(args) < 2:
        print("usage: daemon.py set <enabled|natural|damping|acceleration> <value>", file=sys.stderr)
        sys.exit(2)
    key, raw = args[0], args[1]
    if key not in DEFAULTS:
        print(f"unknown key: {key}", file=sys.stderr)
        sys.exit(2)
    if key in ("enabled", "natural"):
        value = raw.lower() in ("1", "true", "yes", "on")
    else:
        value = int(raw)
    cfg = save_config({key: value})
    print(json.dumps(cfg))


def cmd_list():
    for path in list_mice():
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
        try:
            print(f"{path}  {device_name(fd)}")
        finally:
            os.close(fd)


def main():
    argv = sys.argv[1:]
    if not argv:
        acquire_lock()
        Engine().loop()
        return
    cmd = argv[0]
    if cmd == "get":
        cmd_get()
    elif cmd == "set":
        cmd_set(argv[1:])
    elif cmd == "list":
        cmd_list()
    elif cmd in ("-h", "--help"):
        print("usage: daemon.py [get|set KEY VALUE|list]")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
