"""Interactive Mac helper, run by Terminal as the user; only LLDB uses sudo.

It reads the existing login session and never quits, launches a replacement,
re-signs, logs out, or kills WeChat. Secrets stay in mode-0600 temporary files.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


class ConnectionFailure(Exception):
    pass


def write_private(path, value):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False)
    temporary.replace(path)


def write_stage(job, phase, code):
    write_private(job / 'status.json', {'phase': phase, 'code': code, 'at': time.time(), 'pid': os.getpid()})


def choose_database(configured='', selected=''):
    root = Path.home() / 'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'
    for value in (selected, configured):
        if value:
            path = Path(value).expanduser().resolve()
            if path.is_relative_to(root.resolve()) and path.name == 'db_storage' and path.is_dir():
                return path
            if selected:
                raise ConnectionFailure('invalid_account')
    try:
        matches = [p / 'db_storage' for p in root.iterdir()
                   if p.name not in ('Backup', 'all_users', 'old_backup') and (p / 'db_storage').is_dir()]
    except PermissionError:
        raise ConnectionFailure('disk_permission') from None
    except FileNotFoundError:
        raise ConnectionFailure('no_data') from None
    if len(matches) != 1:
        raise ConnectionFailure('multiple_accounts' if matches else 'no_data')
    return matches[0]


def collect_salts(database):
    salts = set()
    for path in database.rglob('*.db'):
        if path.is_symlink():
            continue
        with path.open('rb') as stream:
            value = stream.read(16)
        if len(value) == 16 and value != b'SQLite format 3\0':
            salts.add(value.hex())
        if len(salts) > 512:
            raise ConnectionFailure('too_many_databases')
    if not salts:
        raise ConnectionFailure('no_data')
    return sorted(salts)


def classify_lldb_error(text):
    if any(word in text.lower() for word in ('not allowed', 'permission', 'operation not permitted', 'task_for_pid', 'attach failed')):
        return 'developer_permission'
    return 'reader_failed'


def run(request):
    request = Path(request).resolve()
    job = request.parent
    data = json.loads(request.read_text(encoding='utf-8'))
    os.umask(0o077)
    def cancelled(*args):
        (job / 'cancel').touch()
        raise ConnectionFailure('cancelled')
    for number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(number, cancelled)
    import fcntl
    lock = (job.parent / 'reader.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        write_stage(job, 'failed', 'already_running')
        return 1
    try:
        if (job / 'cancel').exists():
            raise ConnectionFailure('cancelled')
        write_stage(job, 'checking', 'checking')
        from wechat_preflight import inspect_wechat
        eligibility = inspect_wechat()
        if eligibility.get('blocked'):
            raise ConnectionFailure(eligibility['code'])
        executable = Path(data['executable'])
        hook = Path(data['hook'])
        if not executable.is_file() or not hook.is_file():
            raise ConnectionFailure('component_missing')
        lldb = subprocess.run(['/usr/bin/xcrun', '--find', 'lldb'], capture_output=True, text=True, timeout=10)
        if lldb.returncode:
            raise ConnectionFailure('tools_missing')
        process = subprocess.run(['/usr/bin/pgrep', '-x', 'WeChat'], capture_output=True, text=True, timeout=5)
        pids = [p for p in process.stdout.split() if p.isdecimal()]
        if len(pids) != 1:
            raise ConnectionFailure('wechat_not_running' if not pids else 'multiple_processes')
        config_file = Path.home() / '.wxvault/config.json'
        try:
            old_config = json.loads(config_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            old_config = {}
        database = choose_database(old_config.get('db_dir', ''), data.get('dbDir', ''))
        salts = collect_salts(database)
        if (job / 'cancel').exists():
            raise ConnectionFailure('cancelled')
        print('正在连接已经登录的微信。此流程不会退出或重新签名微信。', flush=True)
        print('请在下方输入 Mac 登录密码并按回车。输入时不显示字符，这是正常现象。', flush=True)
        print('授权后，请打开要导出的聊天，并往上翻几页历史消息。约 1 分钟后返回工具查看结果。', flush=True)
        write_stage(job, 'authorizing', 'password')
        if subprocess.run(['/usr/bin/sudo', '-v']).returncode:
            raise ConnectionFailure('authorization_cancelled')
        if (job / 'cancel').exists():
            raise ConnectionFailure('cancelled')
        # Root writes only within this private temporary directory. The outer
        # directory is user-owned, allowing cleanup without another sudo call.
        with tempfile.TemporaryDirectory(prefix='chatarchive-live-', dir='/private/tmp') as temp:
            private = Path(temp)
            shutil.copyfile(hook, private / 'hook.py')
            write_private(private / 'salts.json', salts)
            args = ['/usr/bin/sudo', '-n', '/usr/bin/env', 'CHATARCHIVE_LIVE_JOB=' + str(private),
                    lldb.stdout.strip(), '--batch', '-o', 'script import sys; sys.dont_write_bytecode = True',
                    '-o', 'process attach --pid ' + pids[0],
                    '-o', 'command script import ' + str(private / 'hook.py'), '-o', 'quit']
            write_stage(job, 'attaching', 'attaching')
            with tempfile.TemporaryFile() as output:
                child = subprocess.Popen(args, stdout=output, stderr=output)
                try:
                    deadline = time.monotonic() + 100
                    while child.poll() is None:
                        if (job / 'cancel').exists():
                            (private / 'cancel').touch()
                        if time.monotonic() > deadline:
                            (private / 'cancel').touch()
                            raise ConnectionFailure('timeout')
                        # Stage metadata is not secret; it contains no memory contents.
                        reader = private / 'reader.json'
                        if reader.is_file():
                            try:
                                status = json.loads(reader.read_text())
                                if status.get('phase') == 'reading':
                                    write_stage(job, 'reading', 'open_chat')
                            except (OSError, ValueError):
                                pass
                        time.sleep(.25)
                    output.seek(0)
                    diagnostic = output.read(32768).decode(errors='replace')
                    reader = private / 'reader.json'
                    if reader.is_file() and json.loads(reader.read_text()).get('phase') == 'failed':
                        raise ConnectionFailure('reader_failed')
                    if child.returncode:
                        raise ConnectionFailure(classify_lldb_error(diagnostic))
                finally:
                    if child.poll() is None:
                        (private / 'cancel').touch()
                        # The reader observes cancellation and detaches; never kill WeChat.
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            child.terminate()
                            child.wait(timeout=10)
                if (job / 'cancel').exists():
                    raise ConnectionFailure('cancelled')
                pairs = private / 'pairs.json'
                if not pairs.is_file():
                    raise ConnectionFailure('no_keys')
                # The reader assigns its private output to the requesting user;
                # validation and permanent storage never run as root.
                write_stage(job, 'validating', 'validating')
                checked = subprocess.run([str(executable), 'ingest-keys', str(pairs), '--db-dir', str(database), '--check'], capture_output=True, timeout=45)
                if checked.returncode:
                    raise ConnectionFailure('no_keys')
                previous_database = old_config.get('db_dir', '')
                if previous_database and Path(previous_database).resolve() != database.resolve():
                    for filename in ('all_keys.json', 'all_keys.json.prev'):
                        source = config_file.parent / filename
                        if source.exists():
                            source.rename(config_file.parent / (filename + '.account-' + job.name))
                saved = subprocess.run([str(executable), 'ingest-keys', str(pairs), '--db-dir', str(database)], capture_output=True, timeout=45)
                if saved.returncode:
                    raise ConnectionFailure('save_failed')
                config_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                write_private(config_file, {'db_dir': str(database), 'keys_file': 'all_keys.json', 'wechat_process': 'WeChat', 'decrypted_dir': 'cache'})
        probe = subprocess.run([str(executable), 'sessions', '--limit', '1', '--json'], capture_output=True, timeout=60)
        if probe.returncode:
            raise ConnectionFailure('partial_keys')
        result = json.loads(probe.stdout)
        if result.get('meta', {}).get('unknown_shards') or result.get('meta', {}).get('status') not in (None, 'ok'):
            raise ConnectionFailure('partial_keys')
        write_stage(job, 'complete', 'complete')
        print('连接检查通过。请返回 ChatArchiveTool，选择联系人并导出。', flush=True)
        return 0
    except PermissionError:
        write_stage(job, 'failed', 'disk_permission')
        print('无法读取本机文件，请返回工具查看权限设置步骤。', flush=True)
        return 1
    except ConnectionFailure as error:
        write_stage(job, 'failed', str(error))
        print('连接未完成。请返回 ChatArchiveTool 查看具体原因和下一步操作；无需反复输入密码。', flush=True)
        return 1
    except Exception:
        write_stage(job, 'failed', 'unexpected_error')
        print('连接未完成，请返回 ChatArchiveTool 查看帮助。', flush=True)
        return 1

    finally:
        lock.close()


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
