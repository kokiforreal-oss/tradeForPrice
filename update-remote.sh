#!/usr/bin/env bash
# 本机把代码同步到服务器，不覆盖远程 .env、data/（含 e2e.key 与上传文件）、.venv
# 用法：./update-remote.sh root@YOUR_IP:/opt/trade
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:?用法: ./update-remote.sh user@host:/opt/trade}"

rsync -avz --delete \
  --exclude '.env' \
  --exclude 'data/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.git/' \
  --exclude '*.pyc' \
  "$ROOT/" "$DEST"

echo "代码已同步。请在服务器上执行：cd 项目目录 && ./deploy.sh"
echo "deploy.sh 会先备份 MySQL，再重启服务；不会清库、不会覆盖 data/。"
