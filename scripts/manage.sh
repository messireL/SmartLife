#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="$ROOT_DIR/.env"
SECRETS_DIR="$ROOT_DIR/secrets"
DEFAULT_PORT="13443"
DEFAULT_NETWORK_MODE="lan"
DEFAULT_LAN_SUBNET_PREFIX="192.168."

copy_env_template() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  fi
}

load_env() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
}

upsert_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    od -An -N 32 -tx1 /dev/urandom | tr -d ' \n'
  fi
}

ensure_secret_file() {
  local name="$1"
  local default_value="${2:-}"
  local path="$SECRETS_DIR/$name"
  if [[ ! -f "$path" ]]; then
    printf '%s' "$default_value" > "$path"
  fi
  chmod 600 "$path" 2>/dev/null || true
}

write_secret_file() {
  local name="$1"
  local value="$2"
  mkdir -p "$SECRETS_DIR"
  printf '%s' "$value" > "$SECRETS_DIR/$name"
  chmod 600 "$SECRETS_DIR/$name" 2>/dev/null || true
}

read_secret_file() {
  local name="$1"
  local path="$SECRETS_DIR/$name"
  [[ -f "$path" ]] && cat "$path" || true
}

ensure_secrets() {
  mkdir -p "$SECRETS_DIR"
  ensure_secret_file app_secret_key "$(random_secret)"
  ensure_secret_file db_password "$(random_secret)"
  ensure_secret_file smartlife_tuya_access_id ""
  ensure_secret_file smartlife_tuya_access_secret ""
  ensure_secret_file smartlife_tuya_project_code ""
  ensure_secret_file smartlife_xiaomi_username ""
  ensure_secret_file smartlife_xiaomi_password ""
  ensure_secret_file smartlife_xiaomi_device_token ""
}

is_private_ip() {
  local ip="$1"
  [[ "$ip" =~ ^10\. ]] && return 0
  [[ "$ip" =~ ^192\.168\. ]] && return 0
  [[ "$ip" =~ ^172\.(1[6-9]|2[0-9]|3[0-1])\. ]] && return 0
  [[ "$ip" == "127.0.0.1" ]] && return 0
  return 1
}

rank_ip() {
  local ip="$1"
  local lan_prefix="${SMARTLIFE_LAN_SUBNET_PREFIX:-$DEFAULT_LAN_SUBNET_PREFIX}"

  if [[ "$ip" == ${lan_prefix}* ]]; then
    echo "1 $ip"
  elif [[ "$ip" =~ ^192\.168\. ]]; then
    echo "2 $ip"
  elif [[ "$ip" =~ ^10\. ]]; then
    echo "3 $ip"
  elif [[ "$ip" =~ ^172\.(1[6-9]|2[0-9]|3[0-1])\. ]]; then
    echo "4 $ip"
  elif [[ "$ip" == "127.0.0.1" ]]; then
    echo "8 $ip"
  elif [[ "$ip" == "0.0.0.0" ]]; then
    echo "9 $ip"
  else
    echo "7 $ip"
  fi
}

print_available_ips() {
  local -n ip_list_ref=$1
  mapfile -t ip_list_ref < <(ip -o -4 addr show up scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | awk '!/^127\./' | sort -u)

  if [[ ${#ip_list_ref[@]} -eq 0 ]]; then
    ip_list_ref=("127.0.0.1")
  fi

  if [[ "${SMARTLIFE_LAN_ONLY:-yes}" == "yes" ]]; then
    local lan_candidates=()
    local ip
    for ip in "${ip_list_ref[@]}"; do
      if is_private_ip "$ip"; then
        lan_candidates+=("$ip")
      fi
    done
    if [[ ${#lan_candidates[@]} -gt 0 ]]; then
      ip_list_ref=("${lan_candidates[@]}")
    fi
  else
    ip_list_ref+=("0.0.0.0")
  fi

  mapfile -t ip_list_ref < <(
    for ip in "${ip_list_ref[@]}"; do
      rank_ip "$ip"
    done | sort -k1,1n -k2,2 | awk '{print $2}'
  )

  echo "Доступные IPv4-адреса для публикации SmartLife:" >&2
  local i
  for i in "${!ip_list_ref[@]}"; do
    printf '  %d) %s\n' "$((i + 1))" "${ip_list_ref[$i]}" >&2
  done
}

choose_bind_ip() {
  local detected_ips=()
  print_available_ips detected_ips

  local default_index=1
  local current="${SMARTLIFE_BIND_IP:-}"
  local i
  for i in "${!detected_ips[@]}"; do
    if [[ "${detected_ips[$i]}" == "$current" ]]; then
      default_index="$((i + 1))"
      break
    fi
  done

  local choice=""
  read -r -p "Выбери номер IP [${default_index}]: " choice
  choice="${choice:-$default_index}"

  if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#detected_ips[@]} )); then
    printf '%s' "${detected_ips[$((choice - 1))]}"
    return 0
  fi

  printf '%s' "$choice"
}

choose_public_port() {
  local current_port="${SMARTLIFE_PUBLIC_PORT:-$DEFAULT_PORT}"
  local port=""
  read -r -p "Порт публикации SmartLife [${current_port}]: " port
  port="${port:-$current_port}"

  if ! [[ "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    echo "Некорректный порт: $port" >&2
    exit 1
  fi

  printf '%s' "$port"
}

validate_runtime() {
  local bind_ip="$1"
  local network_mode="${SMARTLIFE_NETWORK_MODE:-$DEFAULT_NETWORK_MODE}"
  local lan_only="${SMARTLIFE_LAN_ONLY:-yes}"

  if [[ "$network_mode" == "lan" && "$lan_only" == "yes" ]]; then
    if [[ "$bind_ip" == "0.0.0.0" ]]; then
      echo "В режиме LAN-only нельзя использовать 0.0.0.0. Выбери конкретный IP сервера из локальной сети." >&2
      exit 1
    fi
    if ! is_private_ip "$bind_ip"; then
      echo "В режиме LAN-only адрес должен быть локальным (192.168.x.x / 10.x.x.x / 172.16-31.x.x / 127.0.0.1). Получено: $bind_ip" >&2
      exit 1
    fi
  fi
}

configure_runtime() {
  copy_env_template
  load_env
  ensure_secrets

  upsert_env SMARTLIFE_NETWORK_MODE "${SMARTLIFE_NETWORK_MODE:-$DEFAULT_NETWORK_MODE}"
  upsert_env SMARTLIFE_LAN_ONLY "${SMARTLIFE_LAN_ONLY:-yes}"
  upsert_env SMARTLIFE_LAN_SUBNET_PREFIX "${SMARTLIFE_LAN_SUBNET_PREFIX:-$DEFAULT_LAN_SUBNET_PREFIX}"
  upsert_env SMARTLIFE_APP_HOST "0.0.0.0"
  upsert_env SMARTLIFE_APP_PORT "${SMARTLIFE_APP_PORT:-18089}"
  upsert_env SMARTLIFE_SYNC_INTERVAL_SECONDS "${SMARTLIFE_SYNC_INTERVAL_SECONDS:-60}"
  upsert_env SMARTLIFE_BACKGROUND_SYNC_ENABLED "${SMARTLIFE_BACKGROUND_SYNC_ENABLED:-yes}"
  upsert_env SMARTLIFE_SYNC_ON_STARTUP "${SMARTLIFE_SYNC_ON_STARTUP:-yes}"

  load_env

  local force_mode="${1:-no}"
  if [[ "${SMARTLIFE_RUNTIME_CONFIGURED:-no}" == "yes" && "$force_mode" != "yes" ]]; then
    return 0
  fi

  echo "Режим сети: ${SMARTLIFE_NETWORK_MODE:-$DEFAULT_NETWORK_MODE} (LAN-only=${SMARTLIFE_LAN_ONLY:-yes}, приоритет подсети ${SMARTLIFE_LAN_SUBNET_PREFIX:-$DEFAULT_LAN_SUBNET_PREFIX}x)" >&2

  local bind_ip
  bind_ip="$(choose_bind_ip)"
  validate_runtime "$bind_ip"

  local public_port
  public_port="$(choose_public_port)"

  upsert_env SMARTLIFE_BIND_IP "$bind_ip"
  upsert_env SMARTLIFE_PUBLIC_PORT "$public_port"
  upsert_env SMARTLIFE_APP_BASE_URL "http://${bind_ip}:${public_port}"
  upsert_env SMARTLIFE_RUNTIME_CONFIGURED yes

  load_env

  echo "Конфигурация сохранена: ${SMARTLIFE_APP_BASE_URL}" >&2
}

choose_tuya_base_url() {
  load_env
  local current="${SMARTLIFE_TUYA_BASE_URL:-https://openapi.tuyaeu.com}"
  echo "Выбери региональный Tuya OpenAPI endpoint:" >&2
  echo "  1) Europe   https://openapi.tuyaeu.com" >&2
  echo "  2) America  https://openapi.tuyaus.com" >&2
  echo "  3) China    https://openapi.tuyacn.com" >&2
  echo "  4) India    https://openapi.tuyain.com" >&2
  echo "  5) Ввести вручную" >&2

  local default_choice=1
  case "$current" in
    https://openapi.tuyaeu.com) default_choice=1 ;;
    https://openapi.tuyaus.com) default_choice=2 ;;
    https://openapi.tuyacn.com) default_choice=3 ;;
    https://openapi.tuyain.com) default_choice=4 ;;
    *) default_choice=5 ;;
  esac

  local choice=""
  read -r -p "Номер endpoint [${default_choice}]: " choice
  choice="${choice:-$default_choice}"
  case "$choice" in
    1) printf '%s' "https://openapi.tuyaeu.com" ;;
    2) printf '%s' "https://openapi.tuyaus.com" ;;
    3) printf '%s' "https://openapi.tuyacn.com" ;;
    4) printf '%s' "https://openapi.tuyain.com" ;;
    5)
      local manual=""
      read -r -p "Введи полный Tuya OpenAPI URL [${current}]: " manual
      printf '%s' "${manual:-$current}"
      ;;
    *)
      echo "Неизвестный вариант: $choice" >&2
      exit 1
      ;;
  esac
}

configure_tuya() {
  copy_env_template
  load_env
  ensure_secrets
  configure_runtime

  local base_url
  base_url="$(choose_tuya_base_url)"

  local current_id current_secret current_project
  current_id="$(read_secret_file smartlife_tuya_access_id)"
  current_secret="$(read_secret_file smartlife_tuya_access_secret)"
  current_project="$(read_secret_file smartlife_tuya_project_code)"

  local access_id=""
  read -r -p "Tuya Access ID [${current_id:-пусто}]: " access_id
  access_id="${access_id:-$current_id}"

  local access_secret=""
  read -r -s -p "Tuya Access Secret [скрыто, Enter = оставить как есть]: " access_secret
  echo >&2
  access_secret="${access_secret:-$current_secret}"

  local project_code=""
  read -r -p "Tuya Project ID/Code [${current_project:-необязательно}]: " project_code
  project_code="${project_code:-$current_project}"

  if [[ -z "$access_id" || -z "$access_secret" ]]; then
    echo "Tuya Access ID и Access Secret обязательны." >&2
    exit 1
  fi

  write_secret_file smartlife_tuya_access_id "$access_id"
  write_secret_file smartlife_tuya_access_secret "$access_secret"
  write_secret_file smartlife_tuya_project_code "$project_code"

  upsert_env SMARTLIFE_PROVIDER tuya_cloud
  upsert_env SMARTLIFE_TUYA_BASE_URL "$base_url"

  echo "Tuya Cloud настроен. Провайдер переключён на tuya_cloud, endpoint=${base_url}" >&2
  echo "Дальше можно запустить ./scripts/manage.sh up --build и ./scripts/manage.sh sync" >&2
}

configure_sync() {
  copy_env_template
  load_env
  ensure_secrets
  configure_runtime

  local current_enabled="${SMARTLIFE_BACKGROUND_SYNC_ENABLED:-yes}"
  local enabled=""
  read -r -p "Включить фоновую синхронизацию [${current_enabled}]: " enabled
  enabled="${enabled:-$current_enabled}"
  case "$enabled" in
    yes|no|true|false|1|0) ;;
    *)
      echo "Используй yes/no." >&2
      exit 1
      ;;
  esac

  local current_startup="${SMARTLIFE_SYNC_ON_STARTUP:-yes}"
  local startup=""
  read -r -p "Запускать синхронизацию сразу при старте приложения [${current_startup}]: " startup
  startup="${startup:-$current_startup}"
  case "$startup" in
    yes|no|true|false|1|0) ;;
    *)
      echo "Используй yes/no." >&2
      exit 1
      ;;
  esac

  local current_interval="${SMARTLIFE_SYNC_INTERVAL_SECONDS:-60}"
  local interval=""
  read -r -p "Интервал фоновой синхронизации в секундах [${current_interval}]: " interval
  interval="${interval:-$current_interval}"
  if ! [[ "$interval" =~ ^[0-9]+$ ]] || (( interval < 15 )); then
    echo "Интервал должен быть целым числом не меньше 15 секунд." >&2
    exit 1
  fi

  upsert_env SMARTLIFE_BACKGROUND_SYNC_ENABLED "$enabled"
  upsert_env SMARTLIFE_SYNC_ON_STARTUP "$startup"
  upsert_env SMARTLIFE_SYNC_INTERVAL_SECONDS "$interval"

  echo "Настройки синхронизации обновлены: background=${enabled}, startup=${startup}, interval=${interval}s" >&2
}

configure_demo() {
  copy_env_template
  load_env
  ensure_secrets
  configure_runtime
  upsert_env SMARTLIFE_PROVIDER demo
  echo "Провайдер переключён на demo." >&2
}

compose() {
  docker compose "$@"
}

health_url() {
  load_env
  printf 'http://%s:%s/health' "${SMARTLIFE_BIND_IP:-127.0.0.1}" "${SMARTLIFE_PUBLIC_PORT:-$DEFAULT_PORT}"
}

show_url() {
  load_env
  printf 'http://%s:%s/' "${SMARTLIFE_BIND_IP:-127.0.0.1}" "${SMARTLIFE_PUBLIC_PORT:-$DEFAULT_PORT}"
}

show_banner() {
  load_env
  echo
  echo "SmartLife готов в локальной сети: $(show_url)"
  echo "Режим: ${SMARTLIFE_NETWORK_MODE:-$DEFAULT_NETWORK_MODE}; bind IP: ${SMARTLIFE_BIND_IP:-127.0.0.1}; port: ${SMARTLIFE_PUBLIC_PORT:-$DEFAULT_PORT}; provider: ${SMARTLIFE_PROVIDER:-demo}"
  echo "Внутренний bind приложения: ${SMARTLIFE_APP_HOST:-0.0.0.0}:${SMARTLIFE_APP_PORT:-18089}"
  echo "Фоновая синхронизация: ${SMARTLIFE_BACKGROUND_SYNC_ENABLED:-yes}; стартовый прогон: ${SMARTLIFE_SYNC_ON_STARTUP:-yes}; интервал: ${SMARTLIFE_SYNC_INTERVAL_SECONDS:-60}s"
  echo
}

wait_for_http() {
  local url="$1"
  local attempts="${2:-30}"
  local sleep_seconds="${3:-2}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_seconds"
  done
  return 1
}

wait_for_container_http() {
  local url="$1"
  local attempts="${2:-30}"
  local sleep_seconds="${3:-2}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if compose exec -T app sh -lc "curl -fsS --max-time 5 '$url' >/dev/null" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_seconds"
  done
  return 1
}

show_app_logs() {
  echo >&2
  echo "Последние логи app:" >&2
  compose logs --tail=200 app >&2 || true
  echo >&2
}

verify_app_ready() {
  local internal_url="http://127.0.0.1:${SMARTLIFE_APP_PORT:-18089}/health"
  local external_url
  external_url="$(health_url)"

  if ! wait_for_container_http "$internal_url" 45 2; then
    echo "SmartLife внутри контейнера ещё не отвечает на ${internal_url}" >&2
    show_app_logs
    return 1
  fi

  if ! wait_for_http "$external_url" 30 2; then
    echo "SmartLife внутри контейнера запущен, но опубликованный URL пока недоступен: $external_url" >&2
    echo "Проверь, что выбранный bind IP реально назначен серверу и не блокируется firewall." >&2
    show_app_logs
    return 1
  fi

  return 0
}

case "${1:-}" in
  configure)
    configure_runtime yes
    show_banner
    ;;
  configure-tuya)
    configure_tuya
    show_banner
    ;;
  configure-demo)
    configure_demo
    show_banner
    ;;
  configure-sync)
    configure_sync
    show_banner
    ;;
  up)
    shift || true
    configure_runtime
    compose up -d "$@"
    show_banner
    verify_app_ready
    ;;
  down)
    compose down
    ;;
  build)
    configure_runtime
    compose build --no-cache
    show_banner
    ;;
  logs)
    compose logs -f --tail=200
    ;;
  restart)
    compose restart
    show_banner
    ;;
  ps)
    compose ps
    ;;
  sync)
    compose exec app python -m app.commands.sync_provider
    ;;
  seed-demo)
    configure_demo
    compose exec app python -m app.commands.seed_demo
    ;;
  shell)
    compose exec app bash
    ;;
  health)
    if ! verify_app_ready; then
      exit 1
    fi
    curl -fsS "$(health_url)"
    ;;
  url)
    echo "$(show_url)"
    ;;
  *)
    echo "Usage: $0 {configure|configure-tuya|configure-demo|configure-sync|up [--build]|down|build|logs|restart|ps|sync|seed-demo|shell|health|url}"
    exit 1
    ;;
esac
