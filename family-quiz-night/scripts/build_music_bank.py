#!/usr/bin/env python3
# ABOUTME: Builds music bank from Deezer search API: 30s preview MP3s + metadata.
# ABOUTME: Idempotent, polite (1.5s default between calls). Mirrors build_picture_bank.

"""
Usage:
    python3 build_music_bank.py                     # full run from songs.txt
    python3 build_music_bank.py --limit 5           # smoke-test on first 5
    python3 build_music_bank.py --songs FILE        # custom song list

songs.txt format: one entry per line, "Title — Artist | category"
    Bohemian Rhapsody — Queen | rock-classic
    Thriller — Michael Jackson | pop-80s

Lines starting with # or blank are ignored. Em-dash, en-dash, or " - " all OK as separator.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "FamilyQuizNight/1.0 (https://github.com/drdgraham72; drdgraham72@gmail.com)"
SEARCH_URL = "https://api.deezer.com/search"
ALBUM_URL = "https://api.deezer.com/album/{}"

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "frontend" / "audio" / "music-bank"
JSON_PATH = ROOT / "frontend" / "data" / "music-bank.json"
DEFAULT_SONGS = Path(__file__).resolve().parent / "songs.txt"


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def parse_songs(path: Path) -> list[tuple[str, str, str]]:
    """Returns list of (title, artist, category)."""
    out: list[tuple[str, str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            song_part, category = [p.strip() for p in line.rsplit("|", 1)]
        else:
            song_part, category = line, "general"
        # Accept em-dash, en-dash, or hyphen-with-spaces
        sep = None
        for s in (" — ", " – ", " - "):
            if s in song_part:
                sep = s
                break
        if not sep:
            print(f"WARN: skipping malformed line: {line}", file=sys.stderr)
            continue
        title, artist = song_part.split(sep, 1)
        out.append((title.strip(), artist.strip(), category))
    return out


def http_get_json(url: str, retries: int = 2) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = 5 * (2 ** attempt)
                print(f"  429 — backing off {wait}s …", file=sys.stderr)
                time.sleep(wait)
                continue
            raise


def http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def search_track(title: str, artist: str) -> dict | None:
    """Returns the best matching track dict, or None."""
    q = f'track:"{title}" artist:"{artist}"'
    url = f"{SEARCH_URL}?{urllib.parse.urlencode({'q': q, 'limit': 5})}"
    doc = http_get_json(url)
    for track in doc.get("data", []):
        if track.get("readable") and track.get("preview"):
            return track
    # Fallback: relaxed search
    q2 = f"{title} {artist}"
    url2 = f"{SEARCH_URL}?{urllib.parse.urlencode({'q': q2, 'limit': 5})}"
    doc2 = http_get_json(url2)
    for track in doc2.get("data", []):
        if track.get("readable") and track.get("preview"):
            # Sanity-check artist name overlap
            if artist.lower().split()[0] in track.get("artist", {}).get("name", "").lower():
                return track
    return None


def fetch_album_genre(album_id: int) -> str | None:
    try:
        doc = http_get_json(ALBUM_URL.format(album_id))
        genres = [g["name"] for g in doc.get("genres", {}).get("data", [])]
        return genres[0] if genres else None
    except (urllib.error.HTTPError, urllib.error.URLError):
        return None


def make_hint(track: dict, genre: str | None) -> str:
    """One-sentence clue. Genre + album when both useful; just genre otherwise."""
    album_title = (track.get("album") or {}).get("title", "")
    album_clean = re.sub(r"\s*\([^)]*\)", "", album_title).strip()
    title_lc = (track.get("title_short") or track.get("title", "")).lower()
    artist_lc = ((track.get("artist") or {}).get("name", "")).lower()
    # Skip album hint if it overlaps with title, matches the artist (self-titled),
    # or is a generic-numeric compilation name like "1" or "20".
    has_album = bool(
        album_clean
        and title_lc not in album_clean.lower()
        and artist_lc not in album_clean.lower()
        and not album_clean.isdigit()
    )
    if genre and has_album:
        return f"{genre} track from the album '{album_clean}'"
    if genre:
        return f"{genre} track"
    if has_album:
        return f"From the album '{album_clean}'"
    return ""


def alternatives_for(title: str, artist: str) -> list[str]:
    return list(dict.fromkeys([title, artist, f"{title} — {artist}"]))


def process_one(title: str, artist: str, category: str, slug: str) -> dict:
    track = search_track(title, artist)
    if not track:
        raise RuntimeError("no match")
    preview = track.get("preview")
    if not preview:
        raise RuntimeError("no preview URL")

    audio_path = AUDIO_DIR / f"{slug}.mp3"
    if not audio_path.exists():
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        audio_bytes = http_get_bytes(preview)
        # MP3 starts with ID3 tag or MPEG sync (0xFFFB / 0xFFFA / 0xFFF3)
        if not (audio_bytes.startswith(b"ID3") or audio_bytes[:2] in (b"\xff\xfb", b"\xff\xfa", b"\xff\xf3")):
            raise RuntimeError(f"unexpected audio bytes ({len(audio_bytes)}b)")
        audio_path.write_bytes(audio_bytes)

    actual_title = track.get("title_short") or track.get("title") or title
    actual_artist = (track.get("artist") or {}).get("name", artist)
    album_id = (track.get("album") or {}).get("id")
    genre = fetch_album_genre(album_id) if album_id else None

    return {
        "id": slug,
        "filename": f"{slug}.mp3",
        "title": actual_title,
        "artist": actual_artist,
        "album": (track.get("album") or {}).get("title", ""),
        "duration": track.get("duration", 0),
        "genre": genre or "",
        "hint": make_hint(track, genre),
        "alternatives": alternatives_for(actual_title, actual_artist),
        "category": category,
    }


def load_existing() -> dict:
    if JSON_PATH.exists():
        try:
            return json.loads(JSON_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"WARN: {JSON_PATH} unreadable, starting fresh", file=sys.stderr)
    return {"version": 1, "generated": "", "items": []}


def save_bank(bank: dict) -> None:
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    bank["generated"] = datetime.date.today().isoformat()
    JSON_PATH.write_text(json.dumps(bank, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--songs", type=Path, default=DEFAULT_SONGS)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--delay", type=float, default=1.5)
    args = p.parse_args()

    if not args.songs.exists():
        print(f"FATAL: {args.songs} not found", file=sys.stderr)
        return 1

    songs = parse_songs(args.songs)
    if args.limit:
        songs = songs[: args.limit]

    bank = load_existing()
    existing_ids = {item["id"] for item in bank.get("items", [])}

    added = 0
    skipped = 0
    failed = 0

    for i, (title, artist, category) in enumerate(songs, 1):
        slug = slugify(f"{artist}-{title}")
        prefix = f"[{i:>3}/{len(songs)}] {(title[:32]):<32s} — {(artist[:24]):<24s} ({category})"
        if slug in existing_ids:
            print(f"{prefix} ... cached")
            skipped += 1
            continue
        try:
            entry = process_one(title, artist, category, slug)
            bank.setdefault("items", []).append(entry)
            existing_ids.add(slug)
            save_bank(bank)
            added += 1
            print(f"{prefix} ... ok")
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as e:
            print(f"{prefix} ... FAIL: {e}", file=sys.stderr)
            failed += 1
        time.sleep(args.delay)

    print()
    print(f"Done. added={added}  cached={skipped}  failed={failed}  total={len(bank['items'])}")
    print(f"Bank: {JSON_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
