# 🦥 Rimy

**Rimy** is a Telegram bot and Mini App for learning foreign words. Say a word in a voice message (or type it),
and the AI builds a flashcard for you: dictionary form, translation, meaning, example and pronunciation.
Spaced repetition (FSRS, the algorithm modern Anki uses) shows each word right before you would forget it,
and Rimy the sloth reminds you to review, right in Telegram.

- Bot: [@rimy_ai_bot](https://t.me/rimy_ai_bot)
- Built at the Mars IT × Techstars Startup Week Tashkent 2026 hackathon

## Why

Apps like Anki work, but you have to type every card by hand. Courses like Duolingo teach their own phrases,
not the words you meet at work, in a series or in an IELTS book. Rimy keeps the science of spaced repetition
and removes the manual work: one voice message and the card is ready, with no app to install and no sign-up.

**For whom:** students preparing for IELTS / CEFR, people learning Korean, Turkish, German or English for work
and relocation, and language schools (B2B).

## Features

- **Voice-first word capture.** Send a voice message or text; speech recognition (Whisper) plus an LLM turn it
  into a card. The AI fixes spelling, picks the dictionary form and asks which meaning you want when there are several.
- **FSRS review** in both directions (target → base and base → target), grades Again / Hard / Good / Easy.
- **Answer cards by text or voice.** The AI checks the answer, accepts synonyms and small typos, suggests a grade
  and, for spoken answers, points out what to work on.
- **Pronunciation** with neural voices, cached per phrase.
- **Rimy the mascot**: a friendly tutor who answers questions ("how do I say 'I'm late'?"), runs conversation
  practice, remembers facts about you and sends review reminders.
- **Languages.** The bot talks in Russian, Uzbek or English (the base language); you can learn English, Korean,
  Turkish, German, Italian, Spanish, French, Portuguese, Japanese, Chinese, Russian or Uzbek. Each language you learn
  has its own deck. Both can be changed any time from the 🌍 menu button, `/base`, `/lang` or the app.
- **Telegram Mini App** (React): add words by text or voice, review cards, word list with pronunciation,
  stats, language settings and Premium.
- **Freemium.** Free plan with daily AI limits (reviewing is always free); **Premium** is a 123 ⭐ Telegram Stars
  monthly subscription (about 30 000 UZS).
- **Analytics.** Funnel events (`start → first_word → first_review → app_open → limit_reached → paywall_view →
  purchase`), referral deep links `t.me/rimy_ai_bot?start=ref_<code>` and an `/admin` report with leads per code.

## How it works

```
Telegram ──► aiogram bot ─┐
                          ├─► AI service (Groq → OpenAI → Gemini fallback chain, Whisper for voice)
Mini App ──► Caddy (HTTPS) ──► FastAPI (/api) ─┤
                          ├─► FSRS scheduler, quotas, Premium, analytics
                          └─► SQLAlchemy ──► SQLite (WAL), Alembic migrations
```

The bot and the Mini App API run in **one Python process** on one event loop and share one database, so a word
added by voice in the chat appears in the app immediately. Mini App requests are authenticated with Telegram's
signed `initData` (HMAC with the bot token): no logins, and nobody can act as another user.

## Tech stack

Python 3.12, aiogram 3, FastAPI + uvicorn, SQLAlchemy 2 (async) + aiosqlite, Alembic, fsrs, Groq / OpenAI / Gemini,
edge-tts, Pillow · React 18 + TypeScript + Vite · Docker, Caddy, GitHub Actions, GHCR.

## Project structure

```
bot/
  __main__.py        entry point: bot + API + scheduler in one event loop
  handlers/          chat: onboarding, adding words, review, practice, premium, admin
  api/               Mini App REST API and Telegram initData auth
  ai/                prompts, providers and the fallback chain
  billing.py         free-plan quotas, Premium (Stars), analytics events
  db/                models, repository, session (SQLite WAL)
  jobs/              reminders and daily backups
  persona/           the mascot's card, memory and context
  audio/tts.py       pronunciation
  menu.py, texts.py  localized menu and texts (ru / uz / en)
webapp/              Telegram Mini App (React + Vite + TS)
migrations/          Alembic migrations (applied automatically at startup)
deploy/              production compose (bot + Caddy), Caddyfile, server setup script
scripts/deploy.sh    deploy with rollback, called by CI over SSH
tests/               pytest suite
```

## Running locally

```bash
cp .env.example .env          # fill in BOT_TOKEN, ADMIN_IDS and at least one AI key
docker compose up --build     # bot + API on http://localhost:8080
```

Without Docker:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
(cd webapp && npm install && npm run build)    # the API serves webapp/dist at /
.venv/bin/python -m bot
```

Mini App development with hot reload: `cd webapp && npm run dev` (Vite on :5173 proxies `/api` to :8080).
Telegram only opens Mini Apps over HTTPS, so to try it inside Telegram expose :8080 with an HTTPS tunnel
and set `WEBAPP_URL` to that address.

## Configuration

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | yes | token from @BotFather |
| `ADMIN_IDS` | yes | comma-separated Telegram ids: `/admin`, `/backup` and the daily backup |
| `GROQ_API_KEY` | at least one AI key | Groq: fast LLMs and Whisper speech recognition |
| `OPENAI_API_KEY` | | OpenAI, used as a fallback |
| `GEMINI_API_KEY` | | Google Gemini, used as a fallback |
| `GROQ_MODELS`, `OPENAI_MODEL`, `GEMINI_MODELS` | no | models; in comma-separated lists the next one is tried if the first fails |
| `WEBAPP_URL` | no | public HTTPS address of the Mini App; empty = no app button |
| `FREE_WORDS_PER_DAY`, `FREE_VOICE_PER_DAY`, `FREE_CHAT_PER_DAY`, `FREE_CHECKS_PER_DAY` | no | free plan limits (20 / 20 / 20 / 50); a voice word counts only as voice |
| `PREMIUM_PRICE_STARS` | no | Premium price in Telegram Stars per 30 days (123) |
| `DATABASE_URL` | no | default `sqlite+aiosqlite:///data/bot.db` |
| `TIMEZONE` | no | default `Asia/Tashkent` |

The AI providers form a chain: **Groq → OpenAI → Gemini**. Only providers with a key take part; if one is down,
rate-limited or returns a broken answer, the next one answers right away.

## Payments

Premium is sold with **Telegram Stars** (currency `XTR`), as Telegram requires for digital goods in bots and
Mini Apps: no payment provider token is needed. The subscription renews every 30 days. Stars go to the bot's
balance and can be withdrawn through Fragment. Every payment is stored with its Telegram charge id, so a duplicate
update never grants Premium twice.

## Deployment

Production runs on a small Ubuntu server (an Oracle Cloud Always Free VM is enough) with Docker:
the bot container plus **Caddy**, which gets and renews a Let's Encrypt certificate by itself.

**One-time server setup**

```bash
git clone https://github.com/Vuek0/rimy.git ~/rimy && cd ~/rimy
bash deploy/server-setup.sh                      # swap, Docker, opens ports 80/443 in iptables
nano .env                                        # same variables as .env.example
echo "DOMAIN=<your-domain>" > deploy/.env        # e.g. 1-2-3-4.sslip.io for an IP without a domain
docker compose -p rimy -f deploy/docker-compose.prod.yml up -d --build
```

Also allow TCP 80 and 443 in the cloud firewall (on Oracle: the subnet's Security List).

**CI/CD (push to `main` → server)**

1. **Test**: runs pytest (pull requests run the tests too).
2. **Build**: builds the image, Mini App included, and pushes it to GHCR (`ghcr.io/vuek0/rimy:<commit>`).
3. **Deploy**: asks the server over SSH to deploy that commit. `scripts/deploy.sh` checks that the commit is on
   `origin/main`, pulls the image, restarts the stack and verifies that the bot is running and the API answers
   over HTTPS. If not, it rolls back to the previous version.

Setup:
- On the server, add a separate deploy key to `~/.ssh/authorized_keys` **restricted to the deploy script**:
  `command="/home/ubuntu/rimy/scripts/deploy.sh",restrict ssh-ed25519 AAAA... rimy-github-deploy`
- On GitHub: Settings → Environments → `production` (deployment branches: `main`) with secrets
  `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` (the deploy key's private part) and `VPS_KNOWN_HOSTS`
  (output of `ssh-keyscan <server ip>`).
- After the first build make the `rimy` package public (Packages → Package settings → Change visibility),
  so the server pulls images without a token.

**Backups**: every day at 03:00 the bot sends the admins a compressed copy of the database (`rimy-YYYY-MM-DD.db.gz`);
`/backup` sends one right away.

## Admin

`/admin [days]` (admins only) shows users, new users, active Premium, Stars earned, the funnel and leads per
referral code. Put `t.me/rimy_ai_bot?start=ref_<name>` in a QR code to count the leads each person brings.

## Tests

```bash
pytest
```

The suite covers the AI parsing and fallback chain, FSRS, the repository, quotas and payments, the Mini App API
(initData auth and isolation between users), the localized menu, onboarding, reminders, backups and concurrent
SQLite writes.

## Security

- Keys live only in `.env` on the server; `.env*` files are git-ignored.
- Mini App API: every request carries Telegram-signed `initData`, checked for signature and age; users can reach
  only their own decks, cards and words.
- The deploy key can run only `scripts/deploy.sh`, which deploys only commits from `main`. Deploy secrets live in
  the `production` environment, available to the `main` branch only; pull requests never see them.
- Containers run as an unprivileged user; workflow permissions are minimal.

## License

[MIT](LICENSE)
