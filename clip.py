"""Claude Code driven clipping pipeline (no DB, Redis, frontend or LLM key).

Runs inside the supoclip-backend image, driven by ./clip. See README.md and `clip --help`.

    clip fetch <url|file>            download + transcribe (+ video metadata)
    clip render <job> segments.json  pass 1 (SupoClip cut and frame) then pass 2 (brand + sound)
    clip schema | profiles           what style fields and presets exist
    clip brand-preview <job>         3 second sample from the cached pass 1
    clip frames <job> --segment N    contact sheet to choose each clip's layout from
    clip sounds add|list             manage the sound library

Claude Code does the segment selection and style choice between fetch and render.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from clipwright import compose, freesound, layout, pipeline, render_layout, sounds, style, transcribe
from clipwright.sounds import SoundError
from clipwright.style import StyleError

WORK = Path("/work")
JOBS = WORK / "jobs"
OUT = WORK / "out"
SOUNDS = WORK / "sounds"
PROFILES = WORK / "profiles"
BRAND = WORK / "brand.json"
FONTS = Path("/app/fonts")


def _job_dir(job: str) -> Path:
    return JOBS / job


def _brand() -> Dict[str, Any]:
    return style.load_brand(BRAND, fonts_dir=FONTS)


def _load_segments(path: str) -> List[Dict[str, Any]]:
    segments = json.loads(Path(path).read_text())
    if isinstance(segments, dict):
        segments = segments.get("most_relevant_segments") or segments.get("segments") or []
    return segments


def _metadata(url: str) -> Dict[str, Any]:
    """Title, channel, description, categories and tags from yt-dlp, or {} if unavailable."""
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title"), "channel": info.get("channel") or info.get("uploader"),
            "description": (info.get("description") or "")[:1200],
            "categories": info.get("categories") or [], "tags": (info.get("tags") or [])[:15],
        }
    except Exception as exc:  # metadata is a hint for choosing a style, never a reason to fail
        print(f"video metadata unavailable: {exc}", file=sys.stderr)
        return {}


async def _transcribe(video_path: Path, url) -> str:
    """Timestamped transcript text, with word timings cached for captions. Backend per WHISPER_BACKEND."""
    from src.media.transcription import cache_transcript_data, format_transcript_for_analysis
    from src.services.video_service import VideoService

    backend = transcribe.pick_backend(os.environ.get("WHISPER_BACKEND"), transcribe.faster_available())
    size = os.environ.get("WHISPER_MODEL_SIZE", "small")
    print(f"transcribing with {backend}-whisper ({size})", file=sys.stderr)
    if backend == "openai":
        return await VideoService.generate_transcript(video_path, source_url=url)
    language = (os.environ.get("TRANSCRIPTION_LANGUAGE") or "").split("_")[0] or None  # "en_us" -> "en"
    result = await asyncio.to_thread(transcribe.transcribe_faster, video_path, size, language)
    cache_transcript_data(video_path, result)
    return "\n".join(format_transcript_for_analysis(result))


async def fetch(args) -> None:
    from src.media.transcription import load_cached_transcript_data
    from src.services.video_service import VideoService
    from src.youtube_utils import get_youtube_video_id

    source = args.source
    local = Path(source)
    meta: Dict[str, Any] = {}
    if local.exists():
        video_path, job, url = local, pipeline.safe_job_id(local.stem), None
        meta = {"title": local.stem}
    else:
        video_id = get_youtube_video_id(source)
        if not video_id:
            sys.exit(f"Not a YouTube URL or existing file: {source}")
        job, url = video_id, source
        video_path = await VideoService.download_video(source)
        if not video_path:
            sys.exit("Download failed")
        meta = _metadata(source)

    video_path = await VideoService.prepare_source(Path(video_path))
    transcript = await _transcribe(Path(video_path), url)

    job_dir = _job_dir(job)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    words = (load_cached_transcript_data(Path(video_path)) or {}).get("words") or []
    duration = VideoService._get_file_duration(Path(video_path))
    state = {"video_path": str(video_path), "source": source, "duration": duration, **meta}
    (job_dir / "state.json").write_text(json.dumps(state, indent=2))
    print(f"job={job}")
    print(f"video={video_path} duration={duration}s words={len(words)}")
    if meta.get("title"):
        print(f"title={meta['title']} channel={meta.get('channel')}")
    print(f"transcript={job_dir / 'transcript.txt'} ({len(transcript.splitlines())} lines)")


def _prepare_segments(segments, indexes, video_path, args):
    from src.media.transcription import load_cached_transcript_data
    from src.services.video_service import VideoService

    transcript_data = load_cached_transcript_data(video_path)
    prepared = []
    for seg in (segments[i - 1] for i in indexes):
        virality = seg.get("virality") or {}
        payload = {
            "start_time": seg["start_time"], "end_time": seg["end_time"], "text": seg.get("text", ""),
            "relevance_score": seg.get("relevance_score", 0.0), "reasoning": seg.get("reasoning", ""),
            "virality_score": virality.get("total_score", 0),
            "hook_title": None,  # pass 2 draws the brand title
            "hook_start_time": None, "hook_end_time": None,
        }
        payload["text"] = VideoService._ground_segment_text(payload, transcript_data)
        prepared.append(payload)
    if not args.exact:
        try:
            prepared = VideoService._refine_segment_openings(prepared, transcript_data, args.clip_length)
        except Exception as exc:  # heuristic only; keep the chosen openings
            print(f"opening review skipped: {exc}", file=sys.stderr)
    return prepared


def _keep_range(video_path: Path, segment: Dict[str, Any]) -> tuple:
    """The single source range SupoClip would render for this segment (same snapping and limits)."""
    from src.video_utils import (
        clamp_keep_ranges_to_max_duration,
        extend_keep_ranges_to_sentence_boundary,
        snap_keep_ranges_to_sentence_start,
    )

    ranges = [(layout.parse_time(segment["start_time"]), layout.parse_time(segment["end_time"]))]
    ranges = snap_keep_ranges_to_sentence_start(video_path, ranges)
    ranges = extend_keep_ranges_to_sentence_boundary(video_path, ranges)
    ranges = clamp_keep_ranges_to_max_duration(video_path, ranges)
    if len(ranges) != 1:
        raise RuntimeError(f"layout rendering needs one source range, got {len(ranges)}")
    return ranges[0]


async def _pass1(segments, indexes, video_path, args, pass1_dir: Path, cache: Dict[str, Any], styles) -> None:
    """Pass 1: SupoClip frames "auto" clips; clips with a fill/fit layout are framed by render_layout."""
    from src.services.video_service import VideoService

    def wants_layout(i):
        lay = styles[i - 1]["layout"]
        return layout.needs_layout(lay["mode"], lay["ranges"])

    def remember(i, dest, keep_ranges, duration):
        cache[str(i)] = {
            "pass1": str(dest), "source": str(video_path),
            "keep_ranges": [list(r) for r in keep_ranges], "duration": float(duration),
            "start_time": segments[i - 1]["start_time"], "end_time": segments[i - 1]["end_time"],
            "layout": pipeline.layout_signature(styles[i - 1]),
        }

    auto = [i for i in indexes if not wants_layout(i)]
    custom = [i for i in indexes if wants_layout(i)]

    if auto:
        prepared = _prepare_segments(segments, auto, video_path, args)
        clips = await VideoService.create_video_clips(
            video_path, prepared, output_format="original" if args.original else "vertical",
            add_subtitles=False, max_clip_seconds=args.max_seconds,
        )
        if len(clips) != len(auto):
            sys.exit(f"SupoClip rendered {len(clips)} of {len(auto)} segments (a segment was skipped); "
                     "check the timestamps in segments.json")
        for i, clip in zip(auto, clips):
            dest = pass1_dir / f"{i:02d}.mp4"
            shutil.copy2(clip["path"], dest)
            remember(i, dest, clip["keep_ranges"], clip["duration"])

    if custom:
        prepared = _prepare_segments(segments, custom, video_path, args)
        for i, seg in zip(custom, prepared):
            dest = pass1_dir / f"{i:02d}.mp4"
            keep = _keep_range(video_path, seg)
            info = render_layout.render_layout_clip(video_path, keep, styles[i - 1]["layout"], dest,
                                                    pass1_dir / "work")
            print(f"segment {i}: layout {styles[i - 1]['layout']['mode']}, runs "
                  + ", ".join(f"{k} {a:.1f}-{b:.1f}s" for a, b, k in info["runs"])
                  + f", {info['faces']} face detections", file=sys.stderr)
            remember(i, dest, [keep], info["duration"])
    (pass1_dir / "manifest.json").write_text(json.dumps(cache, indent=2))


def _compose_one(i, seg, st, entry, library, dest: Path, workdir: Path, captions: bool) -> Dict[str, Any]:
    analysis = compose.analyze_clip(entry)
    for word in analysis["unmatched"]:
        print(f"warning: segment {i}: key word {word!r} was not found in the spoken words", file=sys.stderr)
    plan = sounds.plan_mix(st, entry["duration"], analysis["pops"], analysis["shots"], library,
                           i - 1, bool(seg.get("source_music")))
    compose.compose_clip(entry, st, plan, dest, workdir, SOUNDS, captions=captions)
    return {"plan": plan, "analysis": analysis}


async def render(args) -> None:
    job_dir = _job_dir(args.job)
    state = json.loads((job_dir / "state.json").read_text())
    video_path = Path(state["video_path"])
    segments = _load_segments(args.segments)
    brand = _brand()
    disabled = tuple(k for k in pipeline.SOUND_KINDS if getattr(args, f"no_{k}"))
    try:
        styles = pipeline.resolve_all(segments, brand, PROFILES,
                                      allow_brand_override=args.allow_brand_override, disabled=disabled)
        library = sounds.load_library(SOUNDS, ensure=True)
    except (StyleError, SoundError) as exc:
        sys.exit(f"Nothing was rendered. Fix this first:\n{exc}")

    indexes = args.only or list(range(1, len(segments) + 1))
    bad = [i for i in indexes if not 1 <= i <= len(segments)]
    if bad:
        sys.exit(f"segment numbers out of range: {bad} (segments.json has {len(segments)})")

    pass1_dir = job_dir / "pass1"
    (pass1_dir / "work").mkdir(parents=True, exist_ok=True)
    manifest_path = pass1_dir / "manifest.json"
    cache = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if args.recompose:
        pipeline.check_entries(cache, indexes, segments, styles)  # fail before any clip renders
    else:
        await _pass1(segments, indexes, video_path, args, pass1_dir, cache, styles)

    out_dir = OUT / args.job
    out_dir.mkdir(parents=True, exist_ok=True)
    out_manifest = out_dir / "manifest.json"
    previous = json.loads(out_manifest.read_text()) if out_manifest.exists() else []
    captions = not args.no_subtitles
    _, failed = pipeline.compose_all(
        indexes, segments, styles, cache, library, out_dir, pass1_dir / "work",
        lambda i, seg, st, entry, lib, part, work: _compose_one(i, seg, st, entry, lib, part, work, captions),
        previous,
    )
    if failed:
        sys.exit(f"segments failed: {failed}")


async def brand_preview(args) -> None:
    job_dir = _job_dir(args.job)
    state = json.loads((job_dir / "state.json").read_text())
    segments = _load_segments(args.segments or str(job_dir / "segments.json"))
    try:
        styles = pipeline.resolve_all(segments, _brand(), PROFILES, allow_brand_override=args.allow_brand_override)
        library = sounds.load_library(SOUNDS, ensure=True)
    except (StyleError, SoundError) as exc:
        sys.exit(f"Fix this first:\n{exc}")
    n = args.segment
    if not 1 <= n <= len(segments):
        sys.exit(f"segment {n} out of range (segments.json has {len(segments)})")
    pass1_dir = job_dir / "pass1"
    cache = json.loads((pass1_dir / "manifest.json").read_text()) if (pass1_dir / "manifest.json").exists() else {}
    entry = pipeline.entry_for(cache, n, segments[n - 1], styles[n - 1])

    seconds = min(3.0, entry["duration"])
    work = pass1_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    short = work / f"preview-{n:02d}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", entry["pass1"], "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", str(short)], check=True)
    entry = dict(entry, pass1=str(short), duration=seconds,
                 keep_ranges=pipeline.truncate_ranges(entry["keep_ranges"], seconds))
    out = OUT / args.job / f"preview_{n:02d}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    _compose_one(n, segments[n - 1], styles[n - 1], entry, library, out, work, True)
    print(out)


def frames_command(args) -> None:
    """Write a contact sheet so Claude Code can see what is on screen before choosing layouts."""
    job_dir = _job_dir(args.job)
    state = json.loads((job_dir / "state.json").read_text())
    if args.segment:
        segments = _load_segments(args.segments or str(job_dir / "segments.json"))
        if not 1 <= args.segment <= len(segments):
            sys.exit(f"segment {args.segment} out of range (segments.json has {len(segments)})")
        seg = segments[args.segment - 1]
        start, end, name = layout.parse_time(seg["start_time"]), layout.parse_time(seg["end_time"]), f"{args.segment:02d}"
    elif args.start and args.end:
        try:
            start, end, name = layout.parse_time(args.start), layout.parse_time(args.end), "range"
        except ValueError as exc:
            sys.exit(str(exc))
    else:
        sys.exit("give --segment N, or both --from and --to")
    if end <= start or args.every <= 0:
        sys.exit("the time range must be positive and --every must be above 0")
    out = job_dir / f"frames-{name}.png"
    font = FONTS / "Anton-Regular.ttf"
    cmd = layout.frames_args(state["video_path"], start, end - start, args.every, str(out),
                             font=str(font) if font.exists() else None)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit("ffmpeg failed:\n" + "\n".join(proc.stderr.strip().splitlines()[-6:]))
    print(out)
    print(f"one frame every {args.every:g}s from {start:g}s to {end:g}s; labels are source times (H:MM:SS)")


def sounds_command(args) -> None:
    if args.sounds_cmd == "list":
        for e in sounds.load_library(SOUNDS, ensure=True):
            print(f"{e['id']:<16} {e['kind']:<7} {e['license']:<6} {e['source']:<12} {e['file']}")
        return
    if args.file:
        entry = sounds.add_own_file(SOUNDS, Path(args.file), args.kind, args.license, args.author)
        print(f"added {entry['id']} ({entry['license']})")
        return
    if not args.target:
        sys.exit("give a Freesound URL or id, or use --file")
    entry = freesound.fetch_sound(args.target, args.kind, os.environ.get("FREESOUND_API_KEY", ""), SOUNDS)
    print(f"added {entry['id']} ({entry['license']}, by {entry['author']})")


def main() -> None:
    args = pipeline.build_parser().parse_args()
    try:
        if args.cmd == "schema":
            print(pipeline.schema_text())
        elif args.cmd == "profiles":
            print(pipeline.profiles_text(_brand(), PROFILES))
        elif args.cmd == "sounds":
            sounds_command(args)
        elif args.cmd == "frames":
            frames_command(args)
        else:
            asyncio.run({"fetch": fetch, "render": render, "brand-preview": brand_preview}[args.cmd](args))
    except (StyleError, SoundError, pipeline.PipelineError, freesound.FreesoundError, transcribe.TranscribeError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
