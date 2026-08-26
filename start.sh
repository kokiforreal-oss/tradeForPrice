#!/usr/bin/env bash
# 本机启动：拉法国际外贸系统
# 用法：在项目目录执行  ./start.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3，请先安装 Python 3.9 或更高版本。"
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "正在创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "正在安装依赖 ..."
pip install -q -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已复制 .env.example 为 .env，请按本机 MySQL 账号修改 DATABASE_URL 后重新运行。"
  echo "示例：mysql+pymysql://trade:trade123@127.0.0.1:3306/trade?charset=utf8mb4"
  exit 1
fi

echo "启动服务：http://127.0.0.1:8000  （Ctrl+C 停止）"
echo "数据库只做增量建表/补列，不会清空已有数据；请勿覆盖 .env 与 data/（含 e2e.key）。"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
