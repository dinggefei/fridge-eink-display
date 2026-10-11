"""Exercise the real shell client against an authenticated HTTP test server."""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import subprocess
import tempfile
import threading
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'rfm-dashboard/refresh.sh'
SECRET = 'client-test-secret-only'
ETAG = '"kindle-pw3-v1-0123456789abcdef"'
BODY = b'validated-frame-fixture'


class RefreshTest(unittest.TestCase):
    def test_download_repeat_and_legacy_cache(self):
        statuses = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == '/v1/device-time':
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(str(int(time.time())).encode())
                    return
                etag = self.headers.get('If-None-Match', '')
                canonical = '\n'.join(('GET', self.path.split('?')[0],
                    self.headers.get('X-Device-Timestamp', ''),
                    self.headers.get('X-Device-Nonce', ''), etag))
                digest = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(digest, self.headers.get('X-Device-Signature', '')):
                    code = 401
                else:
                    code = 304 if etag == ETAG else 200
                statuses.append(code)
                self.send_response(code)
                self.send_header('etag', ETAG)
                self.send_header('x-frame-sha256', hashlib.sha256(BODY).hexdigest())
                self.end_headers()
                if code == 200:
                    self.wfile.write(BODY)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'config.sh').write_text(
                    f'BASE_URL="http://127.0.0.1:{server.server_port}"\n'
                    f'DEVICE_CODE="test-kindle"\nDEVICE_SECRET="{SECRET}"\n')
                fbink = root / 'fbink'
                fbink.write_text("""#!/bin/sh
# Contract from FBInk 1.25's real --help; this cannot validate screen hardware.
[ "$#" -eq 5 ] || exit 64
[ "$1" = '-c' ] && [ "$2" = '-f' ] && [ "$3" = '-w' ] && [ "$4" = '-g' ] || exit 64
case "$5" in file=*) image_path="${5#file=}" ;; *) exit 64 ;; esac
[ -s "$image_path" ] || exit 66
printf 'draw\\n' >> "$RFM_DASHBOARD_DIR/draws"
printf 'FBInk diagnostic output must not cover the image\\n' >&2
""")
                fbink.chmod(0o700)
                # macOS has shasum, Kindle has sha256sum; use equivalent output.
                sha = root / 'sha256sum'
                sha.write_text('#!/bin/sh\nexec shasum -a 256 "$@"\n')
                sha.chmod(0o700)
                env = dict(os.environ, RFM_DASHBOARD_DIR=directory,
                    RFM_FBINK=str(fbink), RFM_ERROR_DISPLAY_SECONDS='0', RFM_PREVIEW_SECONDS='0',
                    PATH=directory + os.pathsep + os.environ['PATH'])
                def run():
                    result = subprocess.run(['sh', str(SCRIPT)], env=env,
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, '')
                    self.assertNotIn('FBInk diagnostic', result.stderr)
                    self.assertIn('render_ok', (root / 'last-run.log').read_text())
                run()  # Empty ETag must retain the trailing HMAC newline.
                self.assertEqual((root / 'state/frame.png').read_bytes(), BODY)
                run()  # Normal second launch; redraw cached image on 304.
                (root / 'state/etag').write_bytes(ETAG.encode() + b'\r\n')
                run()  # Legacy cache with CR must still sign/send correctly.
                (root / 'state/etag').write_bytes(b'"broken\x01header"\n')
                run()  # Invalid cache must be discarded, not sent.
                (root / 'state/frame.png').unlink()
                run()  # ETag alone cannot justify a 304 without an image.
                self.assertEqual(statuses, [200, 304, 304, 200, 200])
                self.assertEqual((root / 'draws').read_text().splitlines(), ['draw'] * 5)
                # A real display failure must surface the tool's error and
                # must not mark a newly downloaded frame as displayed.
                (root / 'state/etag').unlink()
                fbink.write_text('#!/bin/sh\nprintf "framebuffer unavailable\\n" >&2\nexit 42\n')
                failed = subprocess.run(['sh', str(SCRIPT)], env=env,
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(failed.returncode, 1)
                self.assertIn('FBInk 42', failed.stderr)
                self.assertIn('framebuffer unavailable', (root / 'last-error.log').read_text())
                self.assertFalse((root / 'state/etag').exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
