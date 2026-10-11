#!/bin/sh
set -u

RFM_DASHBOARD_DIR="${RFM_DASHBOARD_DIR:-/mnt/us/rfm-dashboard}"
# shellcheck source=/dev/null
. "${RFM_DASHBOARD_DIR}/runtime.sh"

mkdir -p "${RFM_STATE_DIR}" || exit 1

existing_pid="$(rfm_read_pid 2>/dev/null || true)"
if [ -n "${existing_pid}" ] && rfm_pid_is_dashboard "${existing_pid}"; then
    # A second tap is an explicit request to refresh now (for example, after a
    # display-mode change). USR1 interrupts only the daemon's polling sleep.
    kill -USR1 "${existing_pid}" 2>/dev/null || exit 1
    exit 0
fi

# Discard a stale PID before starting. The subshell plus ignored HUP lets the
# worker survive the Scriptlet launcher returning to the Kindle library.
rm -f "${RFM_PID_FILE}"
(
    trap '' HUP
    RFM_DASHBOARD_DIR="${RFM_DASHBOARD_DIR}" \
    RFM_START_DELAY_SECONDS="${RFM_START_DELAY_SECONDS:-8}" \
        sh "${RFM_DAEMON_SCRIPT}" \
        >> "${RFM_STATE_DIR}/daemon.log" 2>&1 </dev/null &
)

# Confirm that the daemon reached its PID-file checkpoint. Keep this bounded so
# the Scriptlet always gives control back to the Kindle UI.
attempt=0
while [ "${attempt}" -lt 20 ]; do
    started_pid="$(rfm_read_pid 2>/dev/null || true)"
    if [ -n "${started_pid}" ] && rfm_pid_is_dashboard "${started_pid}"; then
        exit 0
    fi
    sleep 1
    attempt=$((attempt + 1))
done

exit 1
