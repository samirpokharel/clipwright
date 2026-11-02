"""Transcription backends: faster-whisper (default when installed) or SupoClip's openai-whisper.

faster-whisper runs the same Whisper models through CTranslate2 with int8 weights. On the
author's 12-thread CPU, `small` transcribed 5 min 25 s of audio in 161 s (2.0x real time)
against 298 s (0.9x) for openai-whisper, with the same word count (1152 against 1151).

Both backends end as a Whisper-style dict, which SupoClip's own `format_transcript_for_analysis`
and `cache_transcript_data` already accept, so nothing downstream changes.
"""

import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BACKENDS = ("faster", "openai")


class TranscribeError(RuntimeError):
    """A transcription backend is missing or misconfigured."""


def faster_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def pick_backend(requested: Optional[str], faster_ok: bool) -> str:
    """Resolve WHISPER_BACKEND: auto (or unset) uses faster-whisper when it is installed."""
    choice = (requested or "auto").strip().lower()
    if choice == "auto":
        return "faster" if faster_ok else "openai"
    if choice not in BACKENDS:
        raise TranscribeError(f"WHISPER_BACKEND={requested!r} is not one of auto, {', '.join(BACKENDS)}")
    if choice == "faster" and not faster_ok:
        raise TranscribeError("faster-whisper is not installed in this image; run ./setup.sh "
                              "(it builds the clipwright-runtime image) or set WHISPER_BACKEND=openai")
    return choice


def to_whisper_result(segments: Iterable[Any], language: Optional[str]) -> Dict[str, Any]:
    """Whisper-style result dict from faster-whisper segments (a generator is consumed once)."""
    out: List[Dict[str, Any]] = []
    for index, seg in enumerate(segments):
        words = [
            {"word": w.word, "start": float(w.start), "end": float(w.end), "probability": float(w.probability)}
            for w in (seg.words or [])
        ]
        out.append({"id": index, "start": float(seg.start), "end": float(seg.end), "text": seg.text, "words": words})
    return {"text": " ".join(s["text"].strip() for s in out), "language": language, "segments": out}


def decode_command(video: Path) -> List[str]:
    """ffmpeg command that writes the audio as 16 kHz mono float32 PCM to stdout."""
    return ["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]


def transcribe_faster(video: Path, model_size: str = "small", language: Optional[str] = None) -> Dict[str, Any]:
    """Transcribe with word timestamps on CPU (int8). Audio is decoded by ffmpeg, not PyAV."""
    import numpy as np
    from faster_whisper import WhisperModel

    raw = subprocess.run(decode_command(video), capture_output=True)
    if raw.returncode != 0:
        tail = "\n".join(raw.stderr.decode(errors="replace").strip().splitlines()[-4:])
        raise TranscribeError(f"ffmpeg could not decode the audio of {video.name}:\n{tail}")
    audio = np.frombuffer(raw.stdout, dtype=np.float32)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio, word_timestamps=True, language=language or None, vad_filter=False)
    return to_whisper_result(segments, info.language)
