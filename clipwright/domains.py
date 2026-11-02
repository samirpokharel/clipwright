"""Domain packs: the rules, verification fields and search settings of one content domain.

A pack is a JSON file in domains/. The gate (gate.py) enforces its verification fields, the
overlays are burned into the clip, and `clip sources` reads its search settings. Stdlib only.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")

TOP_KEYS = {"name", "description", "clip_seconds", "verification", "overlays", "sources"}
VERIFICATION_KEYS = ("text", "true", "time_inside", "flags")
SOURCE_INT_KEYS = ("min_minutes", "min_views", "per_query")


class DomainError(ValueError):
    """A domain name or pack file is invalid. The message names every problem."""


def list_packs(directory: Path) -> List[str]:
    return sorted(p.stem for p in Path(directory).glob("*.json"))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def _problems(name: str, pack: Any) -> List[str]:
    if not isinstance(pack, dict):
        return ["the pack must be a JSON object"]
    out: List[str] = []
    for key in sorted(set(pack) - TOP_KEYS):
        out.append(f"unknown key {key!r}")
    for key in sorted(TOP_KEYS - set(pack)):
        out.append(f"missing key {key!r}")
    if pack.get("name") != name and "name" in pack:
        out.append(f"name {pack['name']!r} does not match the file name {name!r}")
    if "description" in pack and (not isinstance(pack["description"], str) or not pack["description"].strip()):
        out.append("description must be a non-empty string")

    secs = pack.get("clip_seconds")
    if "clip_seconds" in pack and not (isinstance(secs, dict) and set(secs) == {"min", "max"} and _is_int(secs["min"]) and _is_int(secs["max"])
            and 0 < secs["min"] < secs["max"]):
        out.append("clip_seconds must be {\"min\": int, \"max\": int} with 0 < min < max")

    ver = pack.get("verification")
    if "verification" not in pack:
        pass
    elif not isinstance(ver, dict) or set(ver) != set(VERIFICATION_KEYS):
        out.append(f"verification must have exactly the keys {', '.join(VERIFICATION_KEYS)}")
    else:
        for key in VERIFICATION_KEYS:
            if not _string_list(ver[key]):
                out.append(f"verification.{key} must be a list of non-empty strings")

    ov = pack.get("overlays")
    if "overlays" in pack and not (isinstance(ov, dict) and set(ov) == {"speaker", "disclaimer"} and isinstance(ov["speaker"], bool)
            and (ov["disclaimer"] is None or isinstance(ov["disclaimer"], str))):
        out.append("overlays must be {\"speaker\": bool, \"disclaimer\": string or null}")

    src = pack.get("sources")
    want = {"queries", "watchlist", "max_age_days", *SOURCE_INT_KEYS}
    if "sources" not in pack:
        pass
    elif not isinstance(src, dict) or set(src) != want:
        out.append(f"sources must have exactly the keys {', '.join(sorted(want))}")
    else:
        if not _string_list(src["queries"]) or not src["queries"]:
            out.append("sources.queries must be a non-empty list of strings")
        if not _string_list(src["watchlist"]):
            out.append("sources.watchlist must be a list of strings")
        for key in SOURCE_INT_KEYS:
            if not _is_int(src[key]) or src[key] < 0:
                out.append(f"sources.{key} must be a non-negative integer")
        if src["max_age_days"] is not None and (not _is_int(src["max_age_days"]) or src["max_age_days"] <= 0):
            out.append("sources.max_age_days must be a positive integer or null")
    return out


def load_pack(name: str, directory: Path) -> Dict[str, Any]:
    """The validated pack called ``name``. Raises DomainError listing every problem."""
    directory = Path(directory)
    if not NAME.match(name or ""):
        raise DomainError(f"invalid domain name {name!r}: use lowercase letters, digits and hyphens")
    path = directory / f"{name}.json"
    if not path.exists():
        raise DomainError(f"unknown domain {name!r}; available: {', '.join(list_packs(directory))}")
    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DomainError(f"{path}: cannot read the pack: {exc}") from None
    problems = _problems(name, pack)
    if problems:
        raise DomainError(f"{path}:\n" + "\n".join(f"  - {p}" for p in problems))
    return pack
