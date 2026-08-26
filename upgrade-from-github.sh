#!/usr/bin/env bash
# 在服务器 /opt/trade 执行：用 GitHub 上的代码升级（不覆盖 .env、data/）
# 本机请先：升版本 → 提交 → push，再跑本脚本。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -d .git ]]; then
  cat <<'EOF'
当前目录还不是 git 仓库。第一次请执行（不会删 .env 和 data/）：

  cd /opt/trade
  git init
  git remote add origin https://github.com/kokiforreal-oss/tradeForPrice.git
  git fetch origin
  git checkout -B main origin/main

若 fetch 要登录，把仓库改成私有部署密钥，或把 origin 换成 git@github.com:kokiforreal-oss/tradeForPrice.git
EOF
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "缺少 .env，拒绝升级，以免连错库。"
  exit 1
fi

git fetch origin
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" == "HEAD" ]]; then
  BRANCH="main"
fi
git pull --ff-only origin "$BRANCH"

chmod +x deploy.sh backup.sh bump-version.py
./deploy.sh
