"""Per-brand settings for the autopilot: which platform accounts a brand posts to, its daily
posting slots, and its queue of video ideas. Stdlib only, so it runs on the host in tests.

brands/<brand>/accounts.json
    {"timezone": "Asia/Kathmandu", "slots": ["09:00", "13:00", "19:30"],
     "stagger_minutes": 20, "hashtags": ["#shorts"],
     "platforms": {"youtube": {"category_id": "27"}, "tiktok": {},
                   "facebook": {"page_id": "123"}, "instagram": {"ig_user_id": "456"}}}

brands/<brand>/ideas.md
    - [ ] Why walking without your phone clears your head      (waiting)
    - [x] How silence calms a stressed brain  <!-- done: 1Fy6dACPtVs -->
    - [!] Some idea  <!-- failed: no source with a real expert -->
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PLATFORMS = ("youtube", "tiktok", "facebook", "instagram")
# fields each platform needs before it can post; tokens live in secrets/, not here
REQUIRED = {"youtube": (), "tiktok": (), "facebook": ("page_id",), "instagram": ("ig_user_id",)}
SLOT_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
IDEA_RE = re.compile(r"^- \[( |x|!)\] (.+?)(?:\s+<!--\s*(.*?)\s*-->)?\s*$")


class BrandError(ValueError):
    """accounts.json or ideas.md is invalid. The message names the file and field."""


def load_accounts(path: Path) -> Dict[str, Any]:
    """Read and validate accounts.json. Platforms left out are simply not posted to."""
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise BrandError(f"{path}: not found (copy brands/example/accounts.json)") from None
    except json.JSONDecodeError as exc:
        raise BrandError(f"{path}: invalid JSON: {exc}") from None
    errors = []
    try:
        ZoneInfo(str(data.get("timezone", "")))
    except (ZoneInfoNotFoundError, ValueError):
        errors.append(f"timezone {data.get('timezone')!r} is not an IANA name like Asia/Kathmandu")
    slots = data.get("slots")
    if not isinstance(slots, list) or not slots or not all(isinstance(s, str) and SLOT_RE.match(s) for s in slots):
        errors.append("slots must be a non-empty list of HH:MM times")
    stagger = data.get("stagger_minutes", 20)
    if not isinstance(stagger, int) or not 0 <= stagger <= 120:
        errors.append("stagger_minutes must be a whole number from 0 to 120")
    platforms = data.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        errors.append(f"platforms must name at least one of {', '.join(PLATFORMS)}")
        platforms = {}
    for name, cfg in platforms.items():
        if name not in PLATFORMS:
            errors.append(f"platforms.{name}: unknown platform (use {', '.join(PLATFORMS)})")
            continue
        if not isinstance(cfg, dict):
            errors.append(f"platforms.{name} must be an object")
            continue
        for field in REQUIRED[name]:
            if not str(cfg.get(field, "")).strip():
                errors.append(f"platforms.{name}.{field} is required")
    if errors:
        raise BrandError(f"{path}:\n  " + "\n  ".join(errors))
    data.setdefault("stagger_minutes", 20)
    data.setdefault("hashtags", [])
    data["slots"] = sorted(slots)
    return data


def read_ideas(path: Path) -> List[Tuple[str, str, Optional[str]]]:
    """``(state, idea, note)`` for each idea line; state is ' ' waiting, 'x' done, '!' failed."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        m = IDEA_RE.match(line.strip())
        if m:
            out.append((m.group(1), m.group(2).strip(), m.group(3)))
    return out


def next_idea(path: Path) -> Optional[str]:
    return next((idea for state, idea, _ in read_ideas(path) if state == " "), None)


def mark_idea(path: Path, idea: str, done: bool, note: str) -> None:
    """Tick (``done``) or flag (failed) the first waiting line for ``idea``, keeping every other line."""
    note = note.replace("-->", "").replace("\n", " ").strip()
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        m = IDEA_RE.match(line.strip())
        if m and m.group(1) == " " and m.group(2).strip() == idea:
            mark = "x" if done else "!"
            lines[i] = f"- [{mark}] {idea}  <!-- {'done' if done else 'failed'}: {note} -->"
            path.write_text("\n".join(lines) + "\n")
            return
    raise BrandError(f"{path}: no waiting idea {idea!r}")


def list_brands(work: Path) -> List[str]:
    """Brands with an accounts.json, skipping the committed example."""
    root = work / "brands"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and p.name != "example" and (p / "accounts.json").is_file())
