#!/bin/sh

# Shared process helpers for the Kindle dashboard. This file is sourced by the
# start, daemon and stop scripts, so keep it compatible with BusyBox ash.

RFM_DASHBOARD_DIR="${RFM_DASHBOARD_DIR:-/mnt/us/rfm-dashboard}"
RFM_STATE_DIR="${RFM_DASHBOARD_DIR}/state"
RFM_PID_FILE="${RFM_STATE_DIR}/dashboard.pid"
RFM_DAEMON_SCRIPT="${RFM_DASHBOARD_DIR}/daemon.sh"

rfm_read_pid() {
    [ -r "${RFM_PID_FILE}" ] || return 1
    rfm_pid="$(sed -n '1p' "${RFM_PID_FILE}" 2>/dev/null)"
    case "${rfm_pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    printf '%s\n' "${rfm_pid}"
}

rfm_pid_is_dashboard() {
    rfm_check_pid="$1"
    case "${rfm_check_pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    kill -0 "${rfm_check_pid}" 2>/dev/null || return 1

    # On Kindle, protect against a stale PID file pointing at an unrelated
    # process after reboot. Other test hosts may not expose Linux /proc.
    if [ -r "/proc/${rfm_check_pid}/cmdline" ]; then
        tr '\000' ' ' < "/proc/${rfm_check_pid}/cmdline" \
            | grep -F "${RFM_DAEMON_SCRIPT}" >/dev/null 2>&1 \
            || return 1
    fi
    return 0
}

rfm_set_keep_awake() {
    rfm_awake_value="$1"
    if command -v lipc-set-prop >/dev/null 2>&1; then
        lipc-set-prop -i com.lab126.powerd preventScreenSaver \
            "${rfm_awake_value}" >/dev/null 2>&1 || true
    fi
}

rfm_set_status_bar() {
    rfm_status_bar_action="$1"
    if command -v lipc-set-prop >/dev/null 2>&1; then
        lipc-set-prop com.lab126.pillow disableEnablePillow \
            "${rfm_status_bar_action}" >/dev/null 2>&1 || true
    fi
}

rfm_set_window_manager() {
    rfm_window_manager_action="$1"
    command -v killall >/dev/null 2>&1 || return 0
    case "${rfm_window_manager_action}" in
        pause)
            killall -STOP awesome >/dev/null 2>&1 || true
            ;;
        resume)
            killall -CONT awesome >/dev/null 2>&1 || true
            ;;
    esac
}
