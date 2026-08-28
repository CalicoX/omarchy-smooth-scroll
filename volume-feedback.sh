#!/usr/bin/env bash
# Adjust Omarchy output volume, then play the desktop volume-change tick
# at the new loudness. Rapid repeats replace the previous player.
set -euo pipefail

action="${1:-}"
if [[ -z $action ]]; then
  echo "usage: volume-feedback.sh <raise|lower|mute-toggle|+N|-N>" >&2
  exit 2
fi

/usr/bin/omarchy-audio-output-volume "$action"

sink="$(omarchy-audio-output-sink 2>/dev/null || true)"
if [[ -n $sink ]]; then
  mute="$(pactl get-sink-mute "$sink" 2>/dev/null || true)"
  percent="$(
    pactl get-sink-volume "$sink" 2>/dev/null |
      awk 'NR == 1 {
        for (i = 1; i <= NF; i++)
          if ($i ~ /%$/) { sub("%", "", $i); print $i; exit }
      }'
  )"
  if [[ $mute == *yes* ]] || [[ ${percent:-0} -eq 0 ]]; then
    exit 0
  fi
fi

sound="${OMARCHY_VOLUME_SOUND:-/usr/share/sounds/freedesktop/stereo/audio-volume-change.oga}"
runtime="${XDG_RUNTIME_DIR:-/tmp}"
pidfile="$runtime/stillpilot-volume-tick.pid"

if [[ -f $pidfile ]]; then
  old="$(cat "$pidfile" 2>/dev/null || true)"
  if [[ -n ${old:-} ]]; then
    kill "$old" 2>/dev/null || true
  fi
fi

play() {
  if command -v pw-play >/dev/null 2>&1 && [[ -f $sound ]]; then
    exec pw-play "$sound"
  fi
  if command -v paplay >/dev/null 2>&1 && [[ -f $sound ]]; then
    exec paplay "$sound"
  fi
  if command -v canberra-gtk-play >/dev/null 2>&1; then
    exec canberra-gtk-play -i audio-volume-change
  fi
  if command -v mpv >/dev/null 2>&1 && [[ -f $sound ]]; then
    exec mpv --no-video --really-quiet "$sound"
  fi
  exit 0
}

play >/dev/null 2>&1 &
echo $! >"$pidfile"
