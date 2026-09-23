#!/usr/bin/env bash

# freedom-accounts 一键安装脚本。
# 交互式生成 .env，处理数据目录，并用 Docker Compose 启动前后端容器。
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"
DATA_DIR="$SCRIPT_DIR/data"
DEFAULT_LISTEN_IP="127.0.0.1"
DEFAULT_PORT="8080"
DEFAULT_IMAGE="cloakhq/cloakbrowser:latest"

fail() {
  echo "错误: $*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

prompt_value() {
  local message="$1"
  local default_value="$2"
  local reply=""
  read -r -p "$message [$default_value]: " reply
  printf '%s' "${reply:-$default_value}"
}

prompt_secret_or_default() {
  local message="$1"
  local default_value="$2"
  local reply=""
  while true; do
    read -r -s -p "$message" reply
    echo >&2
    if [[ -z "$reply" ]]; then
      printf '%s' "$default_value"
      return
    fi
    if [[ ${#reply} -lt 8 ]]; then
      echo "密码至少 8 位，请重新输入。" >&2
      continue
    fi
    printf '%s' "$reply"
    return
  done
}

prompt_rebuild() {
  local message="$1"
  local reply=""
  read -r -p "$message" reply
  [[ "$reply" =~ ^([Rr]|[Rr]ebuild|重建)$ ]]
}

validate_ipv4() {
  local ip="$1"
  local octet
  [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1

  IFS='.' read -r -a octets <<< "$ip"
  for octet in "${octets[@]}"; do
    (( octet >= 0 && octet <= 255 )) || return 1
  done
}

validate_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( "$1" >= 1 && "$1" <= 65535 ))
}

random_fernet_key() {
  if command_exists openssl; then
    openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
  else
    python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'
  fi
}

random_jwt_secret() {
  if command_exists openssl; then
    openssl rand -hex 32
  else
    python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
  fi
}

random_admin_password() {
  if command_exists openssl; then
    openssl rand -base64 18 | tr '+/' '-_' | tr -d '=\n'
  else
    python3 -c 'import secrets; print(secrets.token_urlsafe(18))'
  fi
}

env_get() {
  local key="$1"
  local default_value="${2-}"
  local value=""
  value="$(awk -v key="$key" '
    index($0, key "=") == 1 {
      sub("^" key "=", "")
      print $0
      found = 1
      exit
    }
    END { if (!found) exit 1 }
  ' "$ENV_FILE" 2>/dev/null || true)"
  printf '%s' "${value:-$default_value}"
}

env_set() {
  local key="$1"
  local value="$2"
  local tmp_file
  tmp_file="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
  awk -v key="$key" -v value="$value" '
    index($0, key "=") == 1 {
      print key "=" value
      found = 1
      next
    }
    { print }
    END { if (!found) print key "=" value }
  ' "$ENV_FILE" > "$tmp_file"
  mv "$tmp_file" "$ENV_FILE"
}

ensure_compose() {
  if docker compose version >/dev/null 2>&1; then
    compose() { docker compose "$@"; }
  elif command_exists docker-compose; then
    compose() { docker-compose "$@"; }
  else
    fail "未找到 Docker Compose，请先安装 Docker Desktop 或 docker-compose-plugin。"
  fi

  docker info >/dev/null 2>&1 || fail "无法连接 Docker daemon，请先启动 Docker。"
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  fail "请直接执行 ./install.sh"
fi

command_exists docker || fail "未找到 docker，请先安装并启动 Docker。"

echo "=========================================="
echo " freedom-accounts 一键安装"
echo "=========================================="
echo "配置说明：直接按回车即可使用方括号中的默认值。"
echo

# 保留旧配置可避免覆盖已有密钥；重新生成前会自动备份旧 .env。
if [[ -f "$ENV_FILE" ]]; then
  echo "检测到已有 .env 文件。"
  if prompt_rebuild "回车=保留并补齐配置；输入 r=备份后重新生成: "; then
    backup_file="${ENV_FILE}.backup.$(date +%Y%m%d%H%M%S)"
    mv "$ENV_FILE" "$backup_file"
    chmod 600 "$backup_file"
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "已备份旧配置: $backup_file"
  else
    echo "保留现有 .env，只更新本次输入的配置。"
  fi
else
  cp "$ENV_EXAMPLE" "$ENV_FILE"
fi

listen_ip="$(env_get FA_LISTEN_IP "$DEFAULT_LISTEN_IP")"
listen_port="$(env_get FA_PORT "$DEFAULT_PORT")"
admin_user="$(env_get FA_ADMIN_USER "admin")"
admin_password="$(env_get FA_ADMIN_PASSWORD "")"
license_key="$(env_get CLOAKBROWSER_LICENSE_KEY "")"
cloak_image="$(env_get CLOAKBROWSER_IMAGE "$DEFAULT_IMAGE")"
jwt_expire_hours="$(env_get FA_JWT_EXPIRE_HOURS "24")"
callback_timeout="$(env_get FA_CALLBACK_TIMEOUT "15")"
max_concurrency="$(env_get FA_MAX_CONCURRENCY "5")"
idle_timeout="$(env_get CLOAKSERVE_IDLE_TIMEOUT "0")"

while true; do
  listen_ip="$(prompt_value "请输入服务监听 IP（127.0.0.1=仅本机，0.0.0.0=所有网卡）" "$listen_ip")"
  if validate_ipv4 "$listen_ip"; then
    break
  fi
  echo "IP 格式无效，请输入 IPv4 地址，例如 127.0.0.1 或 192.168.1.10。"
done

while true; do
  listen_port="$(prompt_value "请输入服务端口" "$listen_port")"
  if validate_port "$listen_port"; then
    break
  fi
  echo "端口无效，请输入 1-65535 之间的数字。"
done

while true; do
  admin_user="$(prompt_value "请输入管理员账号" "$admin_user")"
  [[ -n "$admin_user" ]] && break
  echo "管理员账号不能为空。"
done

if [[ -z "$admin_password" ]]; then
  generated_password="$(random_admin_password)"
  admin_password="$(prompt_secret_or_default "请输入管理员密码（回车=自动生成强密码）: " "$generated_password")"
else
  echo "已检测到现有管理员密码，直接按回车可继续使用；也可输入新密码。"
  admin_password="$(prompt_secret_or_default "请输入管理员密码（回车=保留现有配置）: " "$admin_password")"
fi

license_key="$(prompt_value "请输入 CloakBrowser Pro License（回车=使用免费版）" "$license_key")"
cloak_image="$(prompt_value "请输入 CloakBrowser 镜像" "$cloak_image")"
jwt_expire_hours="$(prompt_value "请输入登录态有效期（小时）" "$jwt_expire_hours")"
callback_timeout="$(prompt_value "请输入上游回调超时（秒）" "$callback_timeout")"
max_concurrency="$(prompt_value "请输入分组最大并发数" "$max_concurrency")"
idle_timeout="$(prompt_value "请输入 cloakserve 会话空闲清理时间（秒，0=禁用）" "$idle_timeout")"

encryption_key="$(env_get FA_ENCRYPTION_KEY "")"
if [[ -z "$encryption_key" ]]; then
  encryption_key="$(random_fernet_key)"
  echo "已自动生成数据库敏感字段加密密钥。"
fi

jwt_secret="$(env_get FA_JWT_SECRET "")"
if [[ -z "$jwt_secret" ]]; then
  jwt_secret="$(random_jwt_secret)"
  echo "已自动生成 JWT 签名密钥。"
fi

env_set FA_LISTEN_IP "$listen_ip"
env_set FA_PORT "$listen_port"
env_set FA_ENCRYPTION_KEY "$encryption_key"
env_set FA_ADMIN_USER "$admin_user"
env_set FA_JWT_SECRET "$jwt_secret"
env_set FA_ADMIN_PASSWORD "$admin_password"
env_set FA_JWT_EXPIRE_HOURS "$jwt_expire_hours"
env_set FA_CALLBACK_TIMEOUT "$callback_timeout"
env_set FA_MAX_CONCURRENCY "$max_concurrency"
env_set CLOAKBROWSER_LICENSE_KEY "$license_key"
env_set CLOAKBROWSER_IMAGE "$cloak_image"
env_set CLOAKSERVE_IDLE_TIMEOUT "$idle_timeout"
chmod 600 "$ENV_FILE"

ensure_compose

# 启动前先停止旧项目，避免重建数据目录时 bind mount 仍被容器占用。
echo "停止旧容器（如果存在）..."
compose down

if [[ -d "$DATA_DIR" ]] && [[ -n "$(ls -A "$DATA_DIR" 2>/dev/null)" ]]; then
  echo "检测到已有数据目录: $DATA_DIR"
  if prompt_rebuild "回车=跳过并保留已有数据；输入 r=重建数据（旧目录会改名备份）: "; then
    data_backup="${DATA_DIR}.backup.$(date +%Y%m%d%H%M%S)"
    mv "$DATA_DIR" "$data_backup"
    mkdir -p "$DATA_DIR/app"
    chmod 700 "$DATA_DIR"
    echo "已保留旧数据并备份到: $data_backup"
  else
    echo "跳过数据处理，保留现有 data 目录。"
    mkdir -p "$DATA_DIR/app"
  fi
else
  mkdir -p "$DATA_DIR/app"
  echo "已创建数据目录: $DATA_DIR"
fi

# 启动前固定判断旧库；避免应用启动初始化数据库后误判为新密码不可见。
existing_database=0
if [[ -f "$DATA_DIR/app/platform.db" ]]; then
  existing_database=1
fi

echo "构建并启动容器..."
compose up -d --build

display_ip="$listen_ip"
if [[ "$listen_ip" == "0.0.0.0" ]]; then
  display_ip="127.0.0.1"
fi

echo
echo "=========================================="
echo " 安装完成，服务已启动"
echo "=========================================="
echo "登录地址: http://${display_ip}:${listen_port}"
echo "登录账号: ${admin_user}"
if (( existing_database )); then
  echo "登录密码: 使用现有数据库中的密码（本次没有重置旧数据密码）"
else
  echo "登录密码: ${admin_password}"
fi

if [[ "$listen_ip" == "0.0.0.0" ]]; then
  echo "安全提示: 服务已监听所有网卡，请确认防火墙策略。"
fi

echo
echo "容器状态:"
compose ps
echo
echo "常用命令:"
echo "  查看日志: docker compose logs -f app"
echo "  停止服务: docker compose down"
