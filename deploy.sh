#!/usr/bin/env bash
# 在服务器项目目录执行：./deploy.sh
# 只更新代码与依赖，不覆盖 .env / data/，升级前自动备份 MySQL。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "缺少 .env，拒绝部署，以免连到空库或写错库。"
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "正在创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

BACKUP_DIR="$ROOT/data/backups"
mkdir -p "$BACKUP_DIR"

python - <<'PY'
"""Dump MySQL using DATABASE_URL from .env; never DROP."""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

root = Path.cwd()
sys.path.insert(0, str(root))
from app.config import DATA_DIR, settings
from app.db.database import _database_url

url = _database_url(settings.database_url)
if not url.startswith("mysql"):
    print("当前不是 MySQL，跳过 mysqldump。")
    raise SystemExit(0)

parsed = urlparse(url)
user = unquote(parsed.username or "")
password = unquote(parsed.password or "")
host = parsed.hostname or "127.0.0.1"
port = str(parsed.port or 3306)
db = (parsed.path or "/trade").lstrip("/").split("?")[0]
if not db:
    print("DATABASE_URL 没有库名，拒绝部署。", file=sys.stderr)
    raise SystemExit(1)

stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
out = DATA_DIR / "backups" / f"trade-{stamp}.sql"
cmd = [
    "mysqldump",
    "-h", host,
    "-P", port,
    "-u", user,
    f"--password={password}",
    "--single-transaction",
    "--routines",
    "--no-tablespaces",
    db,
]
env = os.environ.copy()
try:
    with out.open("w", encoding="utf-8") as fh:
        subprocess.run(cmd, check=True, stdout=fh, stderr=subprocess.PIPE, env=env)
except FileNotFoundError:
    print("未找到 mysqldump，请先安装 mysql-client。", file=sys.stderr)
    raise SystemExit(1)
except subprocess.CalledProcessError as exc:
    err = (exc.stderr or b"").decode("utf-8", "replace")
    print("数据库备份失败，已中止部署（不会改代码进程）：", err, file=sys.stderr)
    if out.exists():
        out.unlink()
    raise SystemExit(1)

print(f"已备份数据库到 {out}")
PY

if [[ -d data ]]; then
  echo "保留 data/（上传文件与 e2e.key），不会覆盖。"
fi

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q '^trade.service'; then
  sudo systemctl restart trade
  sudo systemctl --no-pager --full status trade | head -n 20
else
  echo "未检测到 trade.service。请自行重启 uvicorn；重启只会增量补表，不会清数据。"
fi

echo "部署完成。请确认登录后历史单据仍在。"
