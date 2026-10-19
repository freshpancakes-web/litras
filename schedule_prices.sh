#!/bin/bash
# Installs a macOS background job that runs update_prices.py on weekdays at 10:30 and 15:00 (your Mac's local time).
# LEA collects prices at about 10:00 but may publish the file later, so the 15:00 run catches the same day's prices.
# Run it once from Terminal:   bash schedule_prices.sh
# Remove it later with:        bash schedule_prices.sh remove
#
# If the Mac is asleep at a run time, macOS runs the job when it wakes up.

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.fuelcalculator.updateprices"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$DIR/update_prices.log"

if [ "$1" = "remove" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed the weekday price update."
  exit 0
fi

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "python3 was not found. Install the Xcode Command Line Tools (run: xcode-select --install) and try again."
  exit 1
fi
if [ ! -f "$DIR/update_prices.py" ]; then
  echo "update_prices.py must be in the same folder as this script ($DIR)."
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DIR/update_prices.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Done. update_prices.py will run on weekdays at 10:30 and 15:00."
echo "Folder: $DIR"
echo "Log:    $LOG"
echo
echo "Check it now with:  launchctl start $LABEL   (then look at the log)"
