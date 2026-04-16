#!/usr/bin/env bash
# ABOUTME: Launches a local dev server for previewing revision cards.
# ABOUTME: Uses Python's built-in HTTP server on port 8080.

PORT="${1:-8080}"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Serving revision cards at http://localhost:${PORT}"
echo "Press Ctrl+C to stop"
python3 -m http.server "$PORT" --directory "$DIR"
