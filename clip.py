"""Claude Code driven SupoClip pipeline (no DB, Redis, frontend or LLM key).

Runs inside the supoclip-backend image, driven by ./clip:

    clip fetch <youtube-url|/work/file.mp4>   download + transcribe -> transcript.txt
    clip render <job> segments.json           render 9:16 clips into out/<job>/

Claude Code does the segment selection between the two steps.
"""

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

WORK = Path("/work")
JOBS = WORK / "jobs"
OUT = WORK / "out"


def _job_dir(job: str) -> Path:
    return JOBS / job


async def fetch(args) -> None:
    from src.media.transcription import load_cached_transcript_data
    from src.services.video_service import VideoService
    from src.youtube_utils import get_youtube_video_id

    source = args.source
    local = Path(source)
    if local.exists():
        video_path = local
        job = local.stem
        url = None
    else:
        video_id = get_youtube_video_id(source)
        if not video_id:
            sys.exit(f"Not a YouTube URL or existing file: {source}")
        job = video_id
        url = source
        video_path = await VideoService.download_video(source)
        if not video_path:
            sys.exit("Download failed")

    video_path = await VideoService.prepare_source(Path(video_path))
    transcript = await VideoService.generate_transcript(Path(video_path), source_url=url)

    job_dir = _job_dir(job)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    words = (load_cached_transcript_data(Path(video_path)) or {}).get("words") or []
    duration = VideoService._get_file_duration(Path(video_path))
    (job_dir / "state.json").write_text(
        json.dumps({"video_path": str(video_path), "source": source, "duration": duration})
    )
    print(f"job={job}")
    print(f"video={video_path} duration={duration}s words={len(words)}")
    print(f"transcript={job_dir / 'transcript.txt'} ({len(transcript.splitlines())} lines)")


async def render(args) -> None:
    from src.media.transcription import load_cached_transcript_data
    from src.services.video_service import VideoService

    job_dir = _job_dir(args.job)
    state = json.loads((job_dir / "state.json").read_text())
    video_path = Path(state["video_path"])
    segments = json.loads(Path(args.segments).read_text())
    if isinstance(segments, dict):
        segments = segments.get("most_relevant_segments") or segments.get("segments") or []

    transcript_data = load_cached_transcript_data(video_path)
    prepared = []
    for seg in segments:
        virality = seg.get("virality") or {}
        payload = {
            "start_time": seg["start_time"],
            "end_time": seg["end_time"],
            "text": seg.get("text", ""),
            "relevance_score": seg.get("relevance_score", 0.0),
            "reasoning": seg.get("reasoning", ""),
            "virality_score": virality.get("total_score", 0),
            "hook_title": seg.get("hook_title"),
            "hook_start_time": seg.get("hook_start_time"),
            "hook_end_time": seg.get("hook_end_time"),
        }
        payload["text"] = VideoService._ground_segment_text(payload, transcript_data)
        prepared.append(payload)

    if not args.exact:
        try:
            prepared = VideoService._refine_segment_openings(
                prepared, transcript_data, args.clip_length
            )
        except Exception as exc:  # heuristic only; keep the chosen openings
            print(f"opening review skipped: {exc}", file=sys.stderr)

    clips = await VideoService.create_video_clips(
        video_path,
        prepared,
        caption_template=args.caption_template,
        output_format="original" if args.original else "vertical",
        add_subtitles=not args.no_subtitles,
        max_clip_seconds=args.max_seconds,
    )

    out_dir = OUT / args.job
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, clip in enumerate(clips, 1):
        src = Path(clip["path"])
        title = (clip.get("hook_title") or "").strip()
        dest = out_dir / f"{i:02d}_{src.name}"
        shutil.copy2(src, dest)
        manifest.append({"file": str(dest), "hook_title": title, "duration": clip.get("duration")})
        print(f"{dest}  {clip.get('duration')}s  {title}")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("source")
    r = sub.add_parser("render")
    r.add_argument("job")
    r.add_argument("segments")
    r.add_argument("--caption-template", default="default")
    r.add_argument("--clip-length", default="auto", choices=["auto", "short", "medium", "long"])
    r.add_argument("--max-seconds", type=float, default=60.0)
    r.add_argument("--no-subtitles", action="store_true")
    r.add_argument("--original", action="store_true", help="keep source aspect ratio")
    r.add_argument("--exact", action="store_true", help="skip opening refinement; use my timestamps")
    args = p.parse_args()
    asyncio.run({"fetch": fetch, "render": render}[args.cmd](args))


if __name__ == "__main__":
    main()
