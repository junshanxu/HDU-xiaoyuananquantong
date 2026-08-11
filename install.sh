#!/usr/bin/env bash

set -eu

REPOSITORY="${HDU_SAFETY_REPOSITORY:-https://github.com/yuaiccc/HDU-xiaoyuananquantong.git}"
if [ -n "${HDU_SAFETY_DIR:-}" ]; then
  INSTALL_DIR="$HDU_SAFETY_DIR"
elif [ -n "${XDG_DATA_HOME:-}" ]; then
  INSTALL_DIR="$XDG_DATA_HOME/hdu-safety-answer"
else
  INSTALL_DIR="$HOME/.local/share/hdu-safety-answer"
fi

fail() {
  printf '安装失败：%s\n' "$1" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "未找到 git，请先安装 Git"
command -v python3 >/dev/null 2>&1 || fail "未找到 python3，请先安装 Python 3"

case "$INSTALL_DIR" in
  /*) ;;
  *) fail "安装目录必须是绝对路径：$INSTALL_DIR" ;;
esac

if [ -e "$INSTALL_DIR" ]; then
  [ -d "$INSTALL_DIR" ] || fail "安装位置已存在且不是目录：$INSTALL_DIR"
  for required_file in server.py xy_auto.py xy_bank.json index.html; do
    [ -f "$INSTALL_DIR/$required_file" ] || fail "安装目录不完整：缺少 $required_file"
  done
  printf '使用已有安装：%s\n' "$INSTALL_DIR"
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  printf '正在下载到：%s\n' "$INSTALL_DIR"
  git clone --depth 1 "$REPOSITORY" "$INSTALL_DIR" || fail "代码下载失败，请检查网络或设置 HDU_SAFETY_REPOSITORY 使用镜像"
fi

python3 -m py_compile "$INSTALL_DIR/server.py" "$INSTALL_DIR/xy_auto.py" || fail "Python 文件编译失败，请检查 server.py / xy_auto.py"
QUESTION_COUNT="$({ python3 - "$INSTALL_DIR/xy_bank.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    bank = json.load(handle)
if not isinstance(bank, (dict, list)) or not bank:
    raise SystemExit("题库不是非空 JSON 对象或数组")
print(len(bank))
PY
} 2>&1)" || fail "题库校验失败：$QUESTION_COUNT"

printf '题库校验完成：%s 题\n' "$QUESTION_COUNT"

if [ "${HDU_SAFETY_INSTALL_ONLY:-0}" = "1" ]; then
  printf '安装完成：%s\n' "$INSTALL_DIR"
  exit 0
fi

PORT="${PORT:-8090}"
case "$PORT" in
  ''|*[!0-9]*) fail "PORT 必须是数字：$PORT" ;;
esac

# 端口占用预检：避免 server.py 启动时因 "Address already in use" 直接退出。
if command -v python3 >/dev/null 2>&1; then
  python3 - "$PORT" <<'PY' || fail "端口 $PORT 已被占用，可用 PORT=xxxx 指定其他端口"
import socket, sys
s = socket.socket()
s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(0)
finally:
    s.close()
sys.exit(1)
PY
fi

URL="http://127.0.0.1:$PORT"
printf '\n服务正在启动：%s\n' "$URL"
printf '关闭此终端或按 Ctrl+C 即可停止。\n\n'

if [ "${HDU_SAFETY_NO_OPEN:-0}" = "1" ]; then
  :
elif command -v open >/dev/null 2>&1; then
  (sleep 1; open "$URL" >/dev/null 2>&1 || true) &
elif command -v xdg-open >/dev/null 2>&1; then
  (sleep 1; xdg-open "$URL" >/dev/null 2>&1 || true) &
fi

cd "$INSTALL_DIR"
exec env HOST=127.0.0.1 PORT="$PORT" python3 server.py
