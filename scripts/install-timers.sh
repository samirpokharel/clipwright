#!/usr/bin/env bash
# Install the autopilot's systemd user timers: publish-due every 15 minutes, produce nightly at 01:30.
# Persistent=true runs a missed timer when the laptop wakes. Remove with: scripts/install-timers.sh --remove
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HOME/.config/systemd/user"
UNITS=(clipwright-publish.service clipwright-publish.timer clipwright-produce.service clipwright-produce.timer)

if [ "${1:-}" = "--remove" ]; then
  systemctl --user disable --now clipwright-publish.timer clipwright-produce.timer 2>/dev/null || true
  for u in "${UNITS[@]}"; do rm -f "$DEST/$u"; done
  systemctl --user daemon-reload
  echo "Timers removed."
  exit 0
fi

mkdir -p "$DEST"
for u in "${UNITS[@]}"; do sed "s|__DIR__|$HERE|g" "$HERE/systemd/$u" > "$DEST/$u"; done
systemctl --user daemon-reload
systemctl --user enable --now clipwright-publish.timer clipwright-produce.timer
systemctl --user list-timers 'clipwright-*'
echo "Logs: journalctl --user -u clipwright-publish -u clipwright-produce"
