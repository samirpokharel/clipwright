"""Pure helpers behind the CLI: argument parser, style resolution for every segment,
file naming and preview range truncation. Stdlib only, so they run on the host in tests."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import layout, style
from .sounds import KINDS, MixPlan, credits
from .style import StyleError

SOUND_KINDS = ("music", "whoosh", "pop", "sting")
BRAND_HELP = "use brands/<NAME>/brand.json and write to out/<NAME>/<job>/ (default: root brand.json, out/<job>/)"
BRAND_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clip", description="Claude Code driven clipping pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download and transcribe a video")
    f.add_argument("source")
    f.add_argument("--captions", metavar="LANG",
                   help="use YouTube's captions in LANG (e.g. ne) instead of Whisper")

    sub.add_parser("schema", help="print the style fields and bounds as JSON")
    pr = sub.add_parser("profiles", help="list profiles with their resolved values")
    pr.add_argument("--brand", help=BRAND_HELP)

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
    r.add_argument("--letterbox", action="store_true",
                   help="upstream layout: blurred background for content/webcam shots")
    r.add_argument("--exact", action="store_true", help="use my start and end timestamps verbatim (no sentence snapping)")
    r.add_argument("--brand", help=BRAND_HELP)

    b = sub.add_parser("brand-preview", help="render a 3 second sample from cached pass 1")
    b.add_argument("job")
    b.add_argument("--segment", type=int, default=1)
    b.add_argument("--segments", default=None, help="segments.json (default jobs/<job>/segments.json)")
    b.add_argument("--allow-brand-override", action="store_true")
    b.add_argument("--brand", help=BRAND_HELP)

    fr = sub.add_parser("frames", help="contact sheet of a segment or time range, to choose layouts from what is on screen")
    fr.add_argument("job")
    fr.add_argument("--segment", type=int, help="1-based segment number in segments.json")
    fr.add_argument("--segments", default=None, help="segments.json (default jobs/<job>/segments.json)")
    fr.add_argument("--from", dest="start", help="start time, MM:SS (instead of --segment)")
    fr.add_argument("--to", dest="end", help="end time, MM:SS (instead of --segment)")
    fr.add_argument("--every", type=float, default=3.0, help="seconds between frames (default 3)")

    s = sub.add_parser("sounds", help="manage the sound library")
    ssub = s.add_subparsers(dest="sounds_cmd", required=True)
    add = ssub.add_parser("add", help="add a Freesound sound (CC0 or CC-BY) or your own file")
    add.add_argument("target", nargs="?", help="Freesound URL or id")
    add.add_argument("--kind", required=True, choices=KINDS)
    add.add_argument("--file", help="a local file instead of a Freesound sound")
    add.add_argument("--license", choices=["CC0", "CC-BY", "own"],
                     help="required with --file; there is no default")
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
            try:
                bounds = (layout.parse_time(segment["start_time"]), layout.parse_time(segment["end_time"]))
            except (KeyError, ValueError) as exc:
                raise StyleError(f"{where}: start_time and end_time must be times: {exc}") from None
            resolved["layout"]["ranges"] = layout.parse_ranges(segment.get("layout_ranges"), *bounds, where)
            styles.append(resolved)
        except StyleError as exc:
            errors.append(str(exc))
    if errors:
        raise StyleError("\n".join(errors))
    return styles


def safe_job_id(stem: str) -> str:
    """A job id usable inside ffmpeg filter paths: letters, digits, underscore and hyphen only.

    YouTube ids already qualify. Local file names with quotes, commas, semicolons, brackets or
    colons would break the filter graph that pass 2 builds from the job folder path.
    """
    return re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "job"


def brand_paths(work: Path, brand: Optional[str]) -> Tuple[Path, Path]:
    """``(brand.json, out root)`` for a brand name, or the root brand.json and ``out/`` with no name."""
    if not brand:
        return work / "brand.json", work / "out"
    if not BRAND_NAME_RE.match(brand):
        raise PipelineError(f"brand name {brand!r}: use lowercase letters, digits, _ and -")
    path = work / "brands" / brand / "brand.json"
    if not path.is_file():
        raise PipelineError(f"brand {brand!r} not found: expected {path}")
    return path, work / "out" / brand


def clip_filename(index: int, segment: Dict[str, Any]) -> str:
    start = str(segment["start_time"]).replace(":", "")
    end = str(segment["end_time"]).replace(":", "")
    return f"{index:02d}_clip_{start}-{end}.mp4"


class PipelineError(ValueError):
    """The cached pass-1 state does not match the request. The message names the segment."""


def layout_signature(style_: Dict[str, Any]) -> Dict[str, Any]:
    """The part of a resolved style that decides how pass 1 frames the clip."""
    lay = style_["layout"]
    return {"mode": lay["mode"], "ranges": [[s, e, k] for s, e, k in lay.get("ranges", [])]}


def entry_for(cache: Dict[str, Any], index: int, segment: Dict[str, Any],
              style_: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The cached pass-1 entry for a segment, joined with its title and key words from segments.json."""
    entry = cache.get(str(index))
    if not entry or not Path(entry["pass1"]).exists():
        raise PipelineError(f"segment {index}: no cached pass 1; run render without --recompose")
    if (entry["start_time"], entry["end_time"]) != (segment["start_time"], segment["end_time"]):
        raise PipelineError(
            f"segment {index}: start or end time changed since pass 1; run render without --recompose")
    if style_ is not None and entry.get("layout", {"mode": "auto", "ranges": []}) != layout_signature(style_):
        raise PipelineError(f"segment {index}: layout changed since pass 1; run render without --recompose")
    return dict(entry, hook_title=segment.get("hook_title"), key_words=segment.get("key_words") or [])


def check_entries(cache: Dict[str, Any], indexes: Sequence[int], segments: Sequence[Dict[str, Any]],
                  styles: Optional[Sequence[Dict[str, Any]]] = None) -> None:
    """Validate every cached entry up front so a bad one cannot stop the run half way."""
    errors = []
    for i in indexes:
        try:
            entry_for(cache, i, segments[i - 1], styles[i - 1] if styles else None)
        except PipelineError as exc:
            errors.append(str(exc))
    if errors:
        raise PipelineError("\n".join(errors))


def compose_all(
    indexes: Sequence[int],
    segments: Sequence[Dict[str, Any]],
    styles: Sequence[Dict[str, Any]],
    cache: Dict[str, Any],
    library: Sequence[Dict[str, Any]],
    out_dir: Path,
    workdir: Path,
    compose_one: Callable[..., Dict[str, Any]],
    previous: Sequence[Dict[str, Any]],
    log: Callable[..., None] = print,
):
    """Run pass 2 for each selected segment. One clip failing never stops the others.

    ``compose_one(i, segment, style, entry, library, part_path, workdir)`` renders to ``part_path``
    and returns ``{"plan": MixPlan}``. The output manifest and credits.txt are written in a
    ``finally`` so clips already finished are always listed. Returns (fresh entries, failed indexes).
    """
    out_dir = Path(out_dir)
    fresh: List[Dict[str, Any]] = []
    failed: List[int] = []
    try:
        for i in indexes:
            segment, st = segments[i - 1], styles[i - 1]
            dest = out_dir / clip_filename(i, segment)
            part = dest.with_name(dest.stem + ".part.mp4")
            try:
                entry = entry_for(cache, i, segment, st)
                done = compose_one(i, segment, st, entry, library, part, workdir)
            except Exception as exc:  # any failure in this clip, not only ffmpeg's
                log(f"segment {i} failed ({type(exc).__name__}): {exc}", file=sys.stderr)
                part.unlink(missing_ok=True)
                failed.append(i)
                continue
            replace_output(part, dest, i)
            title = (segment.get("hook_title") or "").strip()
            fresh.append({"file": str(dest), "hook_title": title, "duration": entry["duration"],
                          "profile": (segment.get("style") or {}).get("profile"),
                          "credits": credits([done["plan"]], library)})
            log(f"{dest}  {entry['duration']:.1f}s  {title}")
            log(f"    sounds: {describe_plan(done['plan'])}")
    finally:
        replaced = {int(Path(m["file"]).name[:2]) for m in fresh}
        kept = [m for m in previous if int(Path(m["file"]).name[:2]) not in replaced]
        manifest = sorted(kept + fresh, key=lambda m: Path(m["file"]).name)
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        lines = sorted({line for m in manifest for line in m.get("credits", [])})
        (out_dir / "credits.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
    return fresh, failed


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
