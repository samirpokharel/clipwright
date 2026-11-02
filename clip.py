"""Claude Code driven clipping pipeline (no DB, Redis, frontend or LLM key).

Runs inside the supoclip-backend image, driven by ./clip. See README.md and `clip --help`.

    clip fetch <url|file>            download + transcribe (+ video metadata)
    clip render <job> segments.json  pass 1 (SupoClip cut and frame) then pass 2 (brand + sound)
    clip schema | profiles           what style fields and presets exist
    clip brand-preview <job>         3 second sample from the cached pass 1
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

from clipwright import compose, freesound, pipeline, sounds, style
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


async def fetch(args) -> None:
    from src.media.transcription import load_cached_transcript_data
    from src.services.video_service import VideoService
    from src.youtube_utils import get_youtube_video_id

    source = args.source
    local = Path(source)
    meta: Dict[str, Any] = {}
    if local.exists():
        video_path, job, url = local, local.stem, None
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
    transcript = await VideoService.generate_transcript(Path(video_path), source_url=url)

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


async def _pass1(segments, indexes, video_path, args, pass1_dir: Path, cache: Dict[str, Any]) -> None:
    from src.services.video_service import VideoService

    prepared = _prepare_segments(segments, indexes, video_path, args)
    clips = await VideoService.create_video_clips(
        video_path, prepared, output_format="original" if args.original else "vertical",
        add_subtitles=False, max_clip_seconds=args.max_seconds,
    )
    if len(clips) != len(indexes):
        sys.exit(f"SupoClip rendered {len(clips)} of {len(indexes)} segments (a segment was skipped); "
                 "check the timestamps in segments.json")
    for i, clip in zip(indexes, clips):
        dest = pass1_dir / f"{i:02d}.mp4"
        shutil.copy2(clip["path"], dest)
        cache[str(i)] = {
            "pass1": str(dest), "source": str(video_path),
            "keep_ranges": [list(r) for r in clip["keep_ranges"]], "duration": float(clip["duration"]),
            "start_time": segments[i - 1]["start_time"], "end_time": segments[i - 1]["end_time"],
        }
    (pass1_dir / "manifest.json").write_text(json.dumps(cache, indent=2))


def _entry_for(cache, i, seg) -> Dict[str, Any]:
    entry = cache.get(str(i))
    if not entry or not Path(entry["pass1"]).exists():
        sys.exit(f"no cached pass 1 for segment {i}; run render without --recompose")
    if (entry["start_time"], entry["end_time"]) != (seg["start_time"], seg["end_time"]):
        sys.exit(f"segment {i} start or end time changed since pass 1; run render without --recompose")
    return dict(entry, hook_title=seg.get("hook_title"), key_words=seg.get("key_words") or [])


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
    if not args.recompose:
        await _pass1(segments, indexes, video_path, args, pass1_dir, cache)

    out_dir = OUT / args.job
    out_dir.mkdir(parents=True, exist_ok=True)
    out_manifest = out_dir / "manifest.json"
    old = json.loads(out_manifest.read_text()) if out_manifest.exists() else []
    kept = [m for m in old if int(Path(m["file"]).name[:2]) not in indexes]
    fresh, failed = [], []
    for i in indexes:
        seg, st = segments[i - 1], styles[i - 1]
        entry = _entry_for(cache, i, seg)
        dest = out_dir / pipeline.clip_filename(i, seg)
        part = dest.with_name(dest.stem + ".part.mp4")
        try:
            done = _compose_one(i, seg, st, entry, library, part, pass1_dir / "work", not args.no_subtitles)
        except RuntimeError as exc:
            print(f"segment {i} failed:\n{exc}", file=sys.stderr)
            failed.append(i)
            continue
        pipeline.replace_output(part, dest, i)
        title = (seg.get("hook_title") or "").strip()
        fresh.append({"file": str(dest), "hook_title": title, "duration": entry["duration"],
                      "profile": (seg.get("style") or {}).get("profile"),
                      "credits": sounds.credits([done["plan"]], library)})
        print(f"{dest}  {entry['duration']:.1f}s  {title}")

    manifest = sorted(kept + fresh, key=lambda m: Path(m["file"]).name)
    out_manifest.write_text(json.dumps(manifest, indent=2))
    lines = sorted({line for m in manifest for line in m.get("credits", [])})
    (out_dir / "credits.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
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
    entry = _entry_for(cache, n, segments[n - 1])

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


def sounds_command(args) -> None:
    if args.sounds_cmd == "list":
        for e in sounds.load_library(SOUNDS, ensure=True):
            print(f"{e['id']:<16} {e['kind']:<7} {e['license']:<6} {e['source']:<12} {e['file']}")
        return
    if args.file:
        src = Path(args.file)
        if not src.exists():
            sys.exit(f"file not found: {src}")
        if args.license == "CC-BY" and not args.author:
            sys.exit("CC-BY needs --author")
        folder = "music" if args.kind == "music" else "fx"
        dest = SOUNDS / folder / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        library_path = SOUNDS / "library.json"
        before = library_path.read_text() if library_path.exists() else "[]"
        entry = {"id": f"own-{src.stem}", "kind": args.kind, "file": f"{folder}/{src.name}", "source": "own",
                 "license": args.license, "author": args.author, "url": None}
        library_path.write_text(json.dumps(json.loads(before) + [entry], indent=2) + "\n")
        try:
            sounds.load_library(SOUNDS)
        except SoundError:
            library_path.write_text(before)
            dest.unlink()
            raise
        print(f"added {entry['id']}")
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
        else:
            asyncio.run({"fetch": fetch, "render": render, "brand-preview": brand_preview}[args.cmd](args))
    except (StyleError, SoundError, freesound.FreesoundError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
