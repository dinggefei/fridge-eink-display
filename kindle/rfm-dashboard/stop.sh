#!/bin/sh
set -u

RFM_DASHBOARD_DIR="${RFM_DASHBOARD_DIR:-/mnt/us/rfm-dashboard}"
# shellcheck source=/dev/null
. "${RFM_DASHBOARD_DIR}/runtime.sh"

# Recover the native UI first. This also makes the stop action useful as a
# rescue entry after an interrupted dashboard start.
rfm_set_window_manager resume

dashboard_pid="$(rfm_read_pid 2>/dev/null || true)"
if [ -n "${dashboard_pid}" ] && rfm_pid_is_dashboard "${dashboard_pid}"; then
    kill -TERM "${dashboard_pid}" 2>/dev/null || true
    attempt=0
    while [ "${attempt}" -lt 10 ] && kill -0 "${dashboard_pid}" 2>/dev/null; do
        sleep 1
        attempt=$((attempt + 1))
    done
    if kill -0 "${dashboard_pid}" 2>/dev/null; then
        kill -KILL "${dashboard_pid}" 2>/dev/null || true
    fi
fi

rm -f "${RFM_PID_FILE}"
rfm_set_keep_awake 0
rfm_set_status_bar enable
exit 0
