#!/usr/bin/env bash
# 服务器执行一次：安装 Docker、停掉 systemd 的 trade、用容器接管 127.0.0.1:8000。
# Nginx、MySQL、.env、data/ 保持不变。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "缺少 .env，拒绝切换。"
  exit 1
fi

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    return 0
  fi
  echo "正在安装 Docker…"
  if command -v dnf >/dev/null 2>&1; then
    dnf -y install docker docker-compose-plugin || dnf -y install docker-ce docker-compose-plugin || dnf -y install docker
  elif command -v yum >/dev/null 2>&1; then
    yum -y install docker docker-compose-plugin || yum -y install docker
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y docker.io docker-compose-plugin || apt-get install -y docker.io docker-compose
  else
    echo "无法自动安装 Docker，请先手工安装后再执行本脚本。"
    exit 1
  fi
  systemctl enable --now docker
}

ensure_mirror() {
  mkdir -p /etc/docker
  if [[ -f /etc/docker/daemon.json ]]; then
    echo "已有 /etc/docker/daemon.json，不覆盖。若 build 拉不下 python 镜像，请自行加 registry-mirrors。"
    return 0
  fi
  cat >/etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": ["https://docker.m.daocloud.io"]
}
EOF
  systemctl restart docker
  echo "已写入 Docker 镜像加速（daoCloud）。"
}

install_docker
ensure_mirror

if ! docker info >/dev/null 2>&1; then
  echo "Docker 未能启动，请检查：systemctl status docker"
  exit 1
fi

# shellcheck disable=SC1091
source "$ROOT/docker-lib.sh"

if systemctl is-active --quiet trade 2>/dev/null; then
  echo "停止 systemd trade，避免和容器抢 8000 端口…"
  systemctl stop trade
fi
if systemctl is-enabled --quiet trade 2>/dev/null; then
  systemctl disable trade
  echo "已 disable trade.service。"
fi

ss -lntp 2>/dev/null | grep -q ':8000 ' && echo "注意：8000 仍被占用，若不是即将启动的容器，请先结束该进程。" || true

chmod +x "$ROOT/deploy-docker.sh"
"$ROOT/deploy-docker.sh"

echo
echo "已切换为 Docker 部署。Nginx 不用改，继续反代 http://127.0.0.1:8000 即可。"
echo "以后本机升级：./upgrade.sh root@公网IP:/opt/trade"
echo "不要 docker compose down -v（会碰到数据卷）。不要删除 /opt/trade/data。"
