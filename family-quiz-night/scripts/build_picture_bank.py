#!/usr/bin/env python3
# ABOUTME: Scrapes Wikipedia article thumbnails + intros into a picture-bank.json the frontend reads.
# ABOUTME: Idempotent (skips subjects already present) and polite (1s between API calls).

"""
Usage:
    python3 build_picture_bank.py                    # full scrape from subjects.txt
    python3 build_picture_bank.py --limit 5          # only first 5 subjects
    python3 build_picture_bank.py --subjects FILE    # custom subjects list

Subjects file format: one entry per line, "Wikipedia Title | category"
    Albert Einstein | scientist
    Eiffel Tower | landmark

Lines starting with # or blank are ignored.
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
API = "https://en.wikipedia.org/w/api.php"
THUMB_SIZE = 320

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "frontend" / "images" / "picture-bank"
JSON_PATH = ROOT / "frontend" / "data" / "picture-bank.json"
DEFAULT_SUBJECTS = Path(__file__).resolve().parent / "subjects.txt"


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def parse_subjects(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|", 1)]
        title = parts[0]
        category = parts[1] if len(parts) > 1 else "misc"
        out.append((title, category))
    return out


def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_subject(title: str) -> dict | None:
    """Returns {title, thumb_url, extract} or None if the page has no usable image."""
    params = {
        "action": "query",
        "format": "json",
        "titles": title,
        "redirects": "1",
        "prop": "pageimages|extracts",
        "pithumbsize": str(THUMB_SIZE),
        "exintro": "1",
        "explaintext": "1",
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    data = http_get_json(url)
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    if page.get("missing") is not None:
        return None
    thumb = page.get("thumbnail", {}).get("source")
    if not thumb:
        return None
    return {
        "title": page.get("title", title),
        "thumb_url": thumb,
        "extract": page.get("extract", ""),
    }


SENTENCE_RE = re.compile(r"^(.{30,260}?[.!?])(\s|$)", re.DOTALL)


def strip_parentheticals(text: str) -> str:
    """Remove non-nested parens and brackets repeatedly (IPA, dates, etc.)."""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\([^()]*\)", "", text)
        text = re.sub(r"\[[^\[\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,;:.!?])", r"\1", text)
    return text.strip(" ;,")


def first_sentence(text: str) -> str:
    text = text.replace("\n", " ").strip()
    if not text:
        return ""
    m = SENTENCE_RE.match(text)
    return (m.group(1) if m else text[:240]).strip()


_REDACT = "[?]"


def anonymize(text: str, answer: str) -> str:
    """Replace the answer + obvious name-fragments with a generic placeholder."""
    bare = re.sub(r"\s*\([^)]*\)\s*$", "", answer).strip()
    targets = {answer, bare}
    parts = bare.split()
    if 2 <= len(parts) <= 4:
        targets.add(parts[-1])  # surname
        targets.add(parts[0])   # given name
    for t in sorted(targets, key=len, reverse=True):
        if not t:
            continue
        text = re.sub(rf"\b{re.escape(t)}\b", _REDACT, text)
    text = re.sub(rf"({re.escape(_REDACT)}\s*){{2,}}", _REDACT + " ", text)
    return text.strip()


def make_hint(extract: str, answer: str) -> str:
    cleaned = strip_parentheticals(extract)
    sentence = first_sentence(cleaned)
    return anonymize(sentence, answer)


def alternatives_for(answer: str) -> list[str]:
    """Generate plausible accepted variants of an answer."""
    alts = {answer}
    # Strip parenthetical disambiguation: "Mercury (planet)" -> "Mercury"
    bare = re.sub(r"\s*\(.+?\)\s*$", "", answer).strip()
    if bare and bare != answer:
        alts.add(bare)
    # Surname-only for two-or-more-word names (people)
    parts = bare.split()
    if 2 <= len(parts) <= 4 and not any(p.endswith(".") for p in parts):
        alts.add(parts[-1])
    return sorted(alts, key=len, reverse=True)


def load_existing_bank() -> dict:
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


def process_one(title: str, category: str, existing_ids: set[str]) -> dict | None:
    slug = slugify(title)
    if slug in existing_ids:
        return None  # Caller treats None as "already done"

    info = fetch_subject(title)
    if not info:
        raise RuntimeError("no thumbnail or page missing")

    img_path = IMG_DIR / f"{slug}.jpg"
    img_bytes = http_get_bytes(info["thumb_url"])
    if not img_bytes.startswith(b"\xff\xd8") and not img_bytes.startswith(b"\x89PNG"):
        raise RuntimeError(f"unexpected image bytes (got {len(img_bytes)}b)")
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    img_path.write_bytes(img_bytes)

    full_title = info["title"]
    answer = re.sub(r"\s*\([^)]*\)\s*$", "", full_title).strip()
    return {
        "id": slug,
        "filename": f"{slug}.jpg",
        "answer": answer,
        "alternatives": alternatives_for(answer),
        "hint": make_hint(info["extract"], full_title),
        "category": category,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--subjects", type=Path, default=DEFAULT_SUBJECTS)
    p.add_argument("--limit", type=int, default=0, help="0 = no limit")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between subjects")
    args = p.parse_args()

    if not args.subjects.exists():
        print(f"FATAL: subjects file not found: {args.subjects}", file=sys.stderr)
        return 1

    subjects = parse_subjects(args.subjects)
    if args.limit:
        subjects = subjects[: args.limit]

    bank = load_existing_bank()
    existing_ids = {item["id"] for item in bank.get("items", [])}

    added = 0
    skipped = 0
    failed = 0

    for i, (title, category) in enumerate(subjects, 1):
        slug = slugify(title)
        prefix = f"[{i:>3}/{len(subjects)}] {title:<40s} ({category})"
        if slug in existing_ids:
            print(f"{prefix} ... cached")
            skipped += 1
            continue
        try:
            entry = process_one(title, category, existing_ids)
            if entry is None:
                skipped += 1
                continue
            bank.setdefault("items", []).append(entry)
            existing_ids.add(entry["id"])
            save_bank(bank)  # write after every success — resumable
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
