# Family Quiz Night

A self-sustaining quiz app with automated question generation, ad-supported free tier, and premium upgrade path.

## Structure

```
frontend/     → Single-page quiz app (HTML/CSS/JS, 53 rounds, 530+ questions)
backend/      → FastAPI + PostgreSQL API server (auth, rounds, anti-scrape answer reveal, ratings, reports)
pipeline/     → Three-stage question generation (trawl → generate → AI curate)
```

## Quick Start

```bash
# Start Postgres + API
cd backend
cp .env.example .env  # edit with your keys
docker-compose up -d

# Serve the frontend (picture rounds need same-origin images)
./serve.sh           # http://localhost:8081/
```

## Pipeline

```bash
cd pipeline
pip install aiohttp

# Full run (all topics)
python pipeline.py --topic all --omdb-key YOUR_KEY --anthropic-key YOUR_KEY

# Single topic, dry run (no AI gate)
python pipeline.py --topic movies --omdb-key YOUR_KEY
```

## Nightly Cron

```bash
# Add to crontab — runs at 3am daily
0 3 * * * cd /app/backend && python scripts/nightly_pipeline.py >> /var/log/quiz-pipeline.log 2>&1
```

## Architecture

**Stage 1 — Trawler**: Scrapes OMDB, Wikipedia, etc. into normalised `Factoid` objects.

**Stage 2 — Generator**: Deterministic templates produce `QuestionCandidate` objects. Zero AI, zero network. Over-generates by design.

**Stage 3 — Quality Gate**: Claude API evaluates candidates in batches of 25. Approves, rewrites, or rejects. The **only** AI token spend.

**Backend**: FastAPI serving rounds and individual answers (anti-scrape: one answer per request, rate-limited). JWT auth with anonymous device tokens and email upgrade path.

**Frontend**: Topic launcher → round picker (sortable: all/unseen/top-rated) → tap-to-reveal quiz cards → 5-star rating → ad interstitial. Picture rounds: emoji, silhouette SVGs, CSS blur reveal, and client-side ASCII art portraits.
