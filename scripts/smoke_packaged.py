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
        if sys.platform == 'darwin' and platform.machine().lower() == 'arm64':
            job = root / 'cancelled-connection'; job.mkdir()
            (job / 'cancel').touch()
            (job / 'request.json').write_text('{}')
            cancelled = subprocess.run([executable, '--helper', 'wechat_connect', str(job / 'request.json')], env=env, timeout=15)
            assert cancelled.returncode == 2
            assert not (job / 'status.json').exists()  # Retired helper never starts a reader.
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
            assert config['appVersion'] == (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip()
            if sys.platform == 'darwin':
                assert config['wechatNative'] and config['wechatShareBundled']
                assert not config['wechatSupported'] and not config['wechatReady']
            if sys.platform == 'darwin':
                assert config['wechatSupported'] is False
                assert config['wechatMac'] is True
                assert config['wechatInstalled'] is False
                assert config['qceInstalled'] is False
            assert 'id="help-view"' in page and 'id="help-search"' in page
            assert '会暂时退出微信' not in page
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
            # Exercise native import inside the frozen executable, including dynamic imports.
            import zipfile
            native = root / '微信合成测试.zip'
            with zipfile.ZipFile(native, 'w') as archive:
                archive.writestr('聊天记录.txt', '·测试甲\n2026年10月8日 10:00\n测试文字\n\n·测试乙\n2026年10月8日 10:01\n[图片] test.png\n')
                archive.writestr('media/test.png', b'synthetic-image')
            api('start', {'platform': 'WeChat', 'mode': 'import', 'source': str(native),
                          'output': str(root / 'native-result'), 'transcribe': False})
            deadline = time.monotonic() + 20
            while True:
                state = api('state')
                if not state['busy']: break
                if time.monotonic() > deadline: raise RuntimeError('Packaged native import timed out')
                time.sleep(.1)
            assert state['status'] == 'complete', state
            assert state['summary']['messageCount'] == 2
            assert state['summary']['media']['image'] == 1
            assert not state['summary']['media'].get('missing_image')
            assert state['summary']['historyCompleteness'] == 'selected_messages_only'
            api('shutdown', {})
            assert process.wait(timeout=10) == 0
            print('PASS: packaged startup, assets, platform config, synthetic chat analysis, report, native WeChat ZIP import, shutdown')
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
