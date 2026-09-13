#!/data/data/com.termux/files/usr/bin/bash
#
# termux_listener.sh — SentinelEdge SMS trigger listener
#
# Run this script once inside Termux on your Android phone.
# It watches /sdcard/send_sms_*.txt every 2 seconds.
# For each matching file it reads the phone number and message,
# sends the SMS via termux-sms-send, then deletes the file.
#
# Using per-file unique names (send_sms_TIMESTAMP_PHONE.txt) means
# multiple simultaneous alerts never overwrite each other.
#
# Setup (one-time):
#   1. Install Termux from F-Droid (https://f-droid.org/packages/com.termux/)
#   2. Install Termux:API add-on from F-Droid
#   3. Inside Termux:
#        pkg install termux-api
#        termux-setup-storage        # grant storage permission when prompted
#   4. Push this script via ADB from your PC:
#        adb push termux_listener.sh /sdcard/termux_listener.sh
#   5. In Termux, copy to home and start the listener:
#        cp ~/storage/shared/termux_listener.sh ~/sms_listener.sh
#        nohup ~/sms_listener.sh &
#
# Auto-start on reboot (requires Termux:Boot from F-Droid):
#   mkdir -p ~/.termux/boot
#   cp ~/sms_listener.sh ~/.termux/boot/sms_listener.sh
#
# To stop the listener:
#   kill %1   (or close Termux)
#

echo "[SentinelEdge] Termux SMS listener started. Watching for send_sms_*.txt..."

while true; do
  for f in ~/storage/shared/send_sms_*.txt; do
    # Guard: skip if glob matched nothing (literal string with *)
    [ -f "$f" ] || continue

    number=$(sed -n '1p' "$f")
    message=$(sed -n '2p' "$f")

    echo "[SentinelEdge] Sending SMS to $number (file: $(basename $f))..."
    termux-sms-send -n "$number" "$message"

    rm "$f"
    echo "[SentinelEdge] Done. Trigger file deleted: $(basename $f)"
  done
  sleep 2
done
