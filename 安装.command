#!/bin/zsh
cd -- "$(dirname -- "$0")"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo '正在通过 Homebrew 安装 Python…'
    brew install python || { read -r '?安装失败，按回车退出…'; exit 1; }
  else
    echo '请先从 https://www.python.org/downloads/macos/ 安装 Python 3，再重新运行本脚本。'
    open 'https://www.python.org/downloads/macos/'
    read -r '?按回车退出…'
    exit 1
  fi
fi
python3 setup.py
result=$?
read -r '?按回车退出…'
exit $result
