"""Per-clip layout: fill the 9:16 frame around the speaker, or fit the whole frame.

SupoClip's own planner picks fill or fit per shot from face detection, which misses a
presenter who looks down and so shows the full frame over blur. Here Claude Code decides
(`style.layout.mode` and the segment's `layout_ranges`) after looking at frames, and this
module turns that into an ffmpeg filter. Pure functions, stdlib only.
"""

import math
import statistics
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from .style import StyleError

OUT_W, OUT_H = 1080, 1920
KINDS = ("fill", "fit")
RANGE_TOLERANCE = 1.0  # seconds a range may reach past the segment (sentence snapping moves its ends)
FRAMES_PER_ROW = 5


@dataclass(frozen=True)
class Run:
    start: float  # clip seconds
    end: float
    kind: str


def parse_time(value: Any) -> float:
    """Seconds from a number, "SS", "MM:SS" or "HH:MM:SS"."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"not a time: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"not a time: {value!r}")
    parts = value.strip().split(":")
    if len(parts) > 3:
        raise ValueError(f"not a time: {value!r}")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise ValueError(f"not a time: {value!r}") from None
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def parse_ranges(raw: Any, seg_start: float, seg_end: float, where: str) -> List[Tuple[float, float, str]]:
    """Validate a segment's ``layout_ranges`` and return ``(start, end, kind)`` in source seconds, sorted."""
    if raw is None or raw == []:
        return []
    if not isinstance(raw, list):
        raise StyleError(f"{where}: layout_ranges must be a list")
    out: List[Tuple[float, float, str]] = []
    for index, item in enumerate(raw):
        name = f"{where}: layout_ranges[{index}]"
        if not isinstance(item, dict) or set(item) != {"from", "to", "layout"}:
            raise StyleError(f"{name} must be an object with exactly from, to and layout")
        if item["layout"] not in KINDS:
            raise StyleError(f"{name}.layout = {item['layout']!r} must be one of {', '.join(KINDS)}")
        try:
            start, end = parse_time(item["from"]), parse_time(item["to"])
        except ValueError as exc:
            raise StyleError(f"{name}: {exc}") from None
        if end <= start:
            raise StyleError(f"{name}: from must be before to")
        if start < seg_start - RANGE_TOLERANCE or end > seg_end + RANGE_TOLERANCE:
            raise StyleError(f"{name} is outside the segment ({seg_start:g} to {seg_end:g} seconds)")
        out.append((start, end, item["layout"]))
    out.sort()
    for before, after in zip(out, out[1:]):
        if after[0] < before[1] - 1e-6:
            raise StyleError(f"{where}: layout_ranges overlap around {after[0]:g} seconds")
    return out


def needs_layout(mode: str, ranges: Sequence[Tuple[float, float, str]]) -> bool:
    """True when the clip must be rendered here instead of by SupoClip's own planner."""
    return mode != "auto" or bool(ranges)


def plan_runs(mode: str, ranges: Sequence[Tuple[float, float, str]], clip_start: float, clip_end: float) -> List[Run]:
    """Contiguous fill/fit runs in clip seconds. Time not covered by a range takes the mode.

    ``auto`` with ranges treats uncovered time as ``fit`` (show the whole frame when unsure).
    """
    base = mode if mode in KINDS else "fit"
    duration = round(clip_end - clip_start, 3)
    pieces: List[Tuple[float, float, str]] = []
    cursor = 0.0
    for start, end, kind in sorted(ranges):
        s = round(max(start, clip_start) - clip_start, 3)
        e = round(min(end, clip_end) - clip_start, 3)
        if e <= s:
            continue
        if s > cursor:
            pieces.append((cursor, s, base))
        pieces.append((max(s, cursor), e, kind))
        cursor = e
    if cursor < duration:
        pieces.append((cursor, duration, base))
    runs: List[Run] = []
    for start, end, kind in pieces:
        if end - start < 0.001:
            continue
        if runs and runs[-1].kind == kind and runs[-1].end == start:
            runs[-1] = Run(runs[-1].start, end, kind)
        else:
            runs.append(Run(start, end, kind))
    return runs


MIN_RUN_SECONDS = 0.1


def snap_runs(runs: Sequence[Run], cuts: Sequence[float], window: float = 1.0) -> List[Run]:
    """Move each internal run boundary to the nearest shot change within ``window`` seconds.

    Ranges are chosen from frames a few seconds apart, so a boundary can be a little off the
    real cut. The clip's own start and end never move, and a snap never leaves a run shorter
    than MIN_RUN_SECONDS.
    """
    if len(runs) < 2 or not cuts:
        return list(runs)
    bounds = [[r.start, r.end] for r in runs]
    for i in range(len(bounds) - 1):
        boundary = bounds[i][1]
        near = [c for c in cuts if abs(c - boundary) <= window]
        if not near:
            continue
        best = min(near, key=lambda c: abs(c - boundary))
        if bounds[i][0] + MIN_RUN_SECONDS <= best <= bounds[i + 1][1] - MIN_RUN_SECONDS:
            bounds[i][1] = best
            bounds[i + 1][0] = best
    return [Run(b[0], b[1], r.kind) for b, r in zip(bounds, runs)]


def crop_width(src_h: int) -> int:
    return (int(src_h * 9 / 16) // 2) * 2


def crop_x(centres: Sequence[Tuple[float, float]], start: float, end: float, src_w: int, cw: int,
           fallback: Optional[int] = None) -> int:
    """Left edge of the portrait crop: the median face centre inside the run, else ``fallback``, else the middle."""
    xs = sorted(x for t, x in centres if start <= t <= end)
    if xs:
        left = int(statistics.median(xs) - cw / 2)
    elif fallback is not None:
        left = fallback
    else:
        left = (src_w - cw) // 2
    left = max(0, min(left, src_w - cw))
    return left - left % 2


def _g(value: float) -> str:
    return f"{value:g}"


def build_filter(runs: Sequence[Run], src_w: int, src_h: int, xs: Sequence[Optional[int]]) -> str:
    """filter_complex over input 0 that renders each run as fill or fit and concatenates them into [vout]."""
    cw = crop_width(src_h)
    parts: List[str] = []
    for i, run in enumerate(runs):
        head = f"[0:v]trim=start={_g(run.start)}:end={_g(run.end)},setpts=PTS-STARTPTS"
        if run.kind == "fill":
            if cw >= src_w:  # already portrait or square: cover the frame instead of cropping
                crop = f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase:flags=lanczos,crop={OUT_W}:{OUT_H}"
            else:
                crop = f"crop={cw}:{src_h}:{xs[i]}:0,scale={OUT_W}:{OUT_H}:flags=lanczos"
            parts.append(f"{head},{crop},setsar=1[v{i}]")
        else:
            parts.append(
                f"{head},split=2[bg{i}][fg{i}];"
                f"[bg{i}]scale={OUT_W // 2}:{OUT_H // 2}:force_original_aspect_ratio=increase,"
                f"crop={OUT_W // 2}:{OUT_H // 2},gblur=sigma=14:steps=2,scale={OUT_W}:{OUT_H}:flags=bilinear,setsar=1[b{i}];"
                f"[fg{i}]scale={OUT_W}:-2:flags=lanczos,setsar=1[f{i}];"
                f"[b{i}][f{i}]overlay=(W-w)/2:(H-h)/2[v{i}]"
            )
    parts.append("".join(f"[v{i}]" for i in range(len(runs))) + f"concat=n={len(runs)}:v=1:a=0[vout]")
    return ";".join(parts)


def frames_args(source: str, start: float, duration: float, every: float, out: str,
                font: Optional[str] = None) -> List[str]:
    """ffmpeg command for a contact sheet: one frame every ``every`` seconds, labelled with source time."""
    count = max(1, math.ceil(duration / every))
    cols = min(FRAMES_PER_ROW, count)
    rows = math.ceil(count / cols)
    label = ""
    if font:
        label = (f",drawtext=fontfile={font}:text='%{{pts\\:hms\\:{_g(start)}}}':x=6:y=6:fontsize=24:"
                 "fontcolor=white:box=1:boxcolor=black@0.65")
    vf = f"fps=1/{_g(every)},scale=320:-1{label},tile={cols}x{rows}"
    return ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(duration), "-i", source,
            "-vf", vf, "-frames:v", "1", out]
