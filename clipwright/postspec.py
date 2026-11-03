"""post.json: the per-clip contract between production (Claude Code) and the publisher.

    {"brand": "ojastra_mind", "file": "out/ojastra_mind/<job>/01_clip_....mp4",
     "duration": 53.5, "source_url": "https://www.youtube.com/watch?v=...",
     "credit": "Credit: TEDx Talks (https://www.youtube.com/watch?v=...)",
     "platforms": {
       "youtube":   {"title": "...", "description": "...", "tags": ["...", "..."]},
       "tiktok":    {"caption": "..."},
       "facebook":  {"caption": "..."},
       "instagram": {"caption": "..."}}}

Limits are the platforms' published ones. The credit line must appear in every platform's text,
so no upload goes out without crediting the source.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from .brands import PLATFORMS

YT_TITLE_MAX = 100
YT_DESCRIPTION_MAX = 5000
YT_TAGS_MAX = 500          # characters across all tags, as YouTube counts them
CAPTION_MAX = {"tiktok": 2200, "facebook": 63206, "instagram": 2200}
IG_HASHTAGS_MAX = 30
MAX_SECONDS = {"youtube": 180, "tiktok": 600, "facebook": 90, "instagram": 900}


class PostError(ValueError):
    """post.json is invalid. The message lists every problem."""


def load(path: Path) -> Dict[str, Any]:
    try:
        post = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise PostError(f"{path}: invalid JSON: {exc}") from None
    validate(post, str(path))
    return post


def _tags_length(tags: List[str]) -> int:
    # YouTube counts a tag with a space as if it were quoted, plus a comma between tags
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)


def platform_text(post: Dict[str, Any], platform: str) -> str:
    copy = post["platforms"][platform]
    return copy["description"] if platform == "youtube" else copy["caption"]


def validate(post: Dict[str, Any], where: str = "post.json") -> None:
    errors = []
    for field in ("brand", "file", "credit", "source_url"):
        if not str(post.get(field, "")).strip():
            errors.append(f"{field} is required")
    duration = post.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        errors.append("duration must be the clip length in seconds")
        duration = 0
    platforms = post.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        errors.append(f"platforms must hold copy for at least one of {', '.join(PLATFORMS)}")
        platforms = {}
    credit = str(post.get("credit", "")).strip()
    for name, copy in platforms.items():
        if name not in PLATFORMS:
            errors.append(f"platforms.{name}: unknown platform")
            continue
        if not isinstance(copy, dict):
            errors.append(f"platforms.{name} must be an object")
            continue
        if duration > MAX_SECONDS[name]:
            errors.append(f"platforms.{name}: clip is {duration:g}s, over the {MAX_SECONDS[name]}s limit")
        if name == "youtube":
            title = str(copy.get("title", ""))
            if not title.strip():
                errors.append("platforms.youtube.title is required")
            if len(title) > YT_TITLE_MAX:
                errors.append(f"platforms.youtube.title is {len(title)} chars (max {YT_TITLE_MAX})")
            if "<" in title or ">" in title:
                errors.append("platforms.youtube.title: YouTube rejects < and >")
            text = str(copy.get("description", ""))
            if len(text) > YT_DESCRIPTION_MAX:
                errors.append(f"platforms.youtube.description is over {YT_DESCRIPTION_MAX} chars")
            tags = copy.get("tags", [])
            if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                errors.append("platforms.youtube.tags must be a list of strings")
            elif _tags_length(tags) > YT_TAGS_MAX:
                errors.append(f"platforms.youtube.tags are {_tags_length(tags)} chars (max {YT_TAGS_MAX})")
        else:
            text = str(copy.get("caption", ""))
            if not text.strip():
                errors.append(f"platforms.{name}.caption is required")
            if len(text) > CAPTION_MAX[name]:
                errors.append(f"platforms.{name}.caption is {len(text)} chars (max {CAPTION_MAX[name]})")
            if name == "instagram" and text.count("#") > IG_HASHTAGS_MAX:
                errors.append(f"platforms.instagram.caption has over {IG_HASHTAGS_MAX} hashtags")
        if credit and credit not in text:
            errors.append(f"platforms.{name}: the credit line {credit!r} must appear in the text")
    if errors:
        raise PostError(f"{where}:\n  " + "\n  ".join(errors))
