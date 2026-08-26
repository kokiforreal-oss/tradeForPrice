#!/usr/bin/env bash
# 服务器执行：在确认 Docker 应用已健康后，卸掉裸机 systemd / .venv。
# 不会删除 .env、data/、MySQL、Nginx、业务代码。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/docker-lib.sh"

if ! curl -fsS --connect-timeout 2 http://127.0.0.1:8000/api/health >/dev/null; then
  echo "127.0.0.1:8000 健康检查失败。请先保证 docker compose 里的应用在跑，再清理裸机。"
  echo "查看：docker compose ps -a && docker compose logs --tail=50"
  exit 1
fi

if ! dc ps 2>/dev/null | grep -E 'trade' | grep -qiE 'up|running'; then
  echo "未检测到正在运行的 trade 容器，拒绝清理。"
  dc ps -a || true
  exit 1
fi

echo "Docker 应用正常，开始卸裸机进程…"

if systemctl list-unit-files 2>/dev/null | grep -q '^trade.service'; then
  systemctl stop trade 2>/dev/null || true
  systemctl disable trade 2>/dev/null || true
fi
rm -f /etc/systemd/system/trade.service
systemctl daemon-reload 2>/dev/null || true
echo "已删除 systemd 单元 trade.service"

pkill -f '/opt/trade/.venv/bin/uvicorn' 2>/dev/null || true

if [[ -d .venv ]]; then
  rm -rf .venv
  echo "已删除 /opt/trade/.venv"
fi

find "$ROOT" -type d -name __pycache__ -not -path './.git/*' -prune -exec rm -rf {} + 2>/dev/null || true

echo
echo "保留未动：.env、data/（e2e.key 与上传）、MySQL、Nginx、Docker 与业务代码。"
echo "以后不要在服务器执行 ./start.sh。"
echo "升级请在本机：./upgrade.sh root@公网IP:/opt/trade"
echo "备份：cd /opt/trade && ./backup.sh"
