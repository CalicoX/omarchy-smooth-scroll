#!/usr/bin/env bash
# Idempotent installer for the stillpilot.smooth-scroll daemon.
# Called by the bar panel on first load (--ensure) and by users after
# `omarchy plugin add`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENSURE=0
if [[ ${1:-} == --ensure ]]; then
  ENSURE=1
fi

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/stillpilot-smooth-scroll.service"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/smooth-scroll.json"
MENU="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/extensions/omarchy-menu.jsonc"

mkdir -p "$UNIT_DIR" "$(dirname "$CONFIG")" "$(dirname "$MENU")"

if [[ ! -f $CONFIG ]]; then
  cat >"$CONFIG" <<'EOF'
{
  "enabled": true,
  "natural": true,
  "damping": 65,
  "acceleration": 35
}
EOF
fi

cat >"$UNIT" <<EOF
[Unit]
Description=Omarchy smooth mouse-wheel scrolling
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $ROOT/daemon.py
Restart=on-failure
RestartSec=1
Environment=XDG_RUNTIME_DIR=%t

[Install]
WantedBy=graphical-session.target
EOF

systemctl --user daemon-reload >/dev/null
systemctl --user enable stillpilot-smooth-scroll.service >/dev/null
systemctl --user start stillpilot-smooth-scroll.service >/dev/null || true

if [[ -f $MENU ]] && ! grep -q 'setup.smooth-scroll' "$MENU" 2>/dev/null; then
  python3 - "$MENU" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
snippet = '''  "setup.smooth-scroll": {
    "icon": "󰍽",
    "label": "Smooth Scroll",
    "description": "Mouse wheel smoothing, direction, damping, acceleration",
    "action": "omarchy-shell stillpilot.smooth-scroll toggle"
  }
'''
idx = text.rfind("}")
if idx == -1:
    sys.exit(0)
# Insert before the last closing brace, adding a comma after the previous entry.
head, tail = text[:idx].rstrip(), text[idx:]
if head.rstrip().endswith(","):
    new = head + "\n" + snippet + tail
elif head.rstrip().endswith("{"):
    new = head + "\n" + snippet + tail
else:
    new = head + ",\n" + snippet + tail
path.write_text(new, encoding="utf-8")
PY
fi

if (( ! ENSURE )); then
  echo "Smooth Scroll daemon enabled for this session and future logins."
  echo "Place the bar widget with:  omarchy plugin enable stillpilot.smooth-scroll --section right"
  if [[ ! -w /dev/uinput ]]; then
    echo
    echo "Cannot write /dev/uinput. Add your user to the input group, then log out:"
    echo "  sudo gpasswd -a \"$USER\" input"
  fi
fi
