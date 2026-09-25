#!/bin/sh
# Pulls and registers the default local model for Kontekst.
set -eu
export OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
BASE_MODEL="${OLLAMA_BASE_MODEL:-qwen3:14b}"
LOCAL_MODEL="${OLLAMA_LOCAL_MODEL:-qwen3-14b-bot}"
NUM_CTX="${OLLAMA_NUM_CTX:-8192}"
NUM_THREAD="${OLLAMA_NUM_THREAD:-16}"

echo "==> Waiting for Ollama at ${OLLAMA_HOST}"
i=0
until ollama list >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 90 ]; then
    echo "Ollama did not become ready in time."
    exit 1
  fi
  sleep 2
done

echo "==> Pulling ${BASE_MODEL} (first run can take a while)"
ollama pull "${BASE_MODEL}"

echo "==> Creating ${LOCAL_MODEL} (ctx=${NUM_CTX}, threads=${NUM_THREAD})"
TMP="$(mktemp)"
cat >"${TMP}" <<EOF
FROM ${BASE_MODEL}
PARAMETER num_ctx ${NUM_CTX}
PARAMETER num_thread ${NUM_THREAD}
EOF
ollama create "${LOCAL_MODEL}" -f "${TMP}"
rm -f "${TMP}"
echo "==> Local model ready: ${LOCAL_MODEL}"
ollama list
