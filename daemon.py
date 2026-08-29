#!/usr/bin/env python3
"""Smooth mouse-wheel scrolling for Wayland/Hyprland.

Grabs physical mice, re-emits motion/buttons unchanged, and turns each
wheel detent into a decaying burst of REL_WHEEL_HI_RES events.

Config: ~/.config/omarchy/smooth-scroll.json
"""
from __future__ import annotations

import array
import atexit
import ctypes
import fcntl
import json
import os
import queue
import select
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path.home()
CONFIG_PATH = Path(os.environ.get("OMARCHY_SMOOTH_SCROLL_CONFIG") or (HOME / ".config/omarchy/smooth-scroll.json"))
LOCK_PATH = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "stillpilot-smooth-scroll.lock"
LEARN_PATH = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "smooth-scroll.learn"
LEARN_MAX_AGE = 20
VIRTUAL_NAME = "Omarchy Smooth Scroll"
OMARCHY_BIN = "/usr/share/omarchy/bin"
PLUGIN_DIR = Path(__file__).resolve().parent
UPDATE_INTERVAL = 6 * 3600
UPDATE_FIRST_DELAY = 45

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
EXTRA_BUTTON_MASK = (
    (1 << BTN_SIDE) | (1 << BTN_EXTRA) | (1 << BTN_FORWARD) | (1 << BTN_BACK) | (1 << BTN_TASK)
)
PASSTHROUGH_BUTTONS = [
    BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA, BTN_FORWARD, BTN_BACK, BTN_TASK,
]
SKIP_NAME_PARTS = (
    "keyboard",
    "consumer control",
    "system control",
    "touchpad",
    "link-km",
    "avrcp",
    "speaker",
    "headphone",
    "microphone",
)
PR_SET_TIMERSLACK = 29
BTN_LABELS = {
    BTN_LEFT: "left",
    BTN_RIGHT: "right",
    BTN_MIDDLE: "middle (wheel click)",
    BTN_SIDE: "side / back (thumb)",
    BTN_EXTRA: "extra / forward (thumb)",
    BTN_FORWARD: "forward",
    BTN_BACK: "back",
    BTN_TASK: "task",
}


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
    "auto_update": True,
    "bindings": {},
}

VOLUME_FEEDBACK = PLUGIN_DIR / "volume-feedback.sh"
ACTIONS = {
    "keybindings": [f"{OMARCHY_BIN}/omarchy-menu-keybindings"],
    "volume-up": [str(VOLUME_FEEDBACK), "raise"],
    "volume-down": [str(VOLUME_FEEDBACK), "lower"],
    "volume-mute": [str(VOLUME_FEEDBACK), "mute-toggle"],
    "play-pause": [f"{OMARCHY_BIN}/omarchy-shell", "media", "playPause"],
    "next-track": [f"{OMARCHY_BIN}/omarchy-shell", "media", "next"],
    "prev-track": [f"{OMARCHY_BIN}/omarchy-shell", "media", "previous"],
}

SKIP_LEARN = {BTN_LEFT, BTN_RIGHT}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def expire_learn(max_age=LEARN_MAX_AGE):
    try:
        age = time.time() - LEARN_PATH.stat().st_mtime
    except OSError:
        return
    if age > max_age:
        try:
            LEARN_PATH.unlink()
        except OSError:
            pass


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
    data["auto_update"] = bool(data.get("auto_update", True))
    data["bindings"] = normalize_bindings(data.get("bindings"))
    return data


def normalize_bindings(raw):
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        if not value or value == "none":
            continue
        if isinstance(value, dict):
            out[str(key)] = value
        else:
            out[str(key)] = str(value)
    return out


def save_config(data):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = load_config()
    incoming_bindings = data.pop("bindings") if "bindings" in data else None
    payload.update(data)
    if incoming_bindings is not None:
        payload["bindings"] = normalize_bindings(incoming_bindings)
    payload["enabled"] = bool(payload["enabled"])
    payload["natural"] = bool(payload["natural"])
    payload["damping"] = int(clamp(int(payload["damping"]), 0, 100))
    payload["acceleration"] = int(clamp(int(payload["acceleration"]), 0, 100))
    payload["auto_update"] = bool(payload.get("auto_update", True))
    payload["bindings"] = normalize_bindings(payload.get("bindings"))
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    return payload


def git_cmd(*args, timeout=40):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", "-C", str(PLUGIN_DIR), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def try_auto_update():
    if not load_config().get("auto_update", True):
        return False
    if not (PLUGIN_DIR / ".git").is_dir():
        return False
    try:
        if git_cmd("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
            return False
        if git_cmd("status", "--porcelain").stdout.strip():
            return False
        fetch = git_cmd("fetch", "--quiet", "origin", "HEAD")
        if fetch.returncode != 0:
            return False
        local = git_cmd("rev-parse", "HEAD").stdout.strip()
        remote = git_cmd("rev-parse", "FETCH_HEAD").stdout.strip()
        if not remote or local == remote:
            return False
        if git_cmd("merge", "--ff-only", "FETCH_HEAD").returncode != 0:
            return False
        return git_cmd("rev-parse", "HEAD").stdout.strip() != local
    except (OSError, subprocess.TimeoutExpired):
        return False


def restart_daemon():
    script = str(PLUGIN_DIR / "daemon.py")
    os.execv(sys.executable, [sys.executable, script])


def ensure_path():
    parts = os.environ.get("PATH", "/usr/bin").split(":")
    extra = [OMARCHY_BIN, str(HOME / ".local/bin"), "/usr/bin"]
    os.environ["PATH"] = ":".join(extra + [p for p in parts if p not in extra])


def _spawn(argv):
    try:
        subprocess.Popen(
            argv,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
    except OSError as exc:
        sys.stderr.write(f"smooth-scroll: spawn failed: {exc}\n")


def lua_str(value):
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def hyprctl_dispatch_expr(expression):
    """Run a Lua dispatcher object via `hyprctl dispatch`, same as Super+K.

    Omarchy 4's Hyprland wraps `hyprctl dispatch X` as `hl.dispatch(X)`, so
    classic `dispatch exec foo` is a parse error. Pass `hl.dsp.*(...)` instead.
    """
    expression = str(expression or "").strip()
    if not expression:
        return False
    try:
        result = subprocess.run(
            ["hyprctl", "dispatch", expression],
            capture_output=True,
            text=True,
            timeout=5,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        sys.stderr.write(f"smooth-scroll: hyprctl dispatch failed: {exc}\n")
        return False
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode == 0 and out in ("", "ok"):
        return True
    sys.stderr.write(f"smooth-scroll: hyprctl dispatch failed: {out or err or result.returncode}\n")
    return False


def dispatch_exec(command):
    command = str(command or "")
    if not command:
        return False
    if hyprctl_dispatch_expr(f"hl.dsp.exec_cmd({lua_str(command)})"):
        return True
    try:
        result = subprocess.run(
            ["hyprctl", "eval", f"hl.exec_cmd({lua_str(command)})"],
            capture_output=True,
            text=True,
            timeout=5,
            env=os.environ.copy(),
        )
        out = (result.stdout or "").strip()
        if result.returncode == 0 and out in ("", "ok"):
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    _spawn(["/bin/sh", "-c", command])
    return True


def dispatch_sendshortcut(arg):
    parts = str(arg or "").split(",")
    mods = parts[0].strip() if parts else ""
    key = parts[1].strip() if len(parts) > 1 else ""
    window = parts[2].strip() if len(parts) > 2 else ""
    if not key:
        return False
    if not window:
        window = "activewindow"
    down = (
        "hl.dsp.send_key_state({ mods = "
        + lua_str(mods)
        + ", key = "
        + lua_str(key)
        + ', state = "down", window = '
        + lua_str(window)
        + " })"
    )
    up = (
        "hl.dsp.send_key_state({ mods = "
        + lua_str(mods)
        + ", key = "
        + lua_str(key)
        + ', state = "up", window = '
        + lua_str(window)
        + " })"
    )
    if hyprctl_dispatch_expr(down):
        time.sleep(0.05)
        return hyprctl_dispatch_expr(up)
    return hyprctl_dispatch_expr(
        "hl.dsp.send_shortcut({ mods = "
        + lua_str(mods)
        + ", key = "
        + lua_str(key)
        + ", window = "
        + lua_str(window)
        + " })"
    )


def _dispatch_hypr_sync(dispatcher, arg=""):
    dispatcher = str(dispatcher or "")
    arg = str(arg or "")
    if dispatcher == "exec":
        dispatch_exec(arg)
        return
    if dispatcher == "lua":
        if arg:
            hyprctl_dispatch_expr(arg)
        return
    if dispatcher == "sendshortcut":
        dispatch_sendshortcut(arg)
        return
    if dispatcher == "":
        return
    if arg.lstrip().startswith("hl.dsp.") or dispatcher.startswith("hl.dsp."):
        hyprctl_dispatch_expr(arg or dispatcher)
        return
    if arg:
        dispatch_exec(arg)


def dispatch_hypr(dispatcher, arg=""):
    threading.Thread(
        target=_dispatch_hypr_sync,
        args=(str(dispatcher or ""), str(arg or "")),
        daemon=True,
    ).start()


def run_binding(spec, wait=False):
    if isinstance(spec, dict):
        dispatcher = spec.get("dispatcher") or ""
        arg = spec.get("arg") or ""
        if wait:
            _dispatch_hypr_sync(dispatcher, arg)
        else:
            dispatch_hypr(dispatcher, arg)
        return
    argv = ACTIONS.get(str(spec))
    if argv:
        _spawn(argv)


def device_name(fd):
    buf = array.array("B", [0] * 256)
    fcntl.ioctl(fd, EVIOCGNAME, buf)
    return bytes(buf).split(b"\x00", 1)[0].decode("utf-8", "replace")


def evbit(fd, ev, length=64):
    buf = array.array("B", [0] * length)
    fcntl.ioctl(fd, _ior(0x20 + ev, length), buf)
    return int.from_bytes(buf.tobytes(), "little")


def parse_sysfs_bitmap(text):
    mask = 0
    for part in text.split():
        mask = (mask << 64) | int(part, 16)
    return mask


def skip_device_name(name):
    if not name or name == VIRTUAL_NAME:
        return True
    lowered = name.lower()
    return any(part in lowered for part in SKIP_NAME_PARTS)


def looks_like_wheel_mouse(name, rel_mask):
    if skip_device_name(name):
        return False
    has_move = bool(rel_mask & (1 << REL_X))
    has_wheel = bool(rel_mask & ((1 << REL_WHEEL) | (1 << REL_WHEEL_HI_RES)))
    return has_move and has_wheel


def sysfs_caps(event_path):
    sysdev = Path("/sys/class/input") / Path(event_path).name / "device"
    try:
        name = (sysdev / "name").read_text(encoding="utf-8", errors="replace").strip()
        rel = parse_sysfs_bitmap((sysdev / "capabilities" / "rel").read_text())
        key = parse_sysfs_bitmap((sysdev / "capabilities" / "key").read_text())
        return name, rel, key
    except (OSError, ValueError):
        return None, 0, 0


def is_mouse_path(path):
    name, rel, _key = sysfs_caps(path)
    if name is None:
        return False
    return looks_like_wheel_mouse(name, rel)


def list_mice():
    """Wheel mice, preferring ones with extra buttons when any exist.

    Keyboard dongles and Bluetooth keyboard-mice often expose a 3-button
    pointer. Grabbing those together with a real mouse merges jitter and
    reconnect storms into the cursor. Sysfs is used so the scan never
    opens /dev/input/event* (those opens can block in RCU on BT/USB).
    """
    candidates = []
    for path in sorted(Path("/dev/input").glob("event*")):
        name, rel, key = sysfs_caps(path)
        if name is None or not looks_like_wheel_mouse(name, rel):
            continue
        extra = bool(key & EXTRA_BUTTON_MASK)
        candidates.append((path, extra))
    primaries = [path for path, extra in candidates if extra]
    chosen = primaries or [path for path, _extra in candidates]
    return chosen


def bits_set(mask):
    code = 0
    while mask:
        if mask & 1:
            yield code
        mask >>= 1
        code += 1


def key_label(code):
    if code in BTN_LABELS:
        return BTN_LABELS[code]
    if 0x110 <= code <= 0x11f:
        return f"mouse-btn-{code - 0x110}"
    return f"key-{code}"


def pack_event(etype, code, value):
    now = time.time()
    sec = int(now)
    usec = int((now - sec) * 1_000_000)
    return struct.pack(EVENT_FMT, sec, usec, etype, code, int(value))


class UInput:
    def __init__(self, source_fds=None):
        # Blocking writes: drop-on-EAGAIN is what made motion stutter.
        self.fd = os.open("/dev/uinput", os.O_WRONLY)
        for ev in (EV_SYN, EV_KEY, EV_REL, EV_MSC):
            fcntl.ioctl(self.fd, UI_SET_EVBIT, ev)
        for code in range(0, 256):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        for code in range(0x100, 0x130):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        for src in source_fds or []:
            try:
                for code in bits_set(evbit(src, EV_KEY, 256)):
                    fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
            except OSError:
                pass
        for code in (
            REL_X,
            REL_Y,
            REL_WHEEL,
            REL_HWHEEL,
            REL_WHEEL_HI_RES,
            REL_HWHEEL_HI_RES,
        ):
            fcntl.ioctl(self.fd, UI_SET_RELBIT, code)
        fcntl.ioctl(self.fd, UI_SET_MSCBIT, MSC_SCAN)
        fcntl.ioctl(self.fd, UI_SET_PROPBIT, INPUT_PROP_POINTER)
        setup = struct.pack("HHHH80sI", 0x03, 0x0001, 0x0001, 1, VIRTUAL_NAME.encode().ljust(80, b"\x00"), 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.05)

    def write(self, etype, code, value):
        self.write_bytes(pack_event(etype, code, value))

    def write_bytes(self, data):
        view = memoryview(data)
        while view:
            try:
                n = os.write(self.fd, view)
            except InterruptedError:
                continue
            if n <= 0:
                break
            view = view[n:]

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
        self.dead = False

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
        self.tilt_acc = 0
        self.swallowed_keys = set()
        self._update_thread = None
        self._update_ready = False
        self._started_at = time.monotonic()
        self._last_update_check = 0.0
        self._add_q = queue.SimpleQueue()
        self._drop_q = queue.SimpleQueue()
        self._unwanted = frozenset()
        self._watch_thread = None
        self._last_names = None

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

    def bindings(self):
        return self.smoother.cfg.get("bindings") or {}

    def capture_learn(self, code, label):
        try:
            st = LEARN_PATH.stat()
            raw = LEARN_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if raw != "wait":
            return False
        if time.time() - st.st_mtime > LEARN_MAX_AGE:
            expire_learn(0)
            return False
        payload = json.dumps({"code": str(code), "label": label})
        LEARN_PATH.write_text(payload + "\n", encoding="utf-8")
        return True

    def on_key(self, code, value):
        if value == 1:
            if code not in SKIP_LEARN and self.capture_learn(code, key_label(code)):
                self.swallowed_keys.add(code)
                return True
            action = self.bindings().get(str(code))
            if action:
                run_binding(action)
                self.swallowed_keys.add(code)
                return True
            return False
        if value == 0 and code in self.swallowed_keys:
            self.swallowed_keys.discard(code)
            return True
        return False

    def on_tilt(self, hires):
        if abs(hires) >= 60 and self.capture_learn(
            "tilt-left" if hires < 0 else "tilt-right",
            "wheel tilt left" if hires < 0 else "wheel tilt right",
        ):
            return True
        direction = "tilt-right" if hires > 0 else "tilt-left"
        action = self.bindings().get(direction)
        if not action:
            return False
        self.tilt_acc += hires
        step = 120 if self.tilt_acc > 0 else -120
        while abs(self.tilt_acc) >= 120:
            run_binding(action)
            self.tilt_acc -= step
        return True

    def _apply_timer_slack(self):
        try:
            ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_TIMERSLACK, 1000, 0, 0, 0)
        except OSError:
            pass

    def _watch_loop(self):
        grabbed_paths = set()
        fail_until = {}
        while self.running:
            while True:
                try:
                    mouse = self._drop_q.get_nowait()
                except queue.Empty:
                    break
                grabbed_paths.discard(mouse.path)
                fail_until[mouse.path] = time.monotonic() + 1.5
                mouse.ungrab()
            self.smoother.reload()
            enabled = bool(self.smoother.cfg.get("enabled", True))
            if enabled:
                try:
                    paths = [str(p) for p in list_mice()]
                except OSError as exc:
                    self.log(f"scan failed: {exc}")
                    paths = []
                wanted = set(paths)
                self._unwanted = frozenset(grabbed_paths - wanted)
                now = time.monotonic()
                for path in paths:
                    if path in grabbed_paths:
                        continue
                    if fail_until.get(path, 0) > now:
                        continue
                    try:
                        mouse = GrabbedMouse(path)
                    except OSError as exc:
                        self.log(f"grab failed {path}: {exc}")
                        fail_until[path] = now + 3.0
                        continue
                    grabbed_paths.add(path)
                    self._add_q.put(mouse)
            else:
                self._unwanted = frozenset(grabbed_paths)
            time.sleep(1.0)
        while True:
            try:
                mouse = self._drop_q.get_nowait()
            except queue.Empty:
                break
            mouse.ungrab()

    def _collect_mice(self):
        enabled = bool(self.smoother.cfg["enabled"])
        unwanted = self._unwanted
        if enabled:
            self.set_hypr_natural(False)
        else:
            self.set_hypr_natural(bool(self.smoother.cfg["natural"]))
            self.smoother.vy = self.smoother.vx = 0.0
        while True:
            try:
                mouse = self._add_q.get_nowait()
            except queue.Empty:
                break
            if enabled:
                self.mice.append(mouse)
            else:
                self._drop_q.put(mouse)
        keep = []
        for mouse in self.mice:
            if (not enabled) or mouse.dead or mouse.fd < 0 or mouse.path in unwanted:
                self._drop_q.put(mouse)
            else:
                keep.append(mouse)
        self.mice = keep
        self.active = bool(self.mice) and enabled
        names = tuple(m.name for m in self.mice)
        if names != self._last_names:
            prev = self._last_names
            self._last_names = names
            if names:
                self.log(f"active on {', '.join(names)}")
            elif prev:
                self.log("idle")

    def stop_grab(self):
        for mouse in self.mice:
            self._drop_q.put(mouse)
        self.mice = []
        self.active = False
        self.smoother.vy = self.smoother.vx = 0.0
        self.set_hypr_natural(bool(self.smoother.cfg["natural"]))

    def shutdown(self):
        self.running = False
        if self._watch_thread is not None and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=2.5)
        for mouse in self.mice:
            mouse.ungrab()
        self.mice = []
        while True:
            try:
                self._add_q.get_nowait().ungrab()
            except queue.Empty:
                break
        while True:
            try:
                self._drop_q.get_nowait().ungrab()
            except queue.Empty:
                break
        if self.ui:
            self.ui.close()
            self.ui = None

    def handle_device(self, mouse: GrabbedMouse):
        try:
            data = os.read(mouse.fd, EVENT_SIZE * 64)
        except BlockingIOError:
            return
        except OSError:
            mouse.dead = True
            return
        if not data:
            mouse.dead = True
            return
        out = bytearray()
        unpack = struct.unpack_from
        for offset in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
            _sec, _usec, etype, code, value = unpack(EVENT_FMT, data, offset)
            if etype == EV_KEY and self.on_key(code, value):
                continue
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
                if hires_x and self.on_tilt(hires_x):
                    hires_x = 0
                if hires_y or hires_x:
                    self.smoother.impulse(hires_y, hires_x, time.monotonic())
                mouse.wheel = mouse.hires = mouse.hwheel = mouse.hhires = 0
            elif etype == EV_SYN and code == SYN_DROPPED:
                mouse.wheel = mouse.hires = mouse.hwheel = mouse.hhires = 0
                continue
            out += data[offset:offset + EVENT_SIZE]
        if out and self.ui:
            try:
                self.ui.write_bytes(out)
            except OSError:
                mouse.dead = True

    def kick_update(self):
        if not self.smoother.cfg.get("auto_update", True):
            return
        if self._update_thread and self._update_thread.is_alive():
            return

        def worker():
            if try_auto_update():
                self._update_ready = True

        self._update_thread = threading.Thread(target=worker, daemon=True)
        self._update_thread.start()

    def apply_update_if_ready(self):
        if not self._update_ready:
            return
        self.log("updated from GitHub; restarting")
        _spawn(["notify-send", "-a", "Smooth Scroll", "Smooth Scroll", "Updated from GitHub"])
        _spawn([f"{OMARCHY_BIN}/omarchy-shell", "shell", "rescanPlugins"])
        self.shutdown()
        restart_daemon()

    def loop(self):
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "running", False))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "running", False))
        self._apply_timer_slack()
        try:
            self.ui = UInput()
        except OSError as exc:
            self.log(f"uinput failed: {exc}")
            return
        self._watch_thread = threading.Thread(
            target=self._watch_loop, daemon=True, name="smooth-scroll-devices"
        )
        self._watch_thread.start()
        last = time.monotonic()
        last_reload = 0.0
        while self.running:
            now = time.monotonic()
            if now - last_reload >= 0.2:
                last_reload = now
                self.smoother.reload()
                expire_learn()
            self._collect_mice()
            if self.smoother.cfg.get("auto_update", True):
                if self._last_update_check == 0:
                    if now - self._started_at >= UPDATE_FIRST_DELAY:
                        self._last_update_check = now
                        self.kick_update()
                elif now - self._last_update_check >= UPDATE_INTERVAL:
                    self._last_update_check = now
                    self.kick_update()
            self.apply_update_if_ready()
            timeout = 0.008
            fds = [m.fd for m in self.mice if m.fd >= 0]
            if fds:
                try:
                    readable, _, errored = select.select(fds, [], fds, timeout)
                except OSError:
                    for mouse in self.mice:
                        if mouse.fd < 0:
                            mouse.dead = True
                    continue
                dead = set(errored)
                for mouse in self.mice:
                    if mouse.fd in dead:
                        mouse.dead = True
                        continue
                    if mouse.fd in readable:
                        self.handle_device(mouse)
            else:
                time.sleep(timeout)
            now = time.monotonic()
            dt = now - last
            last = now
            if self.active and self.ui:
                chunks = self.smoother.step(dt)
                if chunks:
                    for code, value in chunks:
                        if value:
                            self.ui.write(EV_REL, code, value)
                    self.ui.syn()
        self.shutdown()


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


def cmd_bind(args):
    if len(args) < 2:
        print("usage: daemon.py bind <code> <action>", file=sys.stderr)
        sys.exit(2)
    code, action = str(args[0]), str(args[1])
    cfg = load_config()
    bindings = dict(cfg.get("bindings") or {})
    if action == "none":
        bindings.pop(code, None)
    elif action.startswith("{"):
        try:
            rec = json.loads(action)
        except json.JSONDecodeError:
            print("invalid shortcut json", file=sys.stderr)
            sys.exit(2)
        if not isinstance(rec, dict):
            print("invalid shortcut json", file=sys.stderr)
            sys.exit(2)
        rec["kind"] = "shortcut"
        bindings[code] = rec
    elif action in ACTIONS:
        bindings[code] = action
    else:
        print(f"unknown action: {action}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(save_config({"bindings": bindings})))


def cmd_shortcuts():
    subprocess.run(
        [f"{OMARCHY_BIN}/omarchy-menu-keybindings", "--print"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    cache_dir = Path(os.environ.get("XDG_CACHE_HOME") or (HOME / ".cache")) / "omarchy"
    files = sorted(cache_dir.glob("keybindings-*.records"), key=lambda p: p.stat().st_mtime, reverse=True)
    rows = []
    if files:
        for line in files[0].read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("\t", 2)
            if len(parts) < 2:
                continue
            display, dispatcher = parts[0], parts[1]
            arg = parts[2] if len(parts) > 2 else ""
            if not dispatcher.strip():
                continue
            if "→" in display:
                keys, desc = display.split("→", 1)
            else:
                keys, desc = display, ""
            keys, desc = " ".join(keys.split()), desc.strip()
            label = f"{keys} → {desc}" if desc else keys
            rows.append(
                {
                    "value": json.dumps(
                        {
                            "kind": "shortcut",
                            "dispatcher": dispatcher,
                            "arg": arg,
                            "label": label,
                        },
                        separators=(",", ":"),
                    ),
                    "label": keys,
                    "description": desc,
                }
            )
    print(json.dumps(rows))


def cmd_dispatch(args):
    if not args:
        print("usage: daemon.py dispatch <exec|lua|sendshortcut> [arg...]", file=sys.stderr)
        sys.exit(2)
    _dispatch_hypr_sync(args[0], " ".join(args[1:]))


def cmd_fire(code):
    spec = (load_config().get("bindings") or {}).get(str(code))
    if not spec:
        print(f"no binding for {code}", file=sys.stderr)
        sys.exit(1)
    run_binding(spec, wait=True)


def cmd_learn(seconds="15"):
    seconds = float(seconds)

    def cleanup(*_):
        try:
            LEARN_PATH.unlink()
        except OSError:
            pass

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(1))
    LEARN_PATH.write_text("wait\n", encoding="utf-8")
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(0.08)
            try:
                raw = LEARN_PATH.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if raw.startswith("{"):
                print(raw)
                return
        print("timeout", file=sys.stderr)
        sys.exit(1)
    finally:
        cleanup()


def cmd_set(args):
    if len(args) < 2:
        print("usage: daemon.py set <enabled|natural|damping|acceleration|auto_update> <value>", file=sys.stderr)
        sys.exit(2)
    key, raw = args[0], args[1]
    if key not in DEFAULTS or key == "bindings":
        print(f"unknown key: {key}", file=sys.stderr)
        sys.exit(2)
    if key in ("enabled", "natural", "auto_update"):
        value = raw.lower() in ("1", "true", "yes", "on")
    else:
        value = int(raw)
    cfg = save_config({key: value})
    print(json.dumps(cfg))


def cmd_list():
    for path in list_mice():
        name, _rel, _key = sysfs_caps(path)
        print(f"{path}  {name}")


def _find_named_device(name):
    for path in sorted(Path("/dev/input").glob("event*")):
        try:
            fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            if device_name(fd) == name:
                return path, fd
        except OSError:
            os.close(fd)
            continue
        os.close(fd)
    return None, None


def cmd_caps():
    for path in list_mice():
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
        try:
            print(f"{path}  {device_name(fd)}")
            keys = list(bits_set(evbit(fd, EV_KEY, 256)))
            rels = list(bits_set(evbit(fd, EV_REL, 16)))
            btns = [c for c in keys if 0x110 <= c <= 0x11f]
            print("  mouse buttons:", ", ".join(f"{key_label(c)} ({c})" for c in btns) or "(none)")
            print("  rel axes:", ", ".join(str(c) for c in rels))
        finally:
            os.close(fd)


def cmd_probe(seconds=12):
    seconds = float(seconds)
    path, fd = _find_named_device(VIRTUAL_NAME)
    source = "virtual (daemon running)"
    if fd is None:
        mice = list_mice()
        if not mice:
            print("no mouse found", file=sys.stderr)
            sys.exit(1)
        path = mice[0]
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
        source = f"physical {device_name(fd)}"
    print(f"listening on {path}  [{source}]")
    print(f"press each extra button within {int(seconds)}s …")
    deadline = time.monotonic() + seconds
    seen = {}
    try:
        while time.monotonic() < deadline:
            remain = deadline - time.monotonic()
            readable, _, _ = select.select([fd], [], [], max(0.05, remain))
            if not readable:
                continue
            try:
                data = os.read(fd, EVENT_SIZE * 32)
            except BlockingIOError:
                continue
            for offset in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                _s, _u, etype, code, value = struct.unpack_from(EVENT_FMT, data, offset)
                if etype == EV_KEY and value:
                    label = key_label(code)
                    seen[code] = label
                    print(f"  press  {label:24}  code={code}")
                elif etype == EV_REL and code in (REL_HWHEEL, REL_HWHEEL_HI_RES) and value:
                    label = "wheel-tilt" if code == REL_HWHEEL else "wheel-tilt-hires"
                    seen[code] = label
                    print(f"  axis   {label:24}  code={code} value={value}")
    finally:
        os.close(fd)
    if not seen:
        print("no extra presses captured")
        return
    print("unique:")
    for code, label in seen.items():
        print(f"  {label} ({code})")


def main():
    ensure_path()
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
    elif cmd == "bind":
        cmd_bind(argv[1:])
    elif cmd == "shortcuts":
        cmd_shortcuts()
    elif cmd == "learn":
        cmd_learn(argv[1] if len(argv) > 1 else "15")
    elif cmd == "list":
        cmd_list()
    elif cmd == "caps":
        cmd_caps()
    elif cmd == "probe":
        cmd_probe(argv[1] if len(argv) > 1 else 12)
    elif cmd == "dispatch":
        cmd_dispatch(argv[1:])
    elif cmd == "fire":
        if len(argv) < 2:
            print("usage: daemon.py fire <code>", file=sys.stderr)
            sys.exit(2)
        cmd_fire(argv[1])
    elif cmd in ("-h", "--help"):
        print("usage: daemon.py [get|set KEY VALUE|bind CODE ACTION|shortcuts|dispatch KIND ARG|fire CODE|learn|list|caps|probe]")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
