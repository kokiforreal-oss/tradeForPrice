#!/usr/bin/env bash
# 在服务器项目目录执行：./backup.sh
# 备份 MySQL、.env、data/e2e.key、data/uploads，不改业务数据。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DEST="${BACKUP_DIR:-/opt/trade-backups}"
KEEP="${BACKUP_KEEP:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORKDIR="$(mktemp -d)"
ARCHIVE="$DEST/trade-$STAMP.tar.gz"

if [[ ! -f .env ]]; then
  echo "缺少 .env，拒绝备份。"
  exit 1
fi

mkdir -p "$DEST"
chmod 700 "$DEST"

if [[ ! -d .venv ]]; then
  echo "缺少 .venv，无法读取 DATABASE_URL。"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

DUMP="$WORKDIR/trade.sql"
python - "$DUMP" <<'PY'
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

out = Path(sys.argv[1])
sys.path.insert(0, str(Path.cwd()))
from app.config import settings
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
    print("DATABASE_URL 没有库名。", file=sys.stderr)
    raise SystemExit(1)

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
try:
    with out.open("w", encoding="utf-8") as fh:
        subprocess.run(cmd, check=True, stdout=fh, stderr=subprocess.PIPE, env=os.environ.copy())
except FileNotFoundError:
    print("未找到 mysqldump，请先安装：dnf -y install mysql", file=sys.stderr)
    raise SystemExit(1)
except subprocess.CalledProcessError as exc:
    err = (exc.stderr or b"").decode("utf-8", "replace")
    print("mysqldump 失败：", err, file=sys.stderr)
    raise SystemExit(1)
print(f"已导出数据库 {db}")
PY

cp -a .env "$WORKDIR/dotenv"
if [[ -f data/e2e.key ]]; then
  cp -a data/e2e.key "$WORKDIR/e2e.key"
else
  echo "警告：没有 data/e2e.key，加密业务数据将来可能解不开。"
fi
if [[ -d data/uploads ]]; then
  mkdir -p "$WORKDIR/uploads"
  cp -a data/uploads/. "$WORKDIR/uploads/"
fi

tar -C "$WORKDIR" -czf "$ARCHIVE" .
chmod 600 "$ARCHIVE"
rm -rf "$WORKDIR"

# 只保留最近 KEEP 份
ls -1t "$DEST"/trade-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "备份完成：$ARCHIVE"
echo "请再拷一份到本机或 OSS，不要只放在这台 ECS 上。"
