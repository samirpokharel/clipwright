"""Brand identity, profiles and per-clip style: load, merge, validate, describe.

A clip's style is three layers merged in order: brand base, profile, clip override.
Identity fields never change through a profile or override unless explicitly allowed.
Every bound lives in BOUNDS, which also drives schema().
"""

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")

SIZES = ["small", "medium", "large"]
LEVELS = ["off", "low", "normal"]

# Font pixel sizes at 1080 wide for each size name. Tunable after visual checks.
CAPTION_PX = {"small": 72, "medium": 90, "large": 110}
TITLE_PX = {"small": 56, "medium": 72, "large": 90}

IDENTITY = ("handle", "accent", "text", "outline", "headline_font")
LOCKED = list(IDENTITY) + ["title.text_color"]
SECTIONS = ("caption", "title", "progress_bar", "sound", "layout")

BOUNDS: Dict[str, Dict[str, Any]] = {
    "layout.mode": {"type": "enum", "values": ["auto", "fill", "fit"]},
    "caption.size": {"type": "enum", "values": SIZES},
    "caption.words_per_line": {"type": "int", "min": 1, "max": 6},
    "caption.uppercase": {"type": "bool"},
    "caption.position_y": {"type": "float", "min": 0.55, "max": 0.80},
    "caption.outline_px": {"type": "int", "min": 0, "max": 6},
    "title.enabled": {"type": "bool"},
    "title.seconds": {"type": "float", "min": 1, "max": 8},
    "title.size": {"type": "enum", "values": SIZES},
    "title.max_lines": {"type": "int", "min": 1, "max": 3},
    "title.tilt_degrees": {"type": "float", "min": -5, "max": 5},
    "title.top": {"type": "float", "min": 0.03, "max": 0.12},
    "progress_bar.enabled": {"type": "bool"},
    "progress_bar.height_px": {"type": "int", "min": 2, "max": 10},
    "sound.music": {"type": "enum", "values": LEVELS},
    "sound.whoosh": {"type": "enum", "values": LEVELS},
    "sound.pop": {"type": "enum", "values": LEVELS},
    "sound.sting": {"type": "enum", "values": LEVELS},
}

BRAND_KEYS = set(IDENTITY) | {"base", "mix"}
MIX_KEYS = ("music_db", "whoosh_db", "pop_db", "sting_db", "low_offset_db", "target_lufs")


class StyleError(ValueError):
    """A style, profile or brand value is invalid. The message names the field."""


def _check(path: str, value: Any, spec: Dict[str, Any], where: str) -> None:
    kind = spec["type"]
    if kind == "bool":
        ok = isinstance(value, bool)
    elif kind == "enum":
        ok = value in spec["values"]
    else:
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if kind == "int":
            number = number and float(value).is_integer()
        ok = number and spec["min"] <= value <= spec["max"]
    if not ok:
        allowed = spec["values"] if kind == "enum" else (
            "true or false" if kind == "bool" else f"{kind} from {spec['min']} to {spec['max']}"
        )
        raise StyleError(f"{where}: {path} = {value!r} is invalid, allowed: {allowed}")


def _hex(path: str, value: Any, where: str) -> None:
    if not isinstance(value, str) or not HEX.match(value):
        raise StyleError(f"{where}: {path} = {value!r} must be a #RRGGBB colour")


def _deep_merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def load_brand(path: Path, fonts_dir: Optional[Path] = None) -> Dict[str, Any]:
    where = f"brand file {Path(path).name}"
    try:
        brand = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StyleError(f"{where}: cannot read: {exc}") from exc
    if not isinstance(brand, dict):
        raise StyleError(f"{where}: must be a JSON object")
    for key in brand:
        if key not in BRAND_KEYS:
            raise StyleError(f"{where}: unknown field {key}")
    for key in BRAND_KEYS:
        if key not in brand:
            raise StyleError(f"{where}: missing field {key}")
    if not isinstance(brand["handle"], str) or not brand["handle"]:
        raise StyleError(f"{where}: handle must be a non-empty string")
    for key in ("accent", "text", "outline"):
        _hex(key, brand[key], where)
    font = brand["headline_font"]
    if not isinstance(font, str) or not font:
        raise StyleError(f"{where}: headline_font must be a non-empty string")
    if fonts_dir is not None and not (Path(fonts_dir) / f"{font}.ttf").exists():
        raise StyleError(f"{where}: headline_font {font!r} not found in {fonts_dir}")

    base = brand["base"]
    for section in SECTIONS:
        if not isinstance(base.get(section), dict):
            raise StyleError(f"{where}: base.{section} is missing")
    for path_, spec in BOUNDS.items():
        section, name = path_.split(".")
        if name not in base[section]:
            raise StyleError(f"{where}: base.{path_} is missing")
        _check(f"base.{path_}", base[section][name], spec, where)
    _hex("base.title.text_color", base["title"].get("text_color"), where)
    alpha = base["progress_bar"].get("track_alpha")
    if not isinstance(alpha, (int, float)) or not 0 <= alpha <= 1:
        raise StyleError(f"{where}: base.progress_bar.track_alpha must be a number from 0 to 1")
    for section, extra in (("title", {"text_color"}), ("progress_bar", {"track_alpha"})):
        allowed = {p.split(".")[1] for p in BOUNDS if p.startswith(section + ".")} | extra
        for key in base[section]:
            if key not in allowed:
                raise StyleError(f"{where}: unknown field base.{section}.{key}")
    mix = brand["mix"]
    for key in MIX_KEYS:
        if not isinstance(mix.get(key), (int, float)) or isinstance(mix.get(key), bool):
            raise StyleError(f"{where}: mix.{key} must be a number")
    for key in mix:
        if key not in MIX_KEYS:
            raise StyleError(f"{where}: unknown field mix.{key}")
    return brand


def _profile_record(path: Path) -> Dict[str, Any]:
    where = f"profile {path.stem}"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StyleError(f"{where}: cannot read: {exc}") from exc
    if not isinstance(data, dict) or set(data) - {"description", "style"} or "style" not in data:
        raise StyleError(f"{where}: must be an object with 'description' and 'style'")
    return data


def load_profile(name: str, profiles_dir: Path) -> Dict[str, Any]:
    """Return the profile's partial style, ready for resolve_style."""
    profiles_dir = Path(profiles_dir)
    path = profiles_dir / f"{name}.json"
    if not NAME.match(name) or not path.exists():
        available = sorted(p.stem for p in profiles_dir.glob("*.json")) if profiles_dir.exists() else []
        raise StyleError(f"unknown profile {name!r} (available: {', '.join(available) or 'none'})")
    return _profile_record(path)["style"]


def list_profiles(profiles_dir: Path) -> Dict[str, Dict[str, Any]]:
    return {p.stem: _profile_record(p) for p in sorted(Path(profiles_dir).glob("*.json"))}


def _partial(data: Any, where: str, source: str, allow_identity: bool):
    """Validate a profile or clip override. Returns (style part, identity part)."""
    if not isinstance(data, dict):
        raise StyleError(f"{where}: {source} style must be an object")
    part: Dict[str, Any] = {}
    identity: Dict[str, Any] = {}
    for key, value in data.items():
        if key == "profile" and source == "clip":
            continue
        if key in IDENTITY:
            if not allow_identity:
                raise StyleError(f"{where}: {key} is a locked identity field (use --allow-brand-override)")
            if key in ("accent", "text", "outline"):
                _hex(key, value, where)
            identity[key] = value
        elif key in SECTIONS:
            if not isinstance(value, dict):
                raise StyleError(f"{where}: {key} must be an object")
            for name, item in value.items():
                path = f"{key}.{name}"
                if path == "title.text_color":
                    if not allow_identity:
                        raise StyleError(f"{where}: {path} is a locked identity field (use --allow-brand-override)")
                    _hex(path, item, where)
                elif path in BOUNDS:
                    _check(path, item, BOUNDS[path], where)
                else:
                    raise StyleError(f"{where}: unknown field {path}")
                part.setdefault(key, {})[name] = item
        else:
            raise StyleError(f"{where}: unknown field {key}")
    return part, identity


def resolve_style(
    brand: Dict[str, Any],
    profile: Optional[Dict[str, Any]],
    override: Optional[Dict[str, Any]],
    *,
    where: str,
    allow_brand_override: bool = False,
) -> Dict[str, Any]:
    """Merge brand base, profile and clip override into one validated style."""
    merged = copy.deepcopy(brand["base"])
    identity = {key: brand[key] for key in IDENTITY}
    for source, data in (("profile", profile), ("clip", override)):
        if not data:
            continue
        part, ident = _partial(data, where, source, allow_brand_override)
        _deep_merge(merged, part)
        identity.update(ident)
    for path, spec in BOUNDS.items():
        section, name = path.split(".")
        _check(path, merged[section][name], spec, where)
    return {
        "identity": identity,
        "caption": merged["caption"],
        "title": merged["title"],
        "progress_bar": merged["progress_bar"],
        "sound": merged["sound"],
        "layout": merged["layout"],
        "mix": copy.deepcopy(brand["mix"]),
    }


def schema() -> Dict[str, Any]:
    """Describe every style field Claude Code may set, with bounds, as JSON-ready data."""
    return {
        "usage": "Segment 'style': {\"profile\": name, caption: {...}, title: {...}, progress_bar: {...}, sound: {...}}",
        "fields": copy.deepcopy(BOUNDS),
        "locked": list(LOCKED),
        "levels": "low plays at mix.low_offset_db below normal; off disables the sound",
    }
