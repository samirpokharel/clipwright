"""Claude Code driven clipping pipeline (no DB, Redis, frontend or LLM key).

Runs inside the supoclip-backend image, driven by ./clip. See README.md and `clip --help`.

    clip fetch <url|file> [--domain D]  download + transcribe (+ video metadata, + domain gate)
    clip check <url> [<url> ...]     licence and title of candidate videos, no download
    clip render <job> segments.json  pass 1 (SupoClip cut and frame) then pass 2 (brand + sound)
    clip domains                     content domains (tech, health, mythology) and their gates
    clip package <job>               upload package per clip: title, description, hashtags, cover images
    clip sources <domain>            find candidate videos for a domain (licence flag, ranked), no download
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

from clipwright import (compose, domains, freesound, gate, layout, licence, pipeline, render_layout, sounds,
                        package, sources, style, tracker, transcribe)
from clipwright.domains import DomainError
from clipwright.sounds import SoundError
from clipwright.style import StyleError

WORK = Path("/work")
JOBS = WORK / "jobs"
OUT = WORK / "out"
SOUNDS = WORK / "sounds"
PROFILES = WORK / "profiles"
DOMAINS = WORK / "domains"
SOURCES = WORK / "sources"
TRACKER = WORK / "tracker" / "state.json"
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
            "license": info.get("license"),  # only Creative Commons videos report one
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

    if args.domain:
        domains.load_pack(args.domain, DOMAINS)  # fail before a long download if the domain is unknown
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
    lic = licence.classify(meta.get("license"), local=url is None)
    state = {"video_path": str(video_path), "source": source, "duration": duration, **meta,
             **({"domain": args.domain} if args.domain else {}),
             "license_kind": lic["kind"], "license_label": lic["label"],
             "attribution": licence.attribution(meta.get("title"), meta.get("channel"), source, lic["kind"])}
    (job_dir / "state.json").write_text(json.dumps(state, indent=2))
    print(f"job={job}")
    if args.domain:
        print(f"domain={args.domain}")
    print(f"video={video_path} duration={duration}s words={len(words)}")
    if meta.get("title"):
        print(f"title={meta['title']} channel={meta.get('channel')}")
    print(f"licence={lic['label']}")
    if licence.warning(lic["kind"]):
        print(f"WARNING: {licence.warning(lic['kind'])}")
    if state["attribution"]:
        print(f"attribution (goes into credits.txt): {state['attribution']}")
    print(f"transcript={job_dir / 'transcript.txt'} ({len(transcript.splitlines())} lines)")


def _prepare_segments(segments, indexes, video_path, args):
    from src.media.transcription import load_cached_transcript_data
    from src.services.video_service import VideoService

    transcript_data = load_cached_transcript_data(video_path)
    prepared = []
    for position, seg in enumerate(segments[i - 1] for i in indexes):
        virality = seg.get("virality") or {}
        payload = {
            "start_time": seg["start_time"], "end_time": seg["end_time"], "text": seg.get("text", ""),
            "relevance_score": seg.get("relevance_score", 0.0), "reasoning": seg.get("reasoning", ""),
            "virality_score": virality.get("total_score", 0),
            "hook_title": None,  # pass 2 draws the brand title
            "hook_start_time": None, "hook_end_time": None,
            "_order": position,  # the opening review may re-sort the list; callers pair it with `indexes`
        }
        payload["text"] = VideoService._ground_segment_text(payload, transcript_data)
        prepared.append(payload)
    if not args.exact:
        try:
            prepared = VideoService._refine_segment_openings(prepared, transcript_data, args.clip_length)
        except Exception as exc:  # heuristic only; keep the chosen openings
            print(f"opening review skipped: {exc}", file=sys.stderr)
    prepared = sorted(prepared, key=lambda p: p.get("_order", 0))
    for payload in prepared:
        payload.pop("_order", None)
    return prepared


def _keep_range(video_path: Path, segment: Dict[str, Any], max_seconds: float = 60.0) -> tuple:
    """The single source range SupoClip would render for this segment (same snapping and limits).

    ``max_seconds`` is the render's --max-seconds, so a layout clip gets the same cap as an auto clip.
    """
    from src.video_utils import (
        clamp_keep_ranges_to_max_duration,
        extend_keep_ranges_to_sentence_boundary,
        snap_keep_ranges_to_sentence_start,
    )

    ranges = [(layout.parse_time(segment["start_time"]), layout.parse_time(segment["end_time"]))]
    ranges = snap_keep_ranges_to_sentence_start(video_path, ranges)
    ranges = extend_keep_ranges_to_sentence_boundary(video_path, ranges)
    ranges = clamp_keep_ranges_to_max_duration(video_path, ranges, max_seconds)
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
            keep = _keep_range(video_path, seg, args.max_seconds)
            info = render_layout.render_layout_clip(video_path, keep, styles[i - 1]["layout"], dest,
                                                    pass1_dir / "work")
            print(f"segment {i}: layout {styles[i - 1]['layout']['mode']}, runs "
                  + ", ".join(f"{k} {a:.1f}-{b:.1f}s" for a, b, k in info["runs"])
                  + f", {info['faces']} face detections", file=sys.stderr)
            remember(i, dest, [keep], info["duration"])
    (pass1_dir / "manifest.json").write_text(json.dumps(cache, indent=2))


def _compose_one(i, seg, st, entry, library, dest: Path, workdir: Path, captions: bool,
                 pack=None) -> Dict[str, Any]:
    analysis = compose.analyze_clip(entry)
    for word in analysis["unmatched"]:
        print(f"warning: segment {i}: key word {word!r} was not found in the spoken words", file=sys.stderr)
    plan = sounds.plan_mix(st, entry["duration"], analysis["pops"], analysis["shots"], library,
                           i - 1, bool(seg.get("source_music")))
    compose.compose_clip(entry, st, plan, dest, workdir, SOUNDS, captions=captions,
                         overlays=gate.overlays_for(pack, seg))
    return {"plan": plan, "analysis": analysis}


async def render(args) -> None:
    job_dir = _job_dir(args.job)
    state = json.loads((job_dir / "state.json").read_text())
    video_path = Path(state["video_path"])
    segments = _load_segments(args.segments)
    pack = domains.load_pack(state["domain"], DOMAINS) if state.get("domain") else None
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

    out_dir = OUT / args.job
    out_dir.mkdir(parents=True, exist_ok=True)
    allowed, blocked = gate.partition(pack, segments, indexes)
    gate_name = f"{pack['name']} gate" if pack else "commentary check"
    for problems in blocked.values():
        for problem in problems:
            print(problem, file=sys.stderr)
    if pack:
        (out_dir / "verification.md").write_text(
            gate.report_markdown(pack, segments, gate.check_all(pack, segments)), encoding="utf-8")
    if not allowed:
        sys.exit(f"Nothing was rendered: every selected clip failed the {gate_name}.")
    indexes = allowed

    pass1_dir = job_dir / "pass1"
    (pass1_dir / "work").mkdir(parents=True, exist_ok=True)
    manifest_path = pass1_dir / "manifest.json"
    cache = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if args.recompose:
        pipeline.check_entries(cache, indexes, segments, styles)  # fail before any clip renders
    else:
        await _pass1(segments, indexes, video_path, args, pass1_dir, cache, styles)

    out_manifest = out_dir / "manifest.json"
    previous = json.loads(out_manifest.read_text()) if out_manifest.exists() else []
    captions = not args.no_subtitles
    extra_credits = [state["attribution"]] if state.get("attribution") else []
    _, failed = pipeline.compose_all(
        indexes, segments, styles, cache, library, out_dir, pass1_dir / "work",
        lambda i, seg, st, entry, lib, part, work: _compose_one(i, seg, st, entry, lib, part, work, captions, pack),
        previous, extra_credits=extra_credits,
    )
    if len(failed) < len(indexes):
        print(f"next: clip package {args.job} (each segment needs title, description and hashtags)")
    problems = []
    if failed:
        problems.append(f"segments failed: {failed}")
    if blocked:
        problems.append(f"segments blocked by the {gate_name}: {sorted(blocked)} (see above)")
    if problems:
        sys.exit("; ".join(problems))


async def brand_preview(args) -> None:
    job_dir = _job_dir(args.job)
    state = json.loads((job_dir / "state.json").read_text())
    segments = _load_segments(args.segments or str(job_dir / "segments.json"))
    pack = domains.load_pack(state["domain"], DOMAINS) if state.get("domain") else None
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
    _compose_one(n, segments[n - 1], styles[n - 1], entry, library, out, work, True, pack)
    print(out)


def check_command(args) -> None:
    """Screen candidate videos: licence, title and length, with no download."""
    for url in args.urls:
        meta = _metadata(url)
        if not meta:
            print(f"{url}\n   could not read the video's metadata")
            continue
        lic = licence.classify(meta.get("license"))
        print(f"{url}\n   {meta.get('title')}  |  {meta.get('channel')}\n   {lic['label']}"
              + ("  ->  reusable with credit" if lic["reuse_ok"] else ""))
        if licence.warning(lic["kind"]):
            print(f"   WARNING: {licence.warning(lic['kind'])}")


def _flat_entries(target: str, count: int) -> List[Dict[str, Any]]:
    """Flat yt-dlp entries (no per-video lookup) for a search or a channel/playlist URL."""
    import yt_dlp

    search = not target.lower().startswith("http")
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True,
            **({} if search else {"playlistend": count})}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{count}:{target}" if search else target, download=False)
    return list(info.get("entries") or [])


class _QuietLogger:
    """Keeps yt-dlp's own error lines out of the output; clip prints one short summary instead."""

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _lookup(url: str):
    """Licence, upload date and follower count of one video, or None if the lookup fails."""
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                               "logger": _QuietLogger()}) as ydl:
            info = ydl.extract_info(url, download=False)
        return {k: info.get(k) for k in ("license", "upload_date", "channel_follower_count")}
    except Exception as exc:  # one video failing must not stop the list
        _LOOKUP_ERRORS.append(str(exc))
        return None


_LOOKUP_ERRORS: List[str] = []


def sources_command(args) -> None:
    """Search YouTube for the domain's queries and watchlist, then write a ranked checklist."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date, datetime

    pack = domains.load_pack(args.domain, DOMAINS)
    rules = pack["sources"]
    found: List[Dict[str, Any]] = []
    for target in list(rules["queries"]) + list(args.query) + list(rules["watchlist"]):
        try:
            entries = _flat_entries(target, rules["per_query"])
        except Exception as exc:  # a failing query is reported, the rest still run
            print(f"search failed for {target!r}: {exc}", file=sys.stderr)
            continue
        found += [c for c in (sources.candidate_from_flat(e) for e in entries) if c]
        print(f"searched {target!r}: {len(entries)} results", file=sys.stderr)

    seen = {p.name for p in JOBS.iterdir()} if JOBS.exists() else set()
    try:
        seen |= tracker.rejected_ids(tracker.load(TRACKER))
    except tracker.TrackerError as exc:
        print(f"tracker ignored: {exc}", file=sys.stderr)
    shortlist = sources.select_for_enrichment(sources.prefilter(found, rules, seen, rules["watchlist"]), args.limit)
    print(f"looking up the licence of {len(shortlist)} candidates...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=4) as pool:
        infos = list(pool.map(lambda c: _lookup(c["url"]), shortlist))
    if _LOOKUP_ERRORS:
        blocked = sum("not a bot" in e for e in _LOOKUP_ERRORS)
        print(f"WARNING: the licence lookup failed for {len(_LOOKUP_ERRORS)} of {len(shortlist)} videos"
              + (f" ({blocked} blocked by YouTube's bot check)" if blocked else "")
              + ". They are listed as 'Licence not checked'; check them yourself before you rely on them.",
              file=sys.stderr)
    today = date.today()
    ranked = sources.rank(sources.postfilter([sources.enrich(c, i, today) for c, i in zip(shortlist, infos)], rules))

    SOURCES.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    (SOURCES / f"{args.domain}.json").write_text(sources.to_json(ranked), encoding="utf-8")
    (SOURCES / f"{args.domain}.md").write_text(sources.to_markdown(args.domain, ranked, stamp), encoding="utf-8")
    print(f"{len(ranked)} candidates for {args.domain}: {SOURCES / (args.domain + '.md')}")
    for c in ranked[:5]:
        tag = "CC BY" if c["license_kind"] == "cc-by" else c["license_kind"]
        views = f"{c['views']:,}" if c.get("views") is not None else "?"
        print(f"  [{tag}] {c['title'][:70]} | {c['channel']} | {views} views")


def package_command(args) -> None:
    """Build out/<job>/upload/NN_slug/ for every rendered clip: video, cover candidates, post text."""
    job_dir = _job_dir(args.job)
    state = json.loads((job_dir / "state.json").read_text())
    segments = _load_segments(args.segments or str(job_dir / "segments.json"))
    pack = domains.load_pack(state["domain"], DOMAINS) if state.get("domain") else None
    out_dir = OUT / args.job
    if not (out_dir / "manifest.json").exists():
        sys.exit(f"nothing rendered for {args.job} yet: run clip render first")
    manifest = json.loads((out_dir / "manifest.json").read_text())
    edits_path = job_dir / "post_edits.json"
    edits = json.loads(edits_path.read_text(encoding="utf-8")) if edits_path.exists() else {}
    upload = out_dir / "upload"
    made, skipped = [], []
    for entry in manifest:
        n = int(Path(entry["file"]).name[:2])
        if not 1 <= n <= len(segments):
            print(f"segment {n}: not in segments.json, skipped", file=sys.stderr)
            skipped.append(n)
            continue
        merged = package.merge_edits(segments[n - 1], edits.get(str(n)))
        problems = package.check_post(merged, n)
        if problems:
            for problem in problems:
                print(problem, file=sys.stderr)
            skipped.append(n)
            continue
        post = package.build_post(merged, state=state, pack=pack, credits=entry.get("credits", []))
        folder = upload / package.slug(post["title"], n)
        try:
            for old in upload.glob(f"{n:02d}_*"):  # the title changed: drop the old folder of this clip
                if old != folder:
                    shutil.rmtree(old)
            package.write_clip_package(folder, Path(entry["file"]), post,
                                       package.cover_times(float(entry["duration"]), merged.get("thumbnail_time")),
                                       merged.get("cover", "a"))
        except (OSError, subprocess.CalledProcessError) as exc:  # a missing video or a failed frame grab
            print(f"segment {n}: could not package ({type(exc).__name__}: {exc})", file=sys.stderr)
            shutil.rmtree(folder, ignore_errors=True)  # no half-built folder that looks like a package
            skipped.append(n)
            continue
        made.append((n, post["title"], folder))
        print(f"{folder}  {post['title']}")
    if made:
        lic = licence.classify(state.get("license"), local=not str(state.get("source", "")).startswith("http"))
        lines = [f"# Upload package: {args.job}", "",
                 f"Source: {state.get('title') or args.job} ({state.get('source')})", f"Licence: {state.get('license_label') or lic['label']}"]
        if licence.warning(state.get("license_kind") or lic["kind"]):
            lines.append(f"Check before posting: {licence.warning(state.get('license_kind') or lic['kind'])}")
        lines += ["", "Clips in order. Each folder has video.mp4, cover.jpg (and cover_a/b/c.jpg to choose from), post.txt and post.json.", ""]
        lines += [f"{n}. {folder.name}: {title}" for n, title, folder in made]
        (upload / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if skipped:
        sys.exit(f"packaged {len(made)} clips; skipped segments {skipped} (fix the problems above)")


def domains_command(args) -> None:
    """List the content domains and what each one's gate requires."""
    for name in domains.list_packs(DOMAINS):
        pack = domains.load_pack(name, DOMAINS)
        ver, ov = pack["verification"], pack["overlays"]
        need = ver["text"] + [f"{k} (true)" for k in ver["true"]] + [f"{k} (inside the clip)" for k in ver["time_inside"]]
        print(f"{name}: {pack['description']}")
        print(f"   clips {pack['clip_seconds']['min']}-{pack['clip_seconds']['max']}s; verification: {', '.join(need) or 'none'}")
        extras = [f"flags: {', '.join(ver['flags'])}"] if ver["flags"] else []
        if ov["speaker"]:
            extras.append("speaker line on screen")
        if ov["disclaimer"]:
            extras.append(f"disclaimer: {ov['disclaimer']}")
        if extras:
            print(f"   {'; '.join(extras)}")


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
        elif args.cmd == "package":
            package_command(args)
        elif args.cmd == "sources":
            sources_command(args)
        elif args.cmd == "domains":
            domains_command(args)
        elif args.cmd == "frames":
            frames_command(args)
        elif args.cmd == "check":
            check_command(args)
        else:
            asyncio.run({"fetch": fetch, "render": render, "brand-preview": brand_preview}[args.cmd](args))
    except (StyleError, SoundError, DomainError, pipeline.PipelineError, freesound.FreesoundError, transcribe.TranscribeError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
