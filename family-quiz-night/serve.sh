#!/usr/bin/env bash
# ABOUTME: Launches a local dev server for the Family Quiz Night frontend.
# ABOUTME: Picture rounds (blur, ASCII) need same-origin image fetches — file:// won't work.

PORT="${1:-8081}"
DIR="$(cd "$(dirname "$0")/frontend" && pwd)"

echo "Serving Family Quiz Night at http://localhost:${PORT}/"
echo "Press Ctrl+C to stop"
python3 -m http.server "$PORT" --directory "$DIR"
