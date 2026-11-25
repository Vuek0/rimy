#!/usr/bin/env bash
# Run a TEST copy of Rimy on this machine: the test bot from .env.local, a local database,
# and the Mini App through a temporary HTTPS tunnel (Cloudflare quick tunnel).
#
#   ./scripts/run_local.sh          # Ctrl+C stops the bot and the tunnel
#
# .env gives the shared settings (AI keys…), .env.local overrides them (BOT_TOKEN of the test bot!).
# Refuses to start with the production bot's token: two copies polling one bot steal each other's messages.

set -euo pipefail
cd "$(dirname "$0")/.."

token() { grep -E '^BOT_TOKEN=' "$1" | tail -1 | cut -d= -f2-; }
[[ -f .env.local ]] || { echo "no .env.local: put the TEST bot's BOT_TOKEN there" >&2; exit 1; }
[[ -n "$(token .env.local)" ]] || { echo ".env.local has no BOT_TOKEN" >&2; exit 1; }
bot=$(curl -s "https://api.telegram.org/bot$(token .env.local)/getMe" | grep -oE '"username":"[^"]+"' | cut -d'"' -f4)
[[ -n "$bot" ]] || { echo "Telegram doesn't accept the BOT_TOKEN in .env.local" >&2; exit 1; }
if [[ "$bot" == "rimy_ai_bot" ]]; then
  echo "STOP: .env.local has the production bot's token (@$bot). Use the test bot's token from BotFather." >&2
  exit 1
fi
echo "Test bot: @$bot"
command -v cloudflared >/dev/null || { echo "install the tunnel first: brew install cloudflared" >&2; exit 1; }

mkdir -p data-local
log=$(mktemp)
cloudflared tunnel --no-autoupdate --url http://localhost:8080 >"$log" 2>&1 &
tunnel=$!
trap 'kill $tunnel 2>/dev/null; docker rm -f rimy-local >/dev/null 2>&1; rm -f "$log"' EXIT

url=""
for _ in $(seq 1 30); do
  url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$log" | head -1 || true)
  [[ -n "$url" ]] && break
  sleep 1
done
[[ -n "$url" ]] || { echo "the tunnel didn't start:"; cat "$log"; exit 1; }
echo "Mini App: $url"

# The image only carries the dependencies (Python packages, the font): it's rebuilt when it's missing or
# with --build (after requirements.txt / Dockerfile changes). The code is mounted fresh on every run,
# and the Mini App is built here, so a code change needs only a restart.
if [[ "${1:-}" == "--build" ]] || ! docker image inspect rimy-local >/dev/null 2>&1; then
  docker build -q -t rimy-local . >/dev/null
fi
(cd webapp && npm run build >/dev/null)
docker rm -f rimy-local >/dev/null 2>&1 || true
docker run --rm --name rimy-local \
  --env-file .env --env-file .env.local \
  -e WEBAPP_URL="$url" \
  -e DATABASE_URL="sqlite+aiosqlite:////app/data/local.db" \
  -v "$PWD/data-local:/app/data" \
  -v "$PWD/bot:/app/bot:ro" \
  -v "$PWD/migrations:/app/migrations:ro" \
  -v "$PWD/webapp/dist:/app/webapp/dist:ro" \
  -p 8080:8080 \
  rimy-local
