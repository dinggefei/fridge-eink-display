# Copy this file to /mnt/us/rfm-dashboard/config.sh and fill in all values.
# Do not commit the configured file; it contains the per-device secret.
BASE_URL="https://your-refrigerator-service.example.com"
DEVICE_CODE="rfm-device-code"
DEVICE_SECRET="replace-with-device-secret"
POLL_SECONDS="300"
# Keep the dashboard visible instead of allowing the normal Kindle screensaver
# to cover it. RFM Stop Dashboard restores the standard power setting.
KEEP_AWAKE="1"
# Hide the native Kindle time/Wi-Fi status bar while the dashboard is active.
HIDE_STATUS_BAR="1"
# Firmware 5.7.2 and newer redraws the clock even when Pillow is hidden. Pause
# the native window manager while the dashboard is active. The bundled power
# button watcher makes a short power-button press stop the dashboard and
# restore the Kindle UI.
PAUSE_WINDOW_MANAGER="1"
POWER_BUTTON_EXIT="1"
