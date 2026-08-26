# shellcheck shell=bash
dc() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "未找到 docker compose。请先安装 docker-compose-plugin，或执行 ./docker-setup.sh"
    exit 1
  fi
}
