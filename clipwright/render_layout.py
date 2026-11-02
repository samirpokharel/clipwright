"""Render one clip as fill, fit or a mix of both (pass 1 for clips whose layout is not "auto").

SupoClip's face tracker (analyze_vertical_clip) only places the crop. Cutting, scaling,
blurring and encoding are plain ffmpeg, so SupoClip's own planner never decides the layout.
Runs inside the container because the tracker is SupoClip's.
"""

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import layout, sounds

ANALYSIS_WIDTH = 640


def _probe_size(path: Path) -> Tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    width, height = out.split(",")
    return int(width), int(height)


def _ffmpeg(args: List[str], what: str) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg failed while {what}:\n{tail}")


def face_centres(source: Path, start: float, duration: float, workdir: Path, src_w: int) -> List[Tuple[float, float]]:
    """(clip seconds, face centre x in source pixels) for every sampled frame where SupoClip's tracker sees a face."""
    from src.media.reframing import analyze_vertical_clip

    small = Path(workdir) / "layout-analysis.mp4"
    _ffmpeg(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(duration), "-i", str(source),
             "-vf", f"scale={ANALYSIS_WIDTH}:-2", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
             str(small)], "making the analysis copy")
    track = analyze_vertical_clip(small, analyze_context=False)[0]
    scale = src_w / _probe_size(small)[0]
    return [(t, cx * scale) for t, cx, _area in track if cx is not None]


def render_layout_clip(source: Path, keep: Tuple[float, float], lay: Dict[str, Any], out: Path,
                       workdir: Path) -> Dict[str, Any]:
    """Cut ``keep`` (source seconds) from ``source`` and frame it per ``lay`` ({"mode", "ranges"}) into ``out``.

    Returns {"duration", "runs": [(start, end, kind)], "xs": [crop x or None per run], "faces": n}.
    """
    start, end = float(keep[0]), float(keep[1])
    duration = round(end - start, 3)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    src_w, src_h = _probe_size(source)
    runs = layout.plan_runs(lay["mode"], lay.get("ranges", []), start, end)
    if not runs:
        raise RuntimeError("layout produced no runs; the clip has no duration")
    if len(runs) > 1:  # ranges come from frames seconds apart: land each boundary on the real shot change
        runs = layout.snap_runs(runs, sounds.detect_shot_changes(source, [(start, end)]), window=1.0)

    centres: List[Tuple[float, float]] = []
    if any(r.kind == "fill" for r in runs) and layout.crop_width(src_h) < src_w:
        centres = face_centres(source, start, duration, workdir, src_w)

    cw, xs, previous = layout.crop_width(src_h), [], None
    for run in runs:
        if run.kind == "fill":
            previous = layout.crop_x(centres, run.start, run.end, src_w, cw, fallback=previous)
            xs.append(previous)
        else:
            xs.append(None)

    graph = layout.build_filter(runs, src_w, src_h, xs)
    _ffmpeg(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(duration), "-i", str(source),
             "-filter_complex", graph, "-map", "[vout]", "-map", "0:a:0?",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)],
            "rendering the layout")
    return {"duration": duration, "runs": [(r.start, r.end, r.kind) for r in runs], "xs": xs, "faces": len(centres)}
