"""End-to-end verification of the packaged executable, with isolated synthetic data."""
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    executable = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix='chatarchive-package-') as temp:
        root = Path(temp).resolve()
        env = {**os.environ, 'CHATARCHIVE_DATA_DIR': str(root / 'data')}
        subprocess.run([executable, '--check'], env=env, check=True, timeout=30)
        assert 'Startup check passed' in (root / 'data/logs/startup.log').read_text(encoding='utf-8')
        # Unknown helpers must exit, never launch a second server.
        invalid = subprocess.run([executable, '--helper', 'invalid'], env=env, timeout=30)
        assert invalid.returncode == 2
        source = root / '示例 聊天'
        shutil.copytree(Path(__file__).resolve().parents[1] / 'examples/synthetic-chat', source)
        process = subprocess.Popen([executable, '--no-browser'], env=env)
        try:
            url_file = root / 'data/logs/current-url.txt'
            deadline = time.monotonic() + 30
            while not url_file.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Packaged server did not start')
                time.sleep(.1)
            url = url_file.read_text(encoding='utf-8').strip()
            with urllib.request.urlopen(url, timeout=5) as response:
                page = response.read().decode('utf-8')
            token = re.search(r'name="archive-token" content="([^"]+)"', page).group(1)

            def api(route, body=None):
                request = urllib.request.Request(url + 'api/' + route,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-Archive-Token': token, 'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=10) as response:
                    return json.load(response)

            config = api('config')
            assert config['output'] == str(root / 'data/exports')
            if sys.platform == 'darwin':
                assert config['wechatSupported'] == (platform.machine().lower() == 'arm64')
                assert config['wechatMac'] is True
                assert config['wechatInstalled'] is False
                assert config['qceInstalled'] is False
            assert 'data-component="install-qq"' in page
            assert 'data-component="init-wechat"' in page
            inspection = api('analysis/inspect', {'archive': str(source)})
            preview = api('analysis/prepare', {'archive': str(source),
                'selfId': inspection['participants'][0]['id'], 'relationship': 'friend', 'mode': 'local'})
            api('analysis/start', {'previewId': preview['previewId'], 'mode': 'local'})
            deadline = time.monotonic() + 20
            while True:
                state = api('state')
                if not state['busy']:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError('Packaged analysis timed out')
                time.sleep(.1)
            assert state['analysisResult'], state
            request = urllib.request.Request(url + 'analysis/report.html', headers={'Cookie': 'archive_session=' + token})
            with urllib.request.urlopen(request, timeout=5) as response:
                assert 'html' in response.read().decode('utf-8').lower()
            api('shutdown', {})
            assert process.wait(timeout=10) == 0
            print('PASS: packaged startup, assets, platform config, synthetic chat analysis, report, shutdown')
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
