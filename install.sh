#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "Docker Compose is missing."
    echo "Install: apt-get install -y docker-compose-plugin"
    exit 1
  fi
}

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is missing. Install Engine first: curl -fsSL https://get.docker.com | sh"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
  echo "Installing docker-compose-plugin…"
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq docker-compose-plugin || apt-get install -y -qq docker-compose || true
  fi
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  # Generate admin token if empty
  if command -v openssl >/dev/null 2>&1; then
    ADMIN="$(openssl rand -hex 18)"
    sed -i "s|^ADMIN_TOKEN=.*|ADMIN_TOKEN=${ADMIN}|" .env 2>/dev/null \
      || sed -i '' "s|^ADMIN_TOKEN=.*|ADMIN_TOKEN=${ADMIN}|" .env
  fi
  echo "Created .env with local Ollama defaults (qwen3:14b)."
  echo "Set TELEGRAM_BOT_TOKEN, then run ./install.sh again."
  exit 0
fi

# Force local Ollama defaults unless the user already pointed elsewhere
if ! grep -q '^LLM_BASE_URL=http://ollama:11434' .env 2>/dev/null; then
  if ! grep -q '^LLM_BASE_URL=.' .env 2>/dev/null || grep -q '^LLM_BASE_URL=$' .env; then
    {
      echo ""
      echo "LLM_BASE_URL=http://ollama:11434/v1"
      echo "LLM_API_KEY=ollama"
      echo "LLM_MODEL=qwen3-14b-bot"
    } >> .env
  fi
fi

chmod +x scripts/ollama-init.sh

echo "==> Starting Ollama + pulling qwen3:14b + Kontekst"
echo "    First model download can take several minutes."
compose up -d --build

echo
compose ps
HTTP_PORT="$(grep -E '^HTTP_PORT=' .env | cut -d= -f2- || true)"
echo
echo "Status: http://127.0.0.1:${HTTP_PORT:-8787}"
echo "Ollama: http://127.0.0.1:${OLLAMA_PORT:-11434}"
echo "Default model: qwen3-14b-bot (from qwen3:14b)"
echo
echo "Watch model pull: docker logs -f kontekst-ollama-init"
