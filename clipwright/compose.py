"""Pass 2: captions, brand title, handle, progress bar and sound in one ffmpeg run.

Pure builders (caption_template, title_ass, build_ffmpeg_args) need only the stdlib.
analyze_clip and compose_clip import SupoClip lazily, so they only run in the container.
"""

import math
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import sounds, timing
from .style import CAPTION_PX, TITLE_PX

WIDTH, HEIGHT = 1080, 1920
HANDLE_Y = 0.84          # fraction of height; keeps the handle above the bottom 15% safe zone
HANDLE_X = 40
TITLE_SIDE_MARGIN = 60
TITLE_START = 0.1
TITLE_END_MARGIN = 0.3
TITLE_MIN_SECONDS = 0.5
CHAR_WIDTH_EM = 0.46     # average Anton glyph width as a fraction of the font size

# Music ducking while speech is present. Tuned by ear and by the container test.
DUCK_THRESHOLD = 0.05
DUCK_RATIO = 8
DUCK_ATTACK_MS = 20
DUCK_RELEASE_MS = 400
MUSIC_FADE_IN = 0.5
MUSIC_FADE_OUT = 1.0


def ass_color(hex_color: str, alpha: int = 0) -> str:
    r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(seconds: float) -> str:
    cs = int(round(max(0.0, seconds) * 100))
    h, rest = divmod(cs, 360000)
    m, rest = divmod(rest, 6000)
    return f"{h}:{m:02d}:{rest / 100:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def caption_template(style: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    """SupoClip caption template dict from the resolved style. Untouched keys come from ``base``."""
    ident, cap = style["identity"], style["caption"]
    tpl = dict(base)
    tpl.update({
        "font_family": ident["headline_font"],
        "font_size": CAPTION_PX[cap["size"]],
        "font_color": ident["text"],
        "highlight_color": ident["accent"],
        "emphasis_color": ident["accent"],
        "stroke_color": ident["outline"],
        "stroke_width": cap["outline_px"],
        "uppercase": cap["uppercase"],
        "max_words_per_line": cap["words_per_line"],
        "position_y": cap["position_y"],
        "animation": "pop",
        "word_pop": True,
        "word_box": False,
        "background": False,
        "emoji": False,
        "glow": False,
    })
    return tpl


def _balance(words: Sequence[str], lines: int) -> List[str]:
    """Split words into at most ``lines`` lines of similar length."""
    if lines <= 1 or len(words) <= 1:
        return [" ".join(words)]
    target = sum(len(w) for w in words) / lines
    out: List[str] = []
    current: List[str] = []
    for index, word in enumerate(words):
        current.append(word)
        remaining_words = len(words) - index - 1
        if (sum(len(w) for w in current) >= target and len(out) < lines - 1 and remaining_words >= 1):
            out.append(" ".join(current))
            current = []
    if current:
        out.append(" ".join(current))
    return out


def title_ass(text: str, style: Dict[str, Any], duration: float, font_name: str,
              width: int = WIDTH, height: int = HEIGHT) -> str:
    """ASS document with the brand title block (opaque tilted box) and the handle."""
    ident, title = style["identity"], style["title"]
    accent, base_text = ass_color(ident["accent"]), ass_color(ident["text"])
    outline = ass_color(ident["outline"])
    px = TITLE_PX[title["size"]]

    lines: List[str] = []
    if title["enabled"] and text.strip():
        words = _escape(text.strip().upper()).split()
        usable = width - 2 * TITLE_SIDE_MARGIN
        per_line = max(8, int(usable / (px * CHAR_WIDTH_EM)))
        needed = min(title["max_lines"], max(1, math.ceil(len(" ".join(words)) / per_line)))
        lines = _balance(words, needed)
        longest = max(len(line) for line in lines)
        if longest > per_line:
            px = max(28, int(usable / (longest * CHAR_WIDTH_EM)))

    pad = max(8, px // 6)
    top = round(height * title["top"])
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
        "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,"
        "MarginR,MarginV,Encoding\n"
        f"Style: Title,{font_name},{px},{ass_color(title['text_color'])},&H000000FF,{accent},{accent},"
        f"0,0,0,0,100,100,0,0,3,{pad},0,7,{TITLE_SIDE_MARGIN},{TITLE_SIDE_MARGIN},{top},1\n"
        f"Style: Handle,{font_name},34,{base_text},&H000000FF,{outline},&H00000000,"
        f"0,0,0,0,100,100,0,0,1,2,0,1,{HANDLE_X},{HANDLE_X},40,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    events: List[str] = []
    if lines:
        if duration <= 0.8:
            start, end = 0.0, duration
        else:
            start = TITLE_START
            end = min(float(title["seconds"]), max(TITLE_MIN_SECONDS, duration - TITLE_END_MARGIN))
        span = max(0.001, end - start)
        fade_in, fade_out = round(min(0.15, span / 3) * 1000), round(min(0.25, span / 3) * 1000)
        tilt = title["tilt_degrees"]
        tilt_tag = f"\\frz{tilt:g}" if tilt else ""
        events.append(
            f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Title,,0,0,0,,"
            f"{{\\an7\\pos({TITLE_SIDE_MARGIN},{top}){tilt_tag}\\fad({fade_in},{fade_out})}}" + "\\N".join(lines)
        )
    events.append(
        f"Dialogue: 2,{ass_time(0)},{ass_time(duration)},Handle,,0,0,0,,"
        f"{{\\an1\\pos({HANDLE_X},{round(height * HANDLE_Y)})\\alpha&H30&}}{_escape(ident['handle'])}"
    )
    return header + "\n".join(events) + "\n"


def _esc_path(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_ffmpeg_args(
    pass1: Path,
    out: Path,
    ass_files: Sequence[Path],
    style: Dict[str, Any],
    mix: sounds.MixPlan,
    duration: float,
    has_audio: bool,
    fonts_dir: str,
    sounds_dir: Path,
    normalize: bool = True,
    width: int = WIDTH,
) -> List[str]:
    """The single ffmpeg command for pass 2."""
    bar = style["progress_bar"]
    accent = style["identity"]["accent"]
    inputs: List[str] = ["-i", str(pass1)]
    index = 1

    bar_index = None
    if bar["enabled"]:
        inputs += ["-f", "lavfi", "-i", f"color=c=0x{accent[1:]}:s={width}x{bar['height_px']}:d={duration}:r=30"]
        bar_index, index = index, index + 1

    music_index = None
    if mix.music:
        inputs += ["-stream_loop", "-1", "-i", str(Path(sounds_dir) / mix.music["file"])]
        music_index, index = index, index + 1

    event_indexes = []
    for event in mix.events:
        inputs += ["-i", str(Path(sounds_dir) / event.file)]
        event_indexes.append(index)
        index += 1

    graph: List[str] = []
    subs = ",".join(f"subtitles=filename={_esc_path(p)}:fontsdir={_esc_path(fonts_dir)}" for p in ass_files)
    graph.append(f"[0:v]{subs or 'null'}[vs]")
    if bar_index is None:
        graph.append("[vs]null[vout]")
    else:
        height = bar["height_px"]
        graph.append(
            f"[vs]drawbox=x=0:y=ih-{height}:w=iw:h={height}:color=white@{style['progress_bar'].get('track_alpha', 0.25)}:t=fill[vt]"
        )
        graph.append(f"[vt][{bar_index}:v]overlay=x='-w+w*t/{duration}':y=H-h[vout]")

    if has_audio:
        graph.append("[0:a]aresample=48000,aformat=channel_layouts=stereo[voice]")
    else:
        graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={duration}[voice]")

    mix_inputs = ["[voice]"]
    if music_index is not None:
        graph.append("[voice]asplit=2[vmix][vkey]")
        mix_inputs = ["[vmix]"]
        fade_out_at = max(0.0, duration - MUSIC_FADE_OUT)
        graph.append(
            f"[{music_index}:a]atrim=duration={duration},afade=t=in:d={MUSIC_FADE_IN},"
            f"afade=t=out:st={fade_out_at}:d={MUSIC_FADE_OUT},volume={mix.music['gain_db']}dB,"
            "aresample=48000,aformat=channel_layouts=stereo[mus]"
        )
        graph.append(
            f"[mus][vkey]sidechaincompress=threshold={DUCK_THRESHOLD}:ratio={DUCK_RATIO}:"
            f"attack={DUCK_ATTACK_MS}:release={DUCK_RELEASE_MS}[duck]"
        )
        mix_inputs.append("[duck]")
    for n, (event, idx) in enumerate(zip(mix.events, event_indexes)):
        ms = round(event.start * 1000)
        graph.append(
            f"[{idx}:a]aformat=channel_layouts=stereo,aresample=48000,adelay={ms}|{ms},"
            f"volume={event.gain_db}dB[ev{n}]"
        )
        mix_inputs.append(f"[ev{n}]")

    if len(mix_inputs) == 1:
        graph.append(f"{mix_inputs[0]}anull[mixed]")
    else:
        graph.append(
            "".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:normalize=0:duration=first:dropout_transition=0[mixed]"
        )
    target = style["mix"]["target_lufs"]
    if normalize:
        graph.append(f"[mixed]loudnorm=I={target:g}:TP=-3:LRA=11[aout]")
    else:  # tests that measure relative levels need the dynamic gain out of the way
        graph.append("[mixed]anull[aout]")

    return [
        "ffmpeg", "-y", "-v", "error", *inputs,
        "-filter_complex", ";".join(graph),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
        "-t", str(duration), str(out),
    ]


def _has_audio(path: Path) -> bool:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(probe.stdout.strip())


def _video_size(path: Path) -> Tuple[int, int]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    width, height = probe.stdout.strip().split(",")
    return int(width), int(height)


def analyze_clip(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Pop times, shot-change times and unmatched key words for one pass-1 clip.

    ``entry`` is a pass-1 manifest item: source video path, keep_ranges (source seconds),
    key_words. Needs SupoClip, so it runs inside the container.
    """
    from src.media.ffmpeg import output_offsets_for_ranges
    from src.media.transcription import load_cached_transcript_data

    ranges = [(float(a), float(b)) for a, b in entry["keep_ranges"]]
    offsets = output_offsets_for_ranges(ranges)
    words = (load_cached_transcript_data(Path(entry["source"])) or {}).get("words") or []
    matches, unmatched = timing.match_key_words(words, entry.get("key_words") or [], ranges, offsets)
    shots = sounds.detect_shot_changes(Path(entry["source"]), ranges, offsets=offsets)
    return {"pops": sorted(t for t, _ in matches), "shots": shots, "unmatched": unmatched}


def compose_clip(entry: Dict[str, Any], style: Dict[str, Any], mix: sounds.MixPlan, out: Path,
                 workdir: Path, sounds_dir: Path, *, voice: bool = True, captions: bool = True) -> None:
    """Render one clip's pass 2. Raises RuntimeError with ffmpeg's last lines on failure."""
    from src.caption_templates import CAPTION_TEMPLATES
    from src.media.captions import ass_font_name, ass_fonts_dir, build_assemblyai_ass_subtitles

    workdir.mkdir(parents=True, exist_ok=True)
    pass1 = Path(entry["pass1"])
    source = Path(entry["source"])
    ranges = [(float(a), float(b)) for a, b in entry["keep_ranges"]]
    duration = float(entry["duration"])
    ident = style["identity"]
    width, height = _video_size(pass1)

    tpl = caption_template(style, CAPTION_TEMPLATES["default"])
    caption_ass = workdir / f"{pass1.stem}.captions.ass"
    ass_files: List[Path] = []
    built = captions and build_assemblyai_ass_subtitles(
        video_path=source, clip_start=min(a for a, _ in ranges), clip_end=max(b for _, b in ranges),
        video_width=width, video_height=height, output_ass_path=caption_ass,
        font_family=tpl["font_family"], caption_template="default", keep_ranges=ranges,
        hook_title=None, include_captions=True, position_y_override=style["caption"]["position_y"],
        highlight_words=entry.get("key_words") or None, template_override=tpl,
        font_px_override=CAPTION_PX[style["caption"]["size"]],
    )
    if built:
        ass_files.append(caption_ass)

    title_file = workdir / f"{pass1.stem}.title.ass"
    title_file.write_text(title_ass(entry.get("hook_title") or "", style, duration,
                                    ass_font_name(ident["headline_font"]), width, height), encoding="utf-8")
    ass_files.append(title_file)

    fonts_dir = ass_fonts_dir(ident["headline_font"])
    args = build_ffmpeg_args(pass1, out, ass_files, style, mix, duration,
                             voice and _has_audio(pass1), str(fonts_dir), sounds_dir, width=width)
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg compose failed for {pass1.name}:\n{tail}")
