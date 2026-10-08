"""Check official Mac release packages in isolation; never log in or read chats."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_exporters as exporters


def main():
    if not exporters.mac_arm():
        raise SystemExit('Run on an Apple Silicon Mac')
    with tempfile.TemporaryDirectory(prefix='chatarchive-components-') as temp:
        previous = os.environ.get('CHATARCHIVE_DATA_DIR')
        os.environ['CHATARCHIVE_DATA_DIR'] = temp
        try:
            exporters.install_component('qce')
            assert exporters.qce_launcher().is_file()
            exporters.install_component('wxvault')
            subprocess.run([str(exporters.wxvault_binary()), '--help'], check=True, timeout=15)
            print('PASS: pinned upstream checksums, extraction, launcher layout, wxvault executable')
        finally:
            if previous is None:
                os.environ.pop('CHATARCHIVE_DATA_DIR', None)
            else:
                os.environ['CHATARCHIVE_DATA_DIR'] = previous


if __name__ == '__main__':
    main()
