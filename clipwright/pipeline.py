"""Pure helpers behind the CLI: argument parser, style resolution for every segment,
file naming and preview range truncation. Stdlib only, so they run on the host in tests."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from . import style
from .sounds import KINDS, MixPlan
from .style import StyleError

SOUND_KINDS = ("music", "whoosh", "pop", "sting")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clip", description="Claude Code driven clipping pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download and transcribe a video")
    f.add_argument("source")

    sub.add_parser("schema", help="print the style fields and bounds as JSON")
    sub.add_parser("profiles", help="list profiles with their resolved values")

    r = sub.add_parser("render", help="render clips from segments.json")
    r.add_argument("job")
    r.add_argument("segments")
    r.add_argument("--only", type=int, nargs="+", metavar="N",
                   help="render only these 1-based segment numbers; other clips are left alone")
    r.add_argument("--recompose", action="store_true", help="reuse cached pass 1, redo pass 2 only")
    r.add_argument("--allow-brand-override", action="store_true",
                   help="allow identity fields (accent, font, handle...) in profiles or clip styles")
    for kind in SOUND_KINDS:
        r.add_argument(f"--no-{kind}", action="store_true", help=f"turn off {kind} for this run")
    r.add_argument("--clip-length", default="auto", choices=["auto", "short", "medium", "long"])
    r.add_argument("--max-seconds", type=float, default=60.0)
    r.add_argument("--no-subtitles", action="store_true", help="skip captions")
    r.add_argument("--original", action="store_true", help="keep source aspect ratio")
    r.add_argument("--exact", action="store_true", help="skip opening refinement; use my timestamps")

    b = sub.add_parser("brand-preview", help="render a 3 second sample from cached pass 1")
    b.add_argument("job")
    b.add_argument("--segment", type=int, default=1)
    b.add_argument("--segments", default=None, help="segments.json (default jobs/<job>/segments.json)")
    b.add_argument("--allow-brand-override", action="store_true")

    s = sub.add_parser("sounds", help="manage the sound library")
    ssub = s.add_subparsers(dest="sounds_cmd", required=True)
    add = ssub.add_parser("add", help="add a Freesound sound (CC0 or CC-BY) or your own file")
    add.add_argument("target", nargs="?", help="Freesound URL or id")
    add.add_argument("--kind", required=True, choices=KINDS)
    add.add_argument("--file", help="a local file instead of a Freesound sound")
    add.add_argument("--license", choices=["CC0", "CC-BY", "own"], default="own")
    add.add_argument("--author")
    ssub.add_parser("list", help="print the library")
    return p


def resolve_all(
    segments: Sequence[Dict[str, Any]],
    brand: Dict[str, Any],
    profiles_dir: Path,
    *,
    allow_brand_override: bool = False,
    disabled: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """Resolve and validate the style of every segment. Raises one StyleError listing all failures."""
    styles: List[Dict[str, Any]] = []
    errors: List[str] = []
    for number, segment in enumerate(segments, 1):
        where = f"segment {number}"
        override = segment.get("style") or {}
        try:
            if not isinstance(override, dict):
                raise StyleError(f"{where}: style must be an object")
            name = override.get("profile")
            try:
                profile = style.load_profile(name, profiles_dir) if name else None
            except StyleError as exc:
                raise StyleError(f"{where}: {exc}") from exc
            resolved = style.resolve_style(
                brand, profile, override or None, where=where, allow_brand_override=allow_brand_override
            )
            for kind in disabled:
                resolved["sound"][kind] = "off"
            styles.append(resolved)
        except StyleError as exc:
            errors.append(str(exc))
    if errors:
        raise StyleError("\n".join(errors))
    return styles


def clip_filename(index: int, segment: Dict[str, Any]) -> str:
    start = str(segment["start_time"]).replace(":", "")
    end = str(segment["end_time"]).replace(":", "")
    return f"{index:02d}_clip_{start}-{end}.mp4"


def describe_plan(plan: MixPlan) -> str:
    """One line saying which sounds a clip received."""
    count = lambda kind: sum(1 for e in plan.events if e.kind == kind)  # noqa: E731
    whooshes, pops = count("whoosh"), count("pop")
    music = f"music {plan.music['id']} {plan.music['gain_db']} dB" if plan.music else "no music"
    sting = "sting+outro" if count("sting") and count("outro") else ("sting" if count("sting") else "no sting")
    return f"{music}, {whooshes} whoosh{'es' if whooshes != 1 else ''}, {pops} pop{'s' if pops != 1 else ''}, {sting}"


def replace_output(part: Path, dest: Path, index: int) -> None:
    """Move a finished ``part`` file to ``dest`` and delete older renders of the same segment."""
    for stale in dest.parent.glob(f"{index:02d}_*.mp4"):
        if stale != part:
            stale.unlink()
    part.rename(dest)


def truncate_ranges(ranges: Sequence[Tuple[float, float]], seconds: float) -> List[Tuple[float, float]]:
    """The first ``seconds`` of a clip's timeline, expressed as source ranges."""
    out: List[Tuple[float, float]] = []
    left = seconds
    for start, end in ranges:
        if left <= 0:
            break
        take = min(end - start, left)
        out.append((start, start + take))
        left -= take
    return out


def schema_text() -> str:
    return json.dumps(style.schema(), indent=2)


def profiles_text(brand: Dict[str, Any], profiles_dir: Path) -> str:
    out = {}
    for name, record in style.list_profiles(profiles_dir).items():
        resolved = style.resolve_style(brand, record["style"], None, where=name)
        out[name] = {"description": record["description"], "style": record["style"], "resolved": resolved}
    return json.dumps(out, indent=2)
