#!/usr/bin/env python3
# ABOUTME: Pulls trivia rounds from OpenTrivia DB and writes them as round JSON files.
# ABOUTME: Idempotent across same-day runs (round IDs include today's date).

"""
Usage:
    python3 build_rounds.py                              # one round per topic × difficulty
    python3 build_rounds.py --topic movies               # only movies
    python3 build_rounds.py --diff medium                # only medium
    python3 build_rounds.py --rounds 3                   # 3 rounds per topic+difficulty combo
    python3 build_rounds.py --topic music --rounds 5     # 15 music rounds (5 × 3 difficulties)

Output:
    frontend/data/rounds/{topic}-online-{date}-{diff}-{n}.json   (one per round)
    frontend/data/rounds-index.json                              (updated to include new rounds)
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "FamilyQuizNight/1.0 (https://github.com/drdgraham72; drdgraham72@gmail.com)"
API_URL = "https://opentdb.com/api.php"

ROOT = Path(__file__).resolve().parent.parent
ROUNDS_DIR = ROOT / "frontend" / "data" / "rounds"
INDEX_PATH = ROOT / "frontend" / "data" / "rounds-index.json"

# Map app topics → OpenTDB category IDs (https://opentdb.com/api_category.php)
TOPIC_CATS: dict[str, int] = {
    "movies":    11,   # Entertainment: Film
    "music":     12,   # Entertainment: Music
    "science":   17,   # Science & Nature
    "history":   23,   # History
    "geography": 22,   # Geography
    "sport":     21,   # Sports
    "nature":    27,   # Animals
    "food":       9,   # General Knowledge (no direct food category; closest fit)
}

DIFFICULTIES = ["easy", "medium", "hard"]

# Drop questions that need their multiple-choice context to make sense.
BAD_PATTERNS = [
    re.compile(r"\bof the following\b", re.I),
    re.compile(r"\bof these\b", re.I),
    re.compile(r"\bwhich of these\b", re.I),
    re.compile(r"\blisted below\b", re.I),
    re.compile(r"\bnone of these\b", re.I),
    re.compile(r"\bany of these\b", re.I),
    re.compile(r"\bnot one of\b", re.I),
]


def http_get_json(url: str, retries: int = 3) -> dict:
    """GET + JSON-decode. Retries on 429 with exponential backoff (10s, 20s, 40s)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = 10 * (2 ** attempt)
                print(f"  429 — backing off {wait}s …", file=sys.stderr)
                time.sleep(wait)
                continue
            raise


def decode_text(s: str) -> str:
    """Decode HTML entities + normalise whitespace."""
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def fetch_questions(category_id: int, difficulty: str, count: int = 10) -> list[dict]:
    params = {
        "amount": str(count),
        "category": str(category_id),
        "difficulty": difficulty,
        "type": "multiple",
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    doc = http_get_json(url)
    code = doc.get("response_code")
    if code != 0:
        raise RuntimeError(f"OpenTDB response_code={code}")
    return doc.get("results", [])


def usable(question_text: str) -> bool:
    return not any(p.search(question_text) for p in BAD_PATTERNS)


def make_round(topic: str, category_id: int, difficulty: str, n: int, today: str) -> dict | None:
    raw = fetch_questions(category_id, difficulty, count=10)
    qs: list[dict] = []
    for r in raw:
        q = decode_text(r["question"])
        a = decode_text(r["correct_answer"])
        if not usable(q):
            continue
        qs.append({"q": q, "a": a})
    if not qs:
        return None
    rid = f"{topic}-online-{today}-{difficulty}-{n}"
    return {
        "id": rid,
        "topic": topic,
        "title": f"🌐 Online: {topic.title()} {difficulty.title()} #{n}",
        "desc": f"Trivia from OpenTrivia DB — {len(qs)} {difficulty} questions",
        "type": "standard",
        "isNew": True,
        "questions": qs,
    }


def load_index() -> dict:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {"version": 1, "generated": "", "rounds": []}


def save_index(index: dict) -> None:
    index["generated"] = datetime.date.today().isoformat()
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--topic", choices=list(TOPIC_CATS.keys()) + ["all"], default="all")
    p.add_argument("--diff", choices=DIFFICULTIES + ["all"], default="all")
    p.add_argument("--rounds", type=int, default=1, help="Rounds per topic+difficulty combo")
    p.add_argument("--delay", type=float, default=5.5, help="Seconds between API calls (OpenTDB requires ≥5s)")
    args = p.parse_args()

    topics = (
        list(TOPIC_CATS.items())
        if args.topic == "all"
        else [(args.topic, TOPIC_CATS[args.topic])]
    )
    diffs = DIFFICULTIES if args.diff == "all" else [args.diff]

    index = load_index()
    existing_ids = {r["id"] for r in index.get("rounds", [])}
    today = datetime.date.today().isoformat()

    ROUNDS_DIR.mkdir(parents=True, exist_ok=True)

    added = 0
    skipped = 0
    failed = 0

    for topic, cat_id in topics:
        for diff in diffs:
            for n in range(1, args.rounds + 1):
                rid = f"{topic}-online-{today}-{diff}-{n}"
                prefix = f"[{topic:>9} {diff:<6} #{n}]"
                if rid in existing_ids:
                    print(f"{prefix} cached")
                    skipped += 1
                    continue
                try:
                    round_data = make_round(topic, cat_id, diff, n, today)
                    if not round_data:
                        print(f"{prefix} no usable questions")
                        skipped += 1
                        time.sleep(args.delay)
                        continue
                    (ROUNDS_DIR / f"{rid}.json").write_text(
                        json.dumps(round_data, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    index["rounds"].append({
                        "id": rid,
                        "topic": round_data["topic"],
                        "title": round_data["title"],
                        "desc": round_data["desc"],
                        "type": round_data["type"],
                        "isNew": True,
                        "count": len(round_data["questions"]),
                    })
                    existing_ids.add(rid)
                    save_index(index)  # write after every success — resumable
                    added += 1
                    print(f"{prefix} added — {len(round_data['questions'])}Q")
                except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as e:
                    print(f"{prefix} FAIL: {e}", file=sys.stderr)
                    failed += 1
                time.sleep(args.delay)

    save_index(index)
    print()
    print(f"Done. added={added}  cached={skipped}  failed={failed}  total={len(index['rounds'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
