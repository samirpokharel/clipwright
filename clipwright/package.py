"""The upload package of one clip: title, description, hashtags, caption and cover candidates.

Claude Code writes ``title``, ``description``, ``hashtags`` and ``thumbnail_time`` on each segment;
the review UI can edit them (``jobs/<job>/post_edits.json``). This module validates them, adds the
credits and disclaimer that must travel with the post, and writes the files. Stdlib only; the ffmpeg
call is injected so tests never need it.
"""

import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

TITLE_MAX = 100
HASHTAG_MIN, HASHTAG_MAX = 3, 6
COVER_LETTERS = ("a", "b", "c")
DEFAULT_COVER_TIME = 1.5   # the brand title block is on screen here, so the frame works as a cover
EDIT_FIELDS = ("title", "description", "hashtags")


def _hashtag_ok(tag: Any) -> bool:
    if not isinstance(tag, str) or len(tag) < 2 or not tag.startswith("#"):
        return False
    # letters, digits, underscore, and the combining marks Devanagari and accented Latin use
    return all(ch.isalnum() or ch == "_" or unicodedata.category(ch).startswith("M") for ch in tag[1:])


def check_post(segment: Dict[str, Any], number: int) -> List[str]:
    """Problems that stop this clip's package, each starting ``segment N:``."""
    prefix = f"segment {number}:"
    problems: List[str] = []
    title = segment.get("title")
    if not isinstance(title, str) or not title.strip():
        problems.append(f"{prefix} title is missing")
    elif len(title.strip()) > TITLE_MAX:
        problems.append(f"{prefix} title is {len(title.strip())} characters; the limit is {TITLE_MAX}")
    description = segment.get("description")
    if not isinstance(description, str) or not description.strip():
        problems.append(f"{prefix} description is missing")
    tags = segment.get("hashtags")
    if not (isinstance(tags, list) and HASHTAG_MIN <= len(tags) <= HASHTAG_MAX and all(_hashtag_ok(t) for t in tags)):
        problems.append(f"{prefix} hashtags must be a list of {HASHTAG_MIN} to {HASHTAG_MAX} tags, "
                        "each starting with # and containing no spaces")
    if "thumbnail_time" in segment:
        t = segment["thumbnail_time"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t < 0:
            problems.append(f"{prefix} thumbnail_time must be a number of seconds, 0 or more")
    return problems


def merge_edits(segment: Dict[str, Any], edits: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The segment with the UI's edits applied. A ``cover`` choice (a, b or c) is carried through."""
    merged = dict(segment)
    for key in EDIT_FIELDS:
        if edits and key in edits:
            merged[key] = edits[key]
    if edits and edits.get("cover") in COVER_LETTERS:
        merged["cover"] = edits["cover"]
    return merged


def build_post(segment: Dict[str, Any], *, state: Dict[str, Any], pack: Optional[Dict[str, Any]],
               credits: Sequence[str]) -> Dict[str, Any]:
    """Title, description (with credits and disclaimer appended), hashtags and the short caption."""
    title = segment["title"].strip()
    tags = list(segment["hashtags"])
    extras: List[str] = []
    source = state.get("source") or ""
    if state.get("attribution"):
        extras.append(state["attribution"])
    elif source.startswith("http"):
        by = f" by {state['channel']}" if state.get("channel") else ""
        name = f"{state['title']}" if state.get("title") else "the original video"
        extras.append(f"Source: {name}{by}, {source}")
    extras += [f"Sound: {line}" for line in credits]
    if pack and pack["overlays"]["disclaimer"]:
        extras.append(pack["overlays"]["disclaimer"])
    blocks = [segment["description"].strip()]
    if extras:
        blocks.append("\n".join(extras))
    blocks.append(" ".join(tags))
    return {"title": title, "description": "\n\n".join(blocks), "hashtags": tags,
            "caption": f"{title}\n\n{' '.join(tags[:5])}"}


def post_text(post: Dict[str, Any]) -> str:
    return (f"TITLE\n{post['title']}\n\nDESCRIPTION\n{post['description']}\n\n"
            f"CAPTION (TikTok, Reels)\n{post['caption']}\n")


def cover_times(duration: float, chosen: Optional[float]) -> List[float]:
    """Three candidate cover times: the chosen one (default 1.5 s), then 40 % and 75 % through."""
    first = DEFAULT_COVER_TIME if chosen is None else float(chosen)
    first = min(max(first, 0.2), max(0.2, duration - 0.2))
    return [round(first, 2), round(duration * 0.4, 2), round(duration * 0.75, 2)]


def slug(title: str, number: int) -> str:
    """``NN_words_of_the_title``, ASCII only, at most 40 characters; ``NN_clip`` when nothing is left."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z0-9]+", "_", ascii_title.lower()).strip("_")
    return f"{number:02d}_{words[:40 - 3].rstrip('_') or 'clip'}"


def frame_args(video: str, t: float, out: str) -> List[str]:
    return ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-q:v", "2", out]


def write_clip_package(folder: Path, video: Path, post: Dict[str, Any], times: Sequence[float], cover: str,
                       run: Callable[..., Any] = subprocess.run) -> None:
    """video.mp4, cover_a/b/c.jpg, cover.jpg (the chosen one), post.txt and post.json in ``folder``."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, folder / "video.mp4")
    for letter, t in zip(COVER_LETTERS, times):
        run(frame_args(str(video), t, str(folder / f"cover_{letter}.jpg")), check=True, capture_output=True)
    chosen = cover if cover in COVER_LETTERS else "a"
    shutil.copy2(folder / f"cover_{chosen}.jpg", folder / "cover.jpg")
    (folder / "post.txt").write_text(post_text(post), encoding="utf-8")
    (folder / "post.json").write_text(json.dumps(post, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
