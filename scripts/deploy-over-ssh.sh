#!/usr/bin/env bash
# Uruchom z laptopa w tej samej sieci co serwer.
# Przykład:
#   SERVER=arek@192.168.5.87 PASS='...' TELEGRAM_BOT_TOKEN='...' ./scripts/deploy-over-ssh.sh
set -euo pipefail

SERVER="${SERVER:-arek@192.168.5.87}"
PASS="${PASS:-}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/kontekst-bundle}"

if [[ -z "${PASS}" ]]; then
  echo "Ustaw PASS=hasło (albo użyj klucza SSH i zostaw PASS puste z SSH bez hasła)."
  exit 1
fi
if [[ -z "${TELEGRAM_BOT_TOKEN}" ]]; then
  echo "Ustaw TELEGRAM_BOT_TOKEN=token_z_BotFather"
  exit 1
fi

if ! command -v sshpass >/dev/null 2>&1; then
  echo "Zainstaluj sshpass (apt install sshpass / brew install sshpass)"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE="$(mktemp -d)/kontekst-bundle"
mkdir -p "${BUNDLE}"
rsync -a \
  --exclude '.git' --exclude '.venv' --exclude 'data' --exclude 'agent-tools' \
  --exclude '__pycache__' --exclude '.pytest_cache' --exclude 'kontekst-host-install.tgz' \
  --exclude '.env' \
  "${ROOT}/" "${BUNDLE}/"

SSH=(sshpass -p "${PASS}" ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no)
SCP=(sshpass -p "${PASS}" scp -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no)

echo "==> Kopiuję pliki na ${SERVER}"
"${SSH[@]}" "${SERVER}" "rm -rf ${REMOTE_DIR} && mkdir -p ${REMOTE_DIR}"
tar -C "$(dirname "${BUNDLE}")" -czf - "$(basename "${BUNDLE}")" | "${SSH[@]}" "${SERVER}" "tar -C /tmp -xzf -"

echo "==> Instaluję Docker + Ollama + Kontekst (sudo)"
"${SSH[@]}" "${SERVER}" "echo '${PASS}' | sudo -S bash ${REMOTE_DIR}/scripts/install-on-host.sh"

echo "==> Ustawiam token Telegram"
"${SSH[@]}" "${SERVER}" "echo '${PASS}' | sudo -S kontekst-set-token '${TELEGRAM_BOT_TOKEN}'"

echo "==> Health"
"${SSH[@]}" "${SERVER}" "curl -sf http://127.0.0.1:8787/health || true"
echo
echo "Gotowe. Bot powinien odpowiadać jako @TrasAI_bot (model lokalny qwen3-14b-bot)."
echo "Status: http://192.168.5.87:8787"
