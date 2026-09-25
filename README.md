# Kontekst

Bot Telegrama, który prowadzi rozmowę w oparciu o bieżący wątek, fakty wyciągnięte z wcześniejszych wypowiedzi i źródła wskazane dla projektu. Działa w Dockerze (Portainer-ready). **Domyślnie** startuje lokalne **Ollama + qwen3:14b** — bez Groq/DeepSeek. Na CPU (np. Xeon + 32/64 GB RAM) działa; GPU nie jest wymagane.

## Czego potrzebujesz

| Element | Po co |
|---|---|
| Komputer z Dockerem | VPS/desktop; ~16+ GB RAM dla qwen3:14b |
| Token z [@BotFather](https://t.me/BotFather) | połączenie z Telegramem |
| (opcjonalnie) klucz API modelu | tylko gdy wolisz Groq/DeepSeek zamiast lokalnej Ollamy |
| Hasło `ADMIN_TOKEN` | formularz źródeł na stronie statusu |

Domyślny silnik to lokalne Ollama (`qwen3-14b-bot`). Chmura jest opcją:

- [DeepSeek](https://platform.deepseek.com) — tani
- [Groq](https://console.groq.com) — szybki darmowy przydział
- [Google AI Studio](https://aistudio.google.com) — Gemini

## Jak bot się uczy

Nie dostraja wag modelu. Po odpowiedzi prosi model o najwyżej trzy trwałe fakty z tej wymiany i zapisuje je w SQLite na dysku. Przy kolejnym pytaniu szuka po tych faktach i po zindeksowanych źródłach (SQLite FTS5, bez embeddingów i bez GPU), dokleja trafienia do promptu i dopiero wtedy prosi o odpowiedź.

Źródła projektu są wspólne. Pamięć faktów jest osobna dla każdej rozmowy. `/zapomnij` czyści tylko bieżący czat.

## Run locally (default: Ollama + qwen3:14b)

```sh
cp .env.example .env
# set TELEGRAM_BOT_TOKEN (and ADMIN_TOKEN if empty)
chmod +x install.sh scripts/ollama-init.sh
./install.sh
```

`install.sh` starts three things: **Ollama**, a one-shot pull of **qwen3:14b** (as `qwen3-14b-bot`), and the **Kontekst** bot. The bot talks to `http://ollama:11434/v1` by default — no Groq/DeepSeek key required.

Status: [http://127.0.0.1:8787](http://127.0.0.1:8787)

W Telegramie napisz do bota `/start`. W grupie odzywa się, gdy go oznaczysz albo odpowiadasz na jego wiadomość. Żeby widział pozostałe wiadomości grupy, w BotFather wyłącz privacy mode (`/setprivacy` → Disable).

## Portainer

1. W Portainerze: **Stacks → Add stack**.
2. Nazwa, na przykład `kontekst`.
3. Metoda **Repository**: adres tego repozytorium, gałąź, ścieżka compose `docker-compose.yml`. Albo **Web editor** i wklej zawartość `docker-compose.yml`, jeśli obraz budujesz z wgranego katalogu (build wymaga plików obok compose).
4. W **Environment variables** ustaw:

```
TELEGRAM_BOT_TOKEN=123:ABC
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat
ADMIN_TOKEN=dlugie-haslo
HTTP_PORT=8787
```

5. Deploy. Portainer pokaże kontener `kontekst-bot` i wolumeny `kontekst-data` (rozmowy, pamięć) oraz `kontekst-sources` (pliki `.md` i `.txt`).

Redeploy stacka bez usuwania wolumenów zostawia pamięć. `docker compose down -v` kasuje ją razem z wolumenami.

Plik źródłowy wrzucisz z konsoli kontenera albo tak:

```sh
docker cp notatka.md kontekst-bot:/sources/notatka.md
```

Bot podchwytuje nowe pliki w ciągu minuty. To samo robi `/zrodlo https://...` i formularz na stronie statusu.

## Rozmowa

Zwykłe pytania w czacie są otwarte dla wszystkich. Slash-komendy (`/source`, `/sources`, `/remember`, `/memory`, `/summarize`, `/forget` i polskie aliasy) działają **tylko** dla administratora z `ADMIN_USERNAMES` (domyślnie `@ArqTras`).

- `/zrodlo https://adres` — pobierz i zindeksuj stronę
- `/zrodla` — lista źródeł
- `/zapamietaj tekst` — fakt bez czekania na model
- `/pamiec` — ostatnie fakty tej rozmowy
- `/podsumuj` — przejrzyj ostatnie wiadomości i dopisz nowe fakty
- `/zapomnij` — wyczyść historię i pamięć tej rozmowy

Pusty katalog źródeł dostaje na start plik `jak-dodac-zrodlo.md`. Usuń go, gdy wgrajesz własne materiały, inaczej bot może cytować instrukcję.

## Rozwój bez Dockera

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
export DATA_DIR=data SOURCES_DIR=sources HTTP_PORT=8787
python -m app
pytest
```

Bez tokenu proces i tak wstaje i serwuje `/health`, żeby Portainer widział, że kontener żyje. Odpowiedzi w Telegramie wymagają obu kluczy.
