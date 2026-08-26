#!/usr/bin/env bash
# 本机提交到 GitHub 之前执行：只升构建号，不提交、不推送。
# 然后你自己 git add / commit / push，再到服务器跑 ./upgrade-from-github.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VER="$(python3 "$ROOT/bump-version.py")"
echo "构建号已改为 $VER"
echo "请把 VERSION 和 app/static/index.html 一并提交后 push："
echo "  git add VERSION app/static/index.html"
echo "  git commit -m \"发布 $VER\""
echo "  git push"
echo "再到服务器：cd /opt/trade && ./upgrade-from-github.sh"
