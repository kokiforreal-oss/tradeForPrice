#!/usr/bin/env bash
# 本机直推服务器（不走 GitHub）。若你已改为「提交到 GitHub 再升级」，
# 请不要用本脚本，改用：本机 ./prepare-release.sh → git push → 服务器 ./upgrade-from-github.sh
# 用法：
#   ./upgrade.sh
#   ./upgrade.sh root@47.118.17.143:/opt/trade
# 也可先 export TRADE_REMOTE=root@你的IP:/opt/trade
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-${TRADE_REMOTE:-root@47.118.17.143:/opt/trade}}"

if [[ "$DEST" != *:* ]]; then
  echo "用法: ./upgrade.sh user@host:/opt/trade"
  exit 1
fi

HOST="${DEST%%:*}"
REMOTE_PATH="${DEST#*:}"

echo "构建号递增中…"
VER="$(python3 "$ROOT/bump-version.py")"
echo "本次版本：$VER"

SKIP_BUMP=1 "$ROOT/update-remote.sh" "$DEST"

echo "服务器部署中（先备份库再重启）…"
ssh "$HOST" "cd '$REMOTE_PATH' && chmod +x deploy.sh backup.sh && ./deploy.sh"

echo
echo "升级完成。版本 $VER"
echo "请用浏览器强制刷新后登录确认：https://${HOST#*@}/"
echo "侧栏和登录页会显示构建号，应与上面一致。"
