# --- 1. Build the Telegram Mini App (static files) ---
FROM node:22-alpine AS webapp
WORKDIR /webapp
COPY webapp/package.json webapp/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY webapp ./
RUN npm run build

# --- 2. The bot + API (serves the built Mini App too) ---
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY bot ./bot
COPY --from=webapp /webapp/dist ./webapp/dist

# Run as an unprivileged user; /app/data is where the SQLite file lives (mounted as a volume).
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data && chown app:app /app/data
USER app

EXPOSE 8080
CMD ["python", "-m", "bot"]
