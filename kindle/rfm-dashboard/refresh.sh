#!/bin/sh
set -u

DASHBOARD_DIR="${RFM_DASHBOARD_DIR:-/mnt/us/rfm-dashboard}"
CONFIG_FILE="${DASHBOARD_DIR}/config.sh"
STATE_DIR="${DASHBOARD_DIR}/state"
FBINK="${RFM_FBINK:-/mnt/us/libkh/bin/fbink}"
FRAME_PATH="/v1/devices"
ERROR_LOG="${DASHBOARD_DIR}/last-error.log"
ERROR_DISPLAY_SECONDS="${RFM_ERROR_DISPLAY_SECONDS:-20}"
PREVIEW_SECONDS="${RFM_PREVIEW_SECONDS:-0}"
FBINK_LOG="${STATE_DIR}/fbink.log"
RUN_LOG="${DASHBOARD_DIR}/last-run.log"

# Normalize HTTP CRLF before parsing; do not depend on awk regexp escapes.
header_value() {
    tr -d '\015' < "${headers}" | awk -v key="$1" '
        tolower($1) == key ":" {
            sub(/^[^:]*:[[:space:]]*/, "")
            print
        }' | tail -n 1
}

valid_etag() {
    printf '%s\n' "$1" | LC_ALL=C grep -Eq '^"kindle-pw3-v[0-9]+-[0-9a-f]{16}"$'
}

render_frame() {
    # FBInk 1.25: -g takes image suboptions, not a bare path.
    # Both streams must stay off the Scriptlet console, which renders output
    # over the image. -w waits for the final display refresh to complete.
    "${FBINK}" -c -f -w -g "file=${current}" > "${FBINK_LOG}" 2>&1
    render_result=$?
    if [ "${render_result}" -ne 0 ]; then
        render_detail="$(head -c 400 "${FBINK_LOG}" | tr '\n' ' ')"
        fail "screen refresh failed (FBInk ${render_result}); ${render_detail}"
    fi
    printf 'render_ok http=%s image=%s\n' "${status}" "${current}" > "${RUN_LOG}"
}

fail() {
    message="$1"
    client_time="${local_timestamp:-unknown}"
    signing_time="${timestamp:-unknown}"
    server_time="unknown"
    if [ -r "${headers:-}" ]; then
        server_time="$(header_value date)"
        [ -n "${server_time}" ] || server_time="unknown"
    fi
    mkdir -p "${DASHBOARD_DIR}" 2>/dev/null || true
    {
        printf 'RFM Dashboard Error\n'
        printf '%s\n' "${message}"
        printf 'Client epoch: %s\n' "${client_time}"
        printf 'Signing epoch: %s\n' "${signing_time}"
        printf 'Server date: %s\n' "${server_time}"
        printf 'This page will close automatically after %s seconds.\n' "${ERROR_DISPLAY_SECONDS}"
    } | tee "${ERROR_LOG}" >&2

    # This PW3 Scriptlet viewer has no close control while a script is running.
    # Keep the message visible long enough to photograph, then return safely.
    sleep "${ERROR_DISPLAY_SECONDS}"
    exit 1
}

[ -r "${CONFIG_FILE}" ] || fail "missing config.sh"
# shellcheck source=/dev/null
. "${CONFIG_FILE}"

[ -n "${BASE_URL:-}" ] || fail "BASE_URL is empty"
[ -n "${DEVICE_CODE:-}" ] || fail "DEVICE_CODE is empty"
[ -n "${DEVICE_SECRET:-}" ] || fail "DEVICE_SECRET is empty"
[ -x "${FBINK}" ] || fail "FBInk is missing"
command -v curl >/dev/null 2>&1 || fail "curl is missing"
command -v openssl >/dev/null 2>&1 || fail "openssl is missing"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is missing"

mkdir -p "${STATE_DIR}" || fail "cannot create state directory"
printf 'started\n' > "${RUN_LOG}"
local_timestamp="$(date +%s)"
timestamp="$(curl -fsS --connect-timeout 10 --max-time 15 "${BASE_URL}/v1/device-time")" \
    || fail "could not fetch server time from ${BASE_URL}"
case "${timestamp}" in
    ''|*[!0-9]*) fail "server returned an invalid timestamp: ${timestamp}" ;;
esac
random_part="$(hexdump -n 12 -e '12/1 "%02x"' /dev/urandom 2>/dev/null || true)"
[ -n "${random_part}" ] || random_part="${timestamp}$$fallback"
nonce="k${random_part}"
etag=""
# Repair legacy CRLF cache entries. Ignore invalid values or missing images.
if [ -r "${STATE_DIR}/etag" ] && [ -s "${STATE_DIR}/frame.png" ]; then
    etag="$(tr -d '\015' < "${STATE_DIR}/etag" | sed -n '1p')"
    valid_etag "${etag}" || etag=""
fi

path="${FRAME_PATH}/${DEVICE_CODE}/frame"
# Pipe the canonical text directly. Command substitution would strip the
# required trailing newline when ETag is empty and produce a different HMAC.
signature="$(printf 'GET\n%s\n%s\n%s\n%s' \
    "${path}" "${timestamp}" "${nonce}" "${etag}" \
    | openssl dgst -sha256 -hmac "${DEVICE_SECRET}" 2>/dev/null \
    | awk '{print $NF}')"
[ "${#signature}" -eq 64 ] || fail "could not create request signature"

headers="${STATE_DIR}/headers.tmp"
incoming="${STATE_DIR}/frame.tmp"
curl_error="${STATE_DIR}/curl-error.tmp"
current="${STATE_DIR}/frame.png"
url="${BASE_URL}${path}?format=kindle-pw3"
rm -f "${headers}" "${incoming}" "${curl_error}"

set -- \
    -sS \
    --connect-timeout 20 \
    --max-time 90 \
    -D "${headers}" \
    -o "${incoming}" \
    -w '%{http_code}' \
    -H "X-Device-Timestamp: ${timestamp}" \
    -H "X-Device-Nonce: ${nonce}" \
    -H "X-Device-Signature: ${signature}"
[ -n "${etag}" ] && set -- "$@" -H "If-None-Match: ${etag}"

status="$(curl "$@" "${url}" 2>"${curl_error}")"
curl_result=$?
if [ "${curl_result}" -ne 0 ]; then
    curl_detail="$(tr '\n' ' ' < "${curl_error}" | cut -c 1-240)"
    fail "download failed (curl ${curl_result}); ${curl_detail}"
fi
if [ "${status}" = "304" ]; then
    render_frame
    rm -f "${incoming}" "${headers}" "${curl_error}"
    if [ "${PREVIEW_SECONDS}" -gt 0 ]; then
        sleep "${PREVIEW_SECONDS}"
    fi
    exit 0
fi
if [ "${status}" != "200" ]; then
    response_detail=""
    if [ -r "${incoming}" ]; then
        response_detail="$(tr '\n' ' ' < "${incoming}" | cut -c 1-240)"
    fi
    fail "server returned HTTP ${status}; ${response_detail}"
fi

expected_sha="$(header_value x-frame-sha256)"
actual_sha="$(sha256sum "${incoming}" | awk '{print $1}')"
[ -n "${expected_sha}" ] || fail "response hash is missing"
[ "${actual_sha}" = "${expected_sha}" ] || fail "response hash mismatch"

new_etag="$(header_value etag)"
valid_etag "${new_etag}" || fail "response ETag is missing or invalid"
mv "${incoming}" "${current}" || fail "cannot save frame"
render_frame
printf '%s\n' "${new_etag}" > "${STATE_DIR}/etag" || fail "cannot save ETag"
rm -f "${headers}" "${curl_error}"
if [ "${PREVIEW_SECONDS}" -gt 0 ]; then
    sleep "${PREVIEW_SECONDS}"
fi
