#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

compose() {
  docker compose "$@"
}

case "${1:-}" in
  up)
    shift || true
    compose up -d "$@"
    ;;
  down)
    compose down
    ;;
  build)
    compose build --no-cache
    ;;
  logs)
    compose logs -f --tail=200
    ;;
  restart)
    compose restart
    ;;
  ps)
    compose ps
    ;;
  seed-demo)
    compose exec app python -m app.commands.seed_demo
    ;;
  shell)
    compose exec app bash
    ;;
  health)
    curl -fsS http://127.0.0.1:18089/health || true
    ;;
  *)
    echo "Usage: $0 {up [--build]|down|build|logs|restart|ps|seed-demo|shell|health}"
    exit 1
    ;;
esac
