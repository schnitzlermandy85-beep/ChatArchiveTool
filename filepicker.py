"""Native picker in a separate main-thread process (including packaged apps)."""
import json
import subprocess
import sys


def choose(kind, category='messages'):
    if kind not in ('folder', 'file'):
        raise ValueError('Invalid picker kind')
    if sys.platform == 'darwin':
        # AppleScript opens the native Finder dialog without a Tk installation.
        command = 'choose folder with prompt "选择文件夹"' if kind == 'folder' else 'choose file with prompt "选择聊天导出文件"'
        script = 'try\nactivate\nset chosen to ' + command + '\nreturn POSIX path of chosen\non error number -128\nreturn ""\nend try'
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True)
        return result.stdout.rstrip('\n')
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        if kind == 'folder':
            return filedialog.askdirectory(parent=root, title='选择文件夹')
        types = [('媒体压缩包', '*.zip')] if category == 'zip' else [('聊天数据', '*.json *.jsonl *.zip *.txt'), ('所有文件', '*.*')]
        return filedialog.askopenfilename(parent=root, title='选择聊天导出文件', filetypes=types)
    finally:
        root.destroy()


def main(args=None):
    args = sys.argv[1:] if args is None else args
    print(json.dumps(choose(*args), ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
