#!/bin/zsh
cd -- "$(dirname -- "$0")"
python3 setup.py --check && python3 server.py
if [ $? -ne 0 ]; then
  echo '启动失败。请确认已安装 Python 3，且 8765 端口未被占用。'
  read -r '?按回车退出…'
fi
