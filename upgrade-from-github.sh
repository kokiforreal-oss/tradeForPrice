#!/usr/bin/env bash
# 在服务器 /opt/trade 执行：用 GitHub 上的代码升级（不覆盖 .env、data/）
# 本机请先：升版本 → 提交 → push，再跑本脚本。
# 若 github.com:443 超时（国内 ECS 常见），不要用本脚本，改在本机执行 ./upgrade.sh
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

echo "正在从 GitHub 拉取（最多等 45 秒）…"
if command -v timeout >/dev/null 2>&1; then
  if ! timeout 45 git fetch --progress origin; then
    cat <<'EOF'
连不上 GitHub（常见于国内 ECS：github.com 443 超时）。

请改在本机项目目录执行（不经过 GitHub）：
  ./upgrade.sh root@你的公网IP:/opt/trade

EOF
    exit 1
  fi
else
  git fetch --progress origin
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" == "HEAD" ]]; then
  BRANCH="main"
fi
echo "正在合并 $BRANCH …"
git pull --ff-only origin "$BRANCH"

chmod +x deploy.sh backup.sh bump-version.py
./deploy.sh
