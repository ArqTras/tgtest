#!/usr/bin/env bash
# Install Kontekst + local Ollama (qwen3:14b) via Docker Compose.
# After install, only TELEGRAM_BOT_TOKEN remains for you to set.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/kontekst}"
HTTP_PORT="${HTTP_PORT:-8787}"
OLLAMA_MODEL_BASE="${OLLAMA_MODEL_BASE:-qwen3:14b}"
OLLAMA_MODEL_NAME="${OLLAMA_MODEL_NAME:-qwen3-14b-bot}"
REPO_URL="${REPO_URL:-}"
ADMIN_TOKEN_DEFAULT="$(openssl rand -hex 18 2>/dev/null || head -c 24 /dev/urandom | xxd -p)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash $0"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates git openssl jq rsync >/dev/null

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
if ! docker compose version >/dev/null 2>&1; then
  echo "==> Installing docker-compose-plugin"
  apt-get install -y -qq docker-compose-plugin || apt-get install -y -qq docker-compose
fi
if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
  echo "Could not install Docker Compose."
  exit 1
fi
compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

echo "==> Installing Kontekst into ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
if [[ -n "${REPO_URL}" ]]; then
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    git -C "${INSTALL_DIR}" pull --ff-only
  else
    git clone "${REPO_URL}" "${INSTALL_DIR}"
  fi
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
  if [[ -f "${ROOT_DIR}/docker-compose.yml" && -f "${ROOT_DIR}/Dockerfile" ]]; then
    rsync -a --delete \
      --exclude '.git' --exclude '.venv' --exclude 'data' --exclude 'agent-tools' \
      --exclude '.env' --exclude '*.tgz' --exclude '*.tar.gz' \
      "${ROOT_DIR}/" "${INSTALL_DIR}/"
  else
    echo "Missing REPO_URL and local project files."
    exit 1
  fi
fi

cd "${INSTALL_DIR}"
chmod +x scripts/ollama-init.sh install.sh || true

EXISTING_TOKEN=""
EXISTING_ADMIN=""
if [[ -f .env ]]; then
  EXISTING_TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2- || true)"
  EXISTING_ADMIN="$(grep -E '^ADMIN_TOKEN=' .env | cut -d= -f2- || true)"
fi
ADMIN_TOKEN="${EXISTING_ADMIN:-$ADMIN_TOKEN_DEFAULT}"

cat >.env <<EOF
# === SET ONLY THIS ===
TELEGRAM_BOT_TOKEN=${EXISTING_TOKEN}

# Local Ollama inside Compose (default)
LLM_BASE_URL=http://ollama:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=${OLLAMA_MODEL_NAME}
OLLAMA_BASE_MODEL=${OLLAMA_MODEL_BASE}
OLLAMA_LOCAL_MODEL=${OLLAMA_MODEL_NAME}
OLLAMA_NUM_CTX=8192
OLLAMA_NUM_THREAD=16
OLLAMA_PORT=11434
ADMIN_TOKEN=${ADMIN_TOKEN}
HTTP_PORT=${HTTP_PORT}
ALLOW_PRIVATE_URLS=false
LEARN_EVERY=1
EOF

echo "==> Starting Ollama + pulling ${OLLAMA_MODEL_BASE} + Kontekst"
echo "    First model download can take several minutes / ~9GB."
compose up -d --build

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q 'Status: active'; then
  ufw allow "${HTTP_PORT}/tcp" || true
  ufw allow 11434/tcp || true
fi

cat >/usr/local/bin/kontekst-set-token <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
ENV=/opt/kontekst/.env
if [[ $# -ne 1 ]]; then
  echo "Usage: kontekst-set-token 123456:ABC-TOKEN-FROM-BOTFATHER"
  exit 1
fi
TOKEN="$1"
sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${TOKEN}|" "$ENV"
cd /opt/kontekst
if docker compose version >/dev/null 2>&1; then
  docker compose up -d kontekst
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose up -d kontekst
else
  echo "Docker Compose missing"
  exit 1
fi
echo "Token saved. Status: http://127.0.0.1:8787/health"
EOS
chmod +x /usr/local/bin/kontekst-set-token

echo
echo "=============================================="
echo "Kontekst install started."
echo "Status:  http://127.0.0.1:${HTTP_PORT}"
echo "Ollama:  http://127.0.0.1:11434"
echo "Model:   ${OLLAMA_MODEL_NAME} (from ${OLLAMA_MODEL_BASE})"
echo "Admin:   ADMIN_TOKEN is in ${INSTALL_DIR}/.env"
echo
echo "Watch the model pull:"
echo "  docker logs -f kontekst-ollama-init"
echo
echo "Then set the bot token:"
echo "  sudo kontekst-set-token '123456:TOKEN_FROM_BOTFATHER'"
echo "=============================================="
