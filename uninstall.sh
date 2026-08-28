#!/usr/bin/env bash
# Stop the daemon. Does not remove the plugin files — use
# `omarchy plugin remove stillpilot.smooth-scroll` for that.
set -euo pipefail

systemctl --user disable --now stillpilot-smooth-scroll.service >/dev/null 2>&1 || true
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/stillpilot-smooth-scroll.service"
systemctl --user daemon-reload >/dev/null 2>&1 || true
echo "Smooth Scroll daemon stopped. Plugin files are unchanged."
echo "Remove the widget with: omarchy plugin remove stillpilot.smooth-scroll"
