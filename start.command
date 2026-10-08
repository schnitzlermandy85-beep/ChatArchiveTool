#!/bin/bash
# Finder launches .command files in Terminal; resolve paths with spaces safely.
cd -- "$(dirname -- "$0")" || exit 1
if [[ -x .venv/bin/python ]]; then
    PYTHON=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
else
    echo '请安装 Python 3.12，或下载 Release 中无需 Python 的 Mac 应用。'
    read -r -p '按回车键退出…'
    exit 1
fi
"$PYTHON" -u app.py "$@"
status=$?
if [[ $status -ne 0 ]]; then
    echo '启动失败，请查看上方错误或 logs/startup.log。'
    read -r -p '按回车键退出…'
fi
exit "$status"
