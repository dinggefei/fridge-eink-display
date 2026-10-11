#!/bin/sh
set -u

# Ignore the Scriptlet launcher's hangup after it returns to the library.
trap '' HUP

RFM_DASHBOARD_DIR="${RFM_DASHBOARD_DIR:-/mnt/us/rfm-dashboard}"
RFM_CONFIG_FILE="${RFM_DASHBOARD_DIR}/config.sh"
RFM_REFRESH_SCRIPT="${RFM_DASHBOARD_DIR}/refresh.sh"
# shellcheck source=/dev/null
. "${RFM_DASHBOARD_DIR}/runtime.sh"

[ -r "${RFM_CONFIG_FILE}" ] || exit 1
[ -r "${RFM_REFRESH_SCRIPT}" ] || exit 1
# shellcheck source=/dev/null
. "${RFM_CONFIG_FILE}"

POLL_SECONDS="${POLL_SECONDS:-300}"
KEEP_AWAKE="${KEEP_AWAKE:-1}"
HIDE_STATUS_BAR="${HIDE_STATUS_BAR:-1}"
PAUSE_WINDOW_MANAGER="${PAUSE_WINDOW_MANAGER:-1}"
POWER_BUTTON_EXIT="${POWER_BUTTON_EXIT:-1}"
POWER_BUTTON_WATCHER="${RFM_POWER_BUTTON_WATCHER:-${RFM_DASHBOARD_DIR}/bin/rfm-power-button-exit}"
START_DELAY_SECONDS="${RFM_START_DELAY_SECONDS:-8}"
case "${POLL_SECONDS}" in
    ''|*[!0-9]*) exit 1 ;;
esac
[ "${POLL_SECONDS}" -ge 30 ] || POLL_SECONDS=30
case "${START_DELAY_SECONDS}" in
    ''|*[!0-9]*) START_DELAY_SECONDS=8 ;;
esac

mkdir -p "${RFM_STATE_DIR}" || exit 1

existing_pid="$(rfm_read_pid 2>/dev/null || true)"
if [ -n "${existing_pid}" ] && [ "${existing_pid}" != "$$" ] \
    && rfm_pid_is_dashboard "${existing_pid}"; then
    exit 0
fi

pid_tmp="${RFM_PID_FILE}.tmp.$$"
printf '%s\n' "$$" > "${pid_tmp}" || exit 1
mv "${pid_tmp}" "${RFM_PID_FILE}" || exit 1

sleep_pid=""
refresh_pid=""
power_watcher_pid=""
refresh_requested=0
cleanup_done=0

cleanup() {
    [ "${cleanup_done}" = "0" ] || return 0
    cleanup_done=1
    [ -n "${sleep_pid}" ] && kill "${sleep_pid}" 2>/dev/null || true
    [ -n "${refresh_pid}" ] && kill "${refresh_pid}" 2>/dev/null || true
    [ -n "${power_watcher_pid}" ] && kill "${power_watcher_pid}" 2>/dev/null || true
    # Resume the native UI before restoring its chrome and power policy. This
    # is deliberately safe to call even if Awesome was never paused.
    [ "${PAUSE_WINDOW_MANAGER}" = "1" ] && rfm_set_window_manager resume
    recorded_pid="$(rfm_read_pid 2>/dev/null || true)"
    if [ "${recorded_pid}" = "$$" ]; then
        rm -f "${RFM_PID_FILE}"
    fi
    [ "${KEEP_AWAKE}" = "1" ] && rfm_set_keep_awake 0
    [ "${HIDE_STATUS_BAR}" = "1" ] && rfm_set_status_bar enable
}

start_power_button_watcher() {
    [ "${POWER_BUTTON_EXIT}" = "1" ] || return 1
    [ -x "${POWER_BUTTON_WATCHER}" ] || return 1
    "${POWER_BUTTON_WATCHER}" "$$" \
        >> "${RFM_STATE_DIR}/power-button.log" 2>&1 &
    power_watcher_pid=$!
    kill -0 "${power_watcher_pid}" 2>/dev/null || {
        power_watcher_pid=""
        return 1
    }
    return 0
}

terminate() {
    cleanup
    exit 0
}

request_refresh() {
    refresh_requested=1
    if [ -n "${sleep_pid}" ]; then
        kill "${sleep_pid}" 2>/dev/null || true
    fi
}

wait_for_launcher() {
    if [ "${START_DELAY_SECONDS}" -gt 0 ]; then
        # A Scriptlet redraws the native Kindle UI as it closes. Delay our
        # framebuffer update until that redraw has completed, including when
        # an already-running daemon receives an explicit refresh request.
        sleep "${START_DELAY_SECONDS}" &
        sleep_pid=$!
        wait "${sleep_pid}" 2>/dev/null || true
        sleep_pid=""
    fi
}

trap terminate TERM INT
trap request_refresh USR1
trap cleanup EXIT

[ "${KEEP_AWAKE}" = "1" ] && rfm_set_keep_awake 1
[ "${HIDE_STATUS_BAR}" = "1" ] && rfm_set_status_bar disable

wait_for_launcher

if [ "${PAUSE_WINDOW_MANAGER}" = "1" ]; then
    if start_power_button_watcher; then
        # On Kindle firmware >= 5.7.2, Pillow alone cannot stop the clock from
        # repainting. Pause Awesome only after the Scriptlet has returned and
        # the independent power-button recovery watcher is running.
        rfm_set_window_manager pause
    else
        printf '%s\n' \
            "window manager left active: power-button recovery unavailable" \
            >> "${RFM_STATE_DIR}/daemon.log"
        PAUSE_WINDOW_MANAGER=0
    fi
fi

while true; do
    refresh_requested=0
    RFM_DASHBOARD_DIR="${RFM_DASHBOARD_DIR}" \
    RFM_PREVIEW_SECONDS=0 \
    RFM_ERROR_DISPLAY_SECONDS=0 \
        sh "${RFM_REFRESH_SCRIPT}" &
    refresh_pid=$!
    wait "${refresh_pid}" || true
    refresh_pid=""

    # If a tap requested a refresh while a download was already in progress,
    # wait for that Scriptlet to close before performing one more pass.
    if [ "${refresh_requested}" = "1" ]; then
        refresh_requested=0
        wait_for_launcher
        continue
    fi

    sleep "${POLL_SECONDS}" &
    sleep_pid=$!
    wait "${sleep_pid}" 2>/dev/null || true
    sleep_pid=""
    if [ "${refresh_requested}" = "1" ]; then
        refresh_requested=0
        wait_for_launcher
    fi
done
