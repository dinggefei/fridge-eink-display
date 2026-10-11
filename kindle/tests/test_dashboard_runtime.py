"""Validate the detached Kindle dashboard start/refresh/stop lifecycle."""
from pathlib import Path
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest


KINDLE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    "runtime.sh",
    "start.sh",
    "stop.sh",
    "daemon.sh",
)


class DashboardRuntimeTest(unittest.TestCase):
    def wait_for(self, condition, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.fail("condition was not met before timeout")

    def test_start_refresh_now_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            for name in RUNTIME_FILES:
                shutil.copy(KINDLE_ROOT / "rfm-dashboard" / name, root / name)
            (root / "config.sh").write_text(
                'BASE_URL="http://unused.invalid"\n'
                'DEVICE_CODE="test-kindle"\n'
                'DEVICE_SECRET="test-only"\n'
                'POLL_SECONDS="30"\n'
                'KEEP_AWAKE="0"\n'
                'HIDE_STATUS_BAR="1"\n'
                'PAUSE_WINDOW_MANAGER="1"\n'
                'POWER_BUTTON_EXIT="1"\n'
            )
            lipc = root / "lipc-set-prop"
            lipc.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "$*" >> "$RFM_DASHBOARD_DIR/state/lipc-calls"\n'
            )
            lipc.chmod(0o700)
            killall = root / "killall"
            killall.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "$*" >> "$RFM_DASHBOARD_DIR/state/killall-calls"\n'
            )
            killall.chmod(0o700)
            power_button_watcher = root / "power-button-watcher"
            power_button_watcher.write_text(
                '#!/bin/sh\n'
                'trap "exit 0" TERM INT HUP\n'
                'while kill -0 "$1" 2>/dev/null; do sleep 1; done\n'
            )
            power_button_watcher.chmod(0o700)
            (root / "refresh.sh").write_text(
                '#!/bin/sh\n'
                'count_file="$RFM_DASHBOARD_DIR/state/test-refresh-count"\n'
                'count="$(cat "$count_file" 2>/dev/null || printf 0)"\n'
                'count=$((count + 1))\n'
                'printf "%s\\n" "$count" > "$count_file"\n'
            )
            env = dict(
                os.environ,
                RFM_DASHBOARD_DIR=directory,
                RFM_START_DELAY_SECONDS="1",
                PATH=directory + os.pathsep + os.environ["PATH"],
                RFM_POWER_BUTTON_WATCHER=str(power_button_watcher),
            )

            subprocess.run(
                ["sh", str(root / "start.sh")],
                env=env,
                check=True,
                timeout=5,
            )
            pid_file = state / "dashboard.pid"
            count_file = state / "test-refresh-count"
            self.wait_for(lambda: pid_file.exists() and count_file.exists())
            first_pid = int(pid_file.read_text().strip())
            self.assertEqual(count_file.read_text().strip(), "1")
            lipc_calls = (state / "lipc-calls").read_text()
            self.assertIn(
                "com.lab126.pillow disableEnablePillow disable",
                lipc_calls,
            )
            killall_calls = (state / "killall-calls").read_text()
            self.assertIn("-STOP awesome", killall_calls)

            # A second tap asks the existing daemon for an immediate refresh;
            # it must not create a duplicate background process.
            subprocess.run(
                ["sh", str(root / "start.sh")],
                env=env,
                check=True,
                timeout=5,
            )
            time.sleep(0.25)
            self.assertEqual(count_file.read_text().strip(), "1")
            self.wait_for(lambda: count_file.read_text().strip() == "2")
            self.assertEqual(int(pid_file.read_text().strip()), first_pid)

            subprocess.run(
                ["sh", str(root / "stop.sh")],
                env=env,
                check=True,
                timeout=15,
            )
            self.wait_for(lambda: not pid_file.exists())
            lipc_calls = (state / "lipc-calls").read_text()
            self.assertIn(
                "com.lab126.pillow disableEnablePillow enable",
                lipc_calls,
            )
            killall_calls = (state / "killall-calls").read_text()
            self.assertIn("-CONT awesome", killall_calls)
            with self.assertRaises(ProcessLookupError):
                os.kill(first_pid, 0)

    def test_scriptlets_do_not_use_launcher_console(self):
        for name in ("RFM_Dashboard.sh", "RFM_Stop_Dashboard.sh"):
            script = (KINDLE_ROOT / name).read_text()
            self.assertIn("# DontUseFBInk", script)
            self.assertIn("# Name:", script)


if __name__ == "__main__":
    unittest.main()
