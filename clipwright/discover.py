"""Find source videos for an idea with yt-dlp's YouTube search, and rank them.

Ranking is a first pass for Claude Code, which still reads the candidates and their captions
before choosing. It prefers long-form talks and interviews with real reach, and pushes down
the low-view narration channels and motivational reupload farms that make poor or risky sources.
"""

import json
import math
import re
import subprocess
from typing import Any, Dict, List, Optional, Sequence

MIN_SECONDS = 120          # shorter than this rarely holds a full 30-70 s idea plus context
MAX_SECONDS = 3 * 3600
REUPLOAD_RE = re.compile(r"motivation|compilation|mindset|hub\b|best speech|wisdom|clips?\s*hd", re.I)


def search(query: str, n: int = 10, runner=subprocess.run, cookies: Optional[str] = None) -> List[Dict[str, Any]]:
    """Up to ``n`` YouTube results for ``query`` (flat search: no download, one request)."""
    fmt = "%(.{id,title,channel,view_count,duration,upload_date})j"
    extra = ["--cookies", cookies] if cookies else []
    proc = runner(["yt-dlp", "--flat-playlist", "--no-warnings", *extra, "--print", fmt, f"ytsearch{n}:{query}"],
                  capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp search failed: {proc.stderr.strip()[-300:]}")
    out = []
    for line in proc.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("id"):
            out.append(item)
    return out


def score(item: Dict[str, Any]) -> float:
    """Higher is a better source. Zero means skip."""
    duration = item.get("duration") or 0
    views = item.get("view_count") or 0
    if not MIN_SECONDS <= duration <= MAX_SECONDS:
        return 0.0
    text = f"{item.get('title', '')} {item.get('channel', '')}"
    value = math.log10(views + 1)            # 1k views -> 3, 1M -> 6
    if views < 10_000:
        value *= 0.5                          # mostly faceless narration with no track record
    if REUPLOAD_RE.search(text):
        value *= 0.3                          # reuploads: someone else's footage, often claimed music
    return round(value, 2)


def rank(results: Sequence[Dict[str, Any]], top: int = 8) -> List[Dict[str, Any]]:
    """Unique ids, scored and sorted best first, zero scores dropped."""
    seen, ranked = set(), []
    for item in results:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        s = score(item)
        if s > 0:
            ranked.append(dict(item, score=s, url=f"https://www.youtube.com/watch?v={item['id']}"))
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked[:top]


def discover(queries: Sequence[str], n: int = 10, top: int = 8, runner=subprocess.run,
             cookies: Optional[str] = None) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for q in queries:
        results.extend(search(q, n, runner, cookies))
    return rank(results, top)
