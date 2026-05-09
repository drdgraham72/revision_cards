#!/usr/bin/env python3
# ABOUTME: Downloads one banner image per topic via the Wikipedia pageimages API.
# ABOUTME: Idempotent (skips topics whose image already exists).

"""
Usage: python3 build_topic_images.py

Edit SUBJECTS to remap a topic to a different Wikipedia article.
Output: frontend/images/topics/{topic_id}.jpg
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "FamilyQuizNight/1.0 (https://github.com/drdgraham72; drdgraham72@gmail.com)"
API = "https://en.wikipedia.org/w/api.php"
THUMB_SIZE = 480

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "frontend" / "images" / "topics"

# topic_id → Wikipedia article title used to source the thumbnail.
SUBJECTS: dict[str, str] = {
    "food":      "Sunday roast",
    "science":   "Microscope",
    "history":   "Colosseum",
    "geography": "Earth",
    "movies":    "Movie theater",
    "music":     "Phonograph record",
    "sport":     "Association football",
    "nature":    "Forest",
    "tv":        "Television set",
    "starwars":  "Star Wars",
    "mcu":       "Marvel Cinematic Universe",
    "picture":   "Photography",
}


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def fetch_thumb_url(title: str) -> str | None:
    params = {
        "action": "query",
        "format": "json",
        "titles": title,
        "redirects": "1",
        "prop": "pageimages",
        "pithumbsize": str(THUMB_SIZE),
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    data = json.loads(http_get(url).decode("utf-8"))
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    return (page.get("thumbnail") or {}).get("source")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = miss = fail = 0

    for topic_id, title in SUBJECTS.items():
        out = OUT_DIR / f"{topic_id}.jpg"
        if out.exists():
            print(f"  cached: {topic_id}")
            ok += 1
            continue
        try:
            thumb = fetch_thumb_url(title)
            if not thumb:
                print(f"  MISS:  {topic_id:<10} ({title}) — no thumbnail", file=sys.stderr)
                miss += 1
                time.sleep(1.0)
                continue
            data = http_get(thumb)
            if not (data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG")):
                raise RuntimeError(f"not a JPG/PNG ({len(data)}b)")
            out.write_bytes(data)
            print(f"  ok:    {topic_id:<10} ({title})")
            ok += 1
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as e:
            print(f"  FAIL:  {topic_id:<10} ({title}): {e}", file=sys.stderr)
            fail += 1
        time.sleep(1.0)

    print()
    print(f"Done. ok={ok}  miss={miss}  fail={fail}  out={OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
