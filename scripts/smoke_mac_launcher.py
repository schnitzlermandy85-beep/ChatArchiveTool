"""Exercise native reopen and both exit paths using only isolated app data."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request


def check(executable):
    with tempfile.TemporaryDirectory(prefix='chatarchive-reopen-') as tmp:
        root = Path(tmp)
        # Same data location, two consecutive launches: no stale URL may be reused.
        for menu_quit in (False, True):
            marker = root / 'launcher-test.json'
            marker.unlink(missing_ok=True)
            env = {**os.environ, 'CHATARCHIVE_DATA_DIR': str(root),
                   'CHATARCHIVE_TEST_MENU_QUIT': '1' if menu_quit else '0'}
            process = subprocess.Popen([str(executable), '--launcher-test'], env=env)
            child = None
            try:
                deadline = time.monotonic() + 30
                info = {}
                while info.get('opens') != 3:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Native reopen failed: ' + str(info))
                    if marker.exists():
                        info = json.loads(marker.read_text())
                    time.sleep(.05)
                child = info['pid']
                assert child > 1 and child != process.pid
                url = info['url']
                if not menu_quit:
                    with urllib.request.urlopen(url, timeout=5) as response:
                        page = response.read().decode()
                    token = re.search(r'name="archive-token" content="([^"]+)"', page).group(1)
                    request = urllib.request.Request(url + 'api/shutdown', data=b'{}',
                        headers={'Content-Type': 'application/json', 'X-Archive-Token': token})
                    with urllib.request.urlopen(request, timeout=5) as response:
                        assert json.load(response)['ok']
                assert process.wait(timeout=15) == 0
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    pass
                else:
                    raise AssertionError('Backend survived native exit')
            finally:
                if process.poll() is None:
                    process.terminate(); process.wait(timeout=5)
                if child:
                    try: os.kill(child, 15)
                    except ProcessLookupError: pass
        print('PASS: native AppKit reopen twice, one backend, in-page exit, relaunch, menu exit, no orphan process')


if __name__ == '__main__':
    import sys
    check(Path(sys.argv[1]).resolve())
