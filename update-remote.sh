#!/usr/bin/env bash
# 本机把代码同步到服务器，不覆盖远程 .env、data/（含 e2e.key 与上传文件）、.venv
# 必须在本机终端执行（不要在服务器上执行）。会提示输入 SSH 密码，除非已配密钥。
# 用法：./update-remote.sh root@YOUR_IP:/opt/trade
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:?用法: ./update-remote.sh user@host:/opt/trade}"

if [[ "$DEST" != *:* ]]; then
  echo "用法: ./update-remote.sh user@host:/opt/trade"
  exit 1
fi

if [[ "$(uname -s)" == "Linux" ]] && [[ -d /opt/trade ]] && [[ "$ROOT" == /opt/trade* ]]; then
  echo "当前看起来是在服务器上。请到电脑项目目录执行本脚本，不要在 ECS 上跑。"
  exit 1
fi

HOST="${DEST%%:*}"
REMOTE_PATH="${DEST#*:}"

if [[ "${SKIP_BUMP:-}" != "1" ]]; then
  echo "构建号递增中…"
  python3 "$ROOT/bump-version.py"
fi

echo "正在同步到 $HOST:$REMOTE_PATH （不会覆盖远程 .env 和 data/）…"
echo "若询问密码，输入的是服务器 SSH 密码，不是 GitHub。"

# macOS 自带 openrsync 与 Linux rsync 经常不兼容，统一用 tar+ssh
# COPYFILE_DISABLE：去掉 macOS 的 ._* 资源叉文件
export COPYFILE_DISABLE=1
ssh -o ConnectTimeout=15 "$HOST" "mkdir -p '$REMOTE_PATH'"
tar -C "$ROOT" \
  --exclude='.env' \
  --exclude='data' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='.cursor' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  -cf - . | ssh -o ConnectTimeout=15 "$HOST" "cd '$REMOTE_PATH' && tar -xf -"

echo "代码已同步。"
echo "若尚未切到 Docker：ssh $HOST 'cd $REMOTE_PATH && chmod +x docker-setup.sh && ./docker-setup.sh'"
echo "若已在用 Docker：ssh $HOST 'cd $REMOTE_PATH && chmod +x deploy-docker.sh && ./deploy-docker.sh'"
