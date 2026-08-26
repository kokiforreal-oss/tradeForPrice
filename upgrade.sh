#!/usr/bin/env bash
# 本机直推服务器并重建 Docker 容器（不走 GitHub，不覆盖远程 .env / data/）。
# 第一次请先在服务器执行：cd /opt/trade && ./docker-setup.sh
# 用法：./upgrade.sh
#       ./upgrade.sh root@47.118.17.143:/opt/trade
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

echo "服务器 Docker 发版中（先备份库再重建容器）…"
ssh "$HOST" "cd '$REMOTE_PATH' && chmod +x docker-setup.sh deploy-docker.sh docker-lib.sh &&
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo 'Docker 未就绪，执行一次性切换 docker-setup.sh …'
    ./docker-setup.sh
  else
    ./deploy-docker.sh
  fi"

echo
echo "升级完成。版本 $VER"
echo "请用浏览器强制刷新后登录确认：https://${HOST#*@}/"
