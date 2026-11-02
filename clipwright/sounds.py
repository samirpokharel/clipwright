"""Sound library, synthesized sounds, shot-change detection and the per-clip mix plan.

Gains and levels follow brand.json `mix`. Pure planning code (plan_mix, credits,
load_library) needs no ffmpeg; ensure_synth and detect_shot_changes call ffmpeg.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .timing import to_clip_time

KINDS = ("music", "whoosh", "pop", "sting", "outro")
LICENSES = ("none", "CC0", "CC-BY", "own")

WHOOSH_MIN_GAP = 4.0
MAX_POPS = 3
OUTRO_SECONDS = 0.6
SCENE_THRESHOLD = 0.35


class SoundError(ValueError):
    """A sound library entry is invalid or missing."""


@dataclass
class Event:
    kind: str
    file: str
    start: float
    gain_db: float
    entry_id: str = ""


@dataclass
class MixPlan:
    events: List[Event] = field(default_factory=list)
    music: Optional[Dict[str, Any]] = None


# lavfi sources for the built-in sounds. Frequencies in the pad are chosen so every
# sine completes whole cycles in 30 s, which makes the loop seamless.
_SYNTH_RECIPES = {
    "whoosh": "anoisesrc=d=0.4:c=pink:r=44100:a=0.7,bandpass=f=1800:w=1.5,"
              "afade=t=in:d=0.1,afade=t=out:st=0.1:d=0.3,volume=3",
    "pop": "sine=f=180:d=0.08:r=44100,afade=t=out:st=0:d=0.08:curve=exp,volume=5",
    "sting": "aevalsrc='if(lt(t,0.45),0.5*sin(2*PI*(300*t+333.3*t*t))*min(1,t*30),"
             "0.8*sin(2*PI*90*t)*exp(-8*(t-0.45)))':d=0.6:s=44100",
    "outro": "aevalsrc='0.5*sin(2*PI*(500*t-208.3*t*t))*exp(-3*t)':d=0.6:s=44100",
    "pad": "aevalsrc='0.12*(sin(2*PI*220*t)+sin(2*PI*277.2*t)+sin(2*PI*330*t))"
           "*(0.75+0.25*sin(2*PI*0.2*t))':d=30:s=44100",
}

_SYNTH_KIND = {"whoosh": "whoosh", "pop": "pop", "sting": "sting", "outro": "outro", "pad": "music"}

SYNTH_ENTRIES: List[Dict[str, Any]] = [
    {"id": f"synth-{name}", "kind": kind, "file": f"synth/{name}.wav", "source": "synthesized",
     "license": "none", "author": None, "url": None}
    for name, kind in _SYNTH_KIND.items()
]


def ensure_synth(sounds_dir: Path) -> None:
    """Generate the built-in sounds into sounds_dir/synth/ if they are missing."""
    out_dir = Path(sounds_dir) / "synth"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, source in _SYNTH_RECIPES.items():
        target = out_dir / f"{name}.wav"
        if target.exists() and target.stat().st_size > 0:
            continue
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-ac", "1", "-ar", "44100", str(target)],
            check=True,
        )


def _validate_entry(entry: Dict[str, Any], sounds_dir: Path, seen: set) -> Dict[str, Any]:
    for key in ("id", "kind", "file", "license"):
        if not entry.get(key):
            raise SoundError(f"library entry {entry.get('id', '?')!r}: missing field {key}")
    ident = entry["id"]
    if ident in seen:
        raise SoundError(f"library entry {ident!r}: duplicate id")
    seen.add(ident)
    if entry["kind"] not in KINDS:
        raise SoundError(f"library entry {ident!r}: kind {entry['kind']!r} must be one of {', '.join(KINDS)}")
    if entry["license"] not in LICENSES:
        raise SoundError(f"library entry {ident!r}: licence {entry['license']!r} is not allowed "
                         f"(allowed: {', '.join(LICENSES)})")
    if entry["license"] == "CC-BY" and not entry.get("author"):
        raise SoundError(f"library entry {ident!r}: CC-BY needs an author")
    if not (Path(sounds_dir) / entry["file"]).exists():
        raise SoundError(f"library entry {ident!r}: file {entry['file']} not found in {sounds_dir}")
    entry = dict(entry)
    entry.setdefault("source", "own")
    if entry["license"] == "CC-BY" and not entry.get("attribution"):
        entry["attribution"] = f"{entry['id']} by {entry['author']} (CC BY)"
    return entry


def load_library(sounds_dir: Path, *, ensure: bool = False) -> List[Dict[str, Any]]:
    """Built-in synthesized entries plus the validated entries in sounds_dir/library.json."""
    sounds_dir = Path(sounds_dir)
    if ensure:
        ensure_synth(sounds_dir)
    path = sounds_dir / "library.json"
    raw: List[Dict[str, Any]] = []
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise SoundError(f"library.json is not valid JSON: {exc}") from exc
        if not isinstance(raw, list):
            raise SoundError("library.json must be a list of entries")
    seen = {e["id"] for e in SYNTH_ENTRIES}
    return [dict(e) for e in SYNTH_ENTRIES] + [_validate_entry(e, sounds_dir, seen) for e in raw]


def _pick(library: Sequence[Dict[str, Any]], kind: str, clip_index: int) -> Optional[Dict[str, Any]]:
    own = [e for e in library if e["kind"] == kind and e.get("source") != "synthesized"]
    pool = own or [e for e in library if e["kind"] == kind]
    return pool[clip_index % len(pool)] if pool else None


def plan_mix(
    style: Dict[str, Any],
    duration: float,
    pops: Sequence[float],
    shots: Sequence[float],
    library: Sequence[Dict[str, Any]],
    clip_index: int,
    source_music: bool,
) -> MixPlan:
    """Decide which sounds play when, and at what gain, for one clip."""
    mix = style["mix"]
    levels = style["sound"]

    def gain(level: str, kind: str) -> Optional[float]:
        if level == "off":
            return None
        return mix[f"{kind}_db"] + (mix["low_offset_db"] if level == "low" else 0.0)

    plan = MixPlan()

    def add(kind: str, start: float, level_key: str, gain_key: str) -> None:
        g = gain(levels[level_key], gain_key)
        item = _pick(library, kind, clip_index)
        if g is None or item is None or start >= duration:
            return
        plan.events.append(Event(kind, item["file"], float(start), g, item["id"]))

    add("sting", 0.0, "sting", "sting")
    add("outro", max(0.0, duration - OUTRO_SECONDS), "sting", "sting")

    last = None
    for t in sorted(shots):
        if last is None or t - last >= WHOOSH_MIN_GAP:
            add("whoosh", t, "whoosh", "whoosh")
            last = t
    for t in sorted(pops)[:MAX_POPS]:
        add("pop", t, "pop", "pop")

    music_gain = gain(levels["music"], "music")
    track = _pick(library, "music", clip_index)
    if music_gain is not None and not source_music and track is not None:
        plan.music = {"id": track["id"], "file": track["file"], "gain_db": music_gain}
    plan.events.sort(key=lambda e: e.start)
    return plan


def credits(plans: Sequence[MixPlan], library: Sequence[Dict[str, Any]]) -> List[str]:
    """One attribution line per CC-BY library sound used in any plan."""
    used = set()
    for p in plans:
        used.update(e.entry_id for e in p.events)
        if p.music:
            used.add(p.music["id"])
    lines = []
    for item in library:
        if item["id"] in used and item.get("license") == "CC-BY":
            line = item.get("attribution") or f"{item['id']} by {item.get('author')} (CC BY)"
            lines.append(f"{line} {item['url']}" if item.get("url") else line)
    return lines


def detect_shot_changes(
    video: Path,
    keep_ranges: Sequence[Sequence[float]],
    threshold: float = SCENE_THRESHOLD,
    offsets: Optional[Sequence[float]] = None,
) -> List[float]:
    """Shot-change times in clip seconds, using ffmpeg's scene score over each kept range."""
    ranges = [(float(a), float(b)) for a, b in keep_ranges]
    found: List[float] = []
    for start, end in ranges:
        proc = subprocess.run(
            ["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(end - start), "-i", str(video),
             "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
            capture_output=True, text=True, check=True,
        )
        for match in re.finditer(r"pts_time:([0-9.]+)", proc.stderr):
            clip_time = to_clip_time(start + float(match.group(1)), ranges, offsets)
            if clip_time is not None and clip_time > 0:
                found.append(clip_time)
    return sorted(found)
