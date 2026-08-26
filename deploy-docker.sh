#!/usr/bin/env bash
# 服务器上：备份 MySQL 后重建并启动应用容器（不覆盖 .env / data/）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/docker-lib.sh"

if [[ ! -f .env ]]; then
  echo "缺少 .env，拒绝部署。"
  exit 1
fi
if [[ ! -f docker-compose.yml ]]; then
  echo "缺少 docker-compose.yml。"
  exit 1
fi
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "Docker 未安装或未启动。请先执行：./docker-setup.sh"
  exit 1
fi

mkdir -p data/uploads/contracts data/backups

if systemctl is-active --quiet trade 2>/dev/null; then
  echo "停止 systemd trade，避免和容器抢 8000…"
  systemctl stop trade
  systemctl disable trade || true
fi

# 升级前 dump 库（只读 .env，不依赖 .venv）
python3 - <<'PY' || true
import os, subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

url = ""
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if s.startswith("DATABASE_URL="):
        url = s.split("=", 1)[1].strip().strip('"').strip("'")
        break
if not url or "mysql" not in url:
    print("跳过库备份：.env 中没有 MySQL DATABASE_URL")
    raise SystemExit(0)
if url.startswith("mysql+pymysql://"):
    url = "mysql://" + url[len("mysql+pymysql://") :]
parsed = urlparse(url)
user = unquote(parsed.username or "")
password = unquote(parsed.password or "")
host = parsed.hostname or "127.0.0.1"
port = str(parsed.port or 3306)
db = (parsed.path or "/trade").lstrip("/").split("?")[0]
stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
out = Path("data/backups") / f"trade-{stamp}.sql"
out.parent.mkdir(parents=True, exist_ok=True)
cmd = ["mysqldump", "-h", host, "-P", port, "-u", user, f"--password={password}",
       "--single-transaction", "--routines", "--no-tablespaces", db]
try:
    with out.open("w", encoding="utf-8") as fh:
        subprocess.run(cmd, check=True, stdout=fh, stderr=subprocess.PIPE, env=os.environ.copy())
    print(f"已备份数据库到 {out}")
except FileNotFoundError:
    print("未找到 mysqldump，跳过库备份。")
except subprocess.CalledProcessError as exc:
    print("数据库备份失败（仍继续发版）：", (exc.stderr or b"").decode("utf-8", "replace"))
PY

echo "正在构建并启动容器…"
dc up -d --build
dc ps -a
echo "等待服务监听 8000…"
ok=0
for i in $(seq 1 20); do
  if curl -fsS --connect-timeout 1 http://127.0.0.1:8000/api/health >/tmp/trade-health.json 2>/dev/null; then
    echo "健康检查：$(cat /tmp/trade-health.json)"
    ok=1
    break
  fi
  sleep 1
done
if [[ "$ok" != 1 ]]; then
  echo "健康检查未通过（127.0.0.1:8000 无响应）。容器日志如下："
  dc logs --tail=80
  echo
  echo "请把上面日志发回来。也可再执行：cd /opt/trade && docker compose ps -a && docker compose logs --tail=80"
  exit 1
fi
