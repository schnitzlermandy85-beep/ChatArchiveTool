"""Observable Windows launcher; launch errors stay visible and have a local log."""
import datetime
import pathlib
import struct
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parent


class StartupStream:
    def __init__(self, original, logfile):
        self.original, self.logfile = original, logfile
        self.encoding = getattr(original, 'encoding', None) or 'utf-8'

    def write(self, value):
        self.logfile.write(value)
        self.logfile.flush()
        if self.original is not None:
            try:
                self.original.write(value)
            except UnicodeEncodeError:
                self.original.write(value.encode(self.encoding, errors='replace').decode(self.encoding))
        return len(value)

    def flush(self):
        self.logfile.flush()
        if self.original is not None:
            self.original.flush()

    def isatty(self):
        return False


def main():
    if sys.version_info[:2] < (3, 10):
        print('ChatArchive requires Python 3.10 or newer; use Python 3.12 x64 for bundled voice/WeChat components.')
        return 1
    logfile = None
    previous_out, previous_err = sys.stdout, sys.stderr
    log_path = ROOT / 'logs' / 'startup.log'
    try:
        try:
            log_path.parent.mkdir(exist_ok=True)
            logfile = log_path.open('w', encoding='utf-8', buffering=1)
            sys.stdout = StartupStream(previous_out, logfile)
            sys.stderr = StartupStream(previous_err, logfile)
        except OSError:
            print('Startup log could not be written; errors will appear in this window.')
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        print('ChatArchive startup:', now.isoformat(), flush=True)
        print('Python:', sys.version.split()[0], '|', sys.executable, flush=True)
        for relative in ('web/index.html', 'web/app.js', 'web/style.css', 'web/report.js', 'web_app.py', 'relationship.py', 'relationship_report.py', 'analysis_input.py', 'psychology_frameworks.py', 'psychology_references.py'):
            if not (ROOT / relative).is_file():
                raise RuntimeError('Missing ' + relative + '. Extract the entire ZIP before running start.cmd.')
        shared = ROOT.parent.parent / 'work/voice-runtime'
        bundled = ROOT / 'runtime/voice'
        site = bundled if bundled.exists() else shared / '.voice-env/Lib/site-packages'
        if site.exists() and sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8:
            sys.path.insert(0, str(site))
        from web_app import make_server, run
        if '--check' in sys.argv:
            server = make_server()
            server.server_close()
            print('Startup check passed: imports, web assets and local HTTP binding.', flush=True)
            return 0
        if sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
            print('Use Python 3.12 x64 to use this package\'s bundled voice and WeChat components.', flush=True)
        run(open_browser='--no-browser' not in sys.argv)
        return 0
    except Exception:
        traceback.print_exc()
        print('Startup failed. Local log: ' + str(log_path), flush=True)
        if previous_out is None:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, '启动失败，请查看日志：\n' + str(log_path) + '\n\n请完整解压工具包，并使用 start.cmd 启动。', 'ChatArchive 启动失败', 0x10)
            except Exception:
                pass
        return 1
    finally:
        sys.stdout, sys.stderr = previous_out, previous_err
        if logfile is not None:
            logfile.close()


if __name__ == '__main__':
    raise SystemExit(main())
