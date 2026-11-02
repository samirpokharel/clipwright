---
name: supoclip
description: Use when the user wants to turn a long video (YouTube URL or local file) into short vertical 9:16 clips with subtitles and hook titles, "clip this", "make shorts from", SupoClip. Claude Code picks the segments itself; no API keys.
---

# SupoClip clipping (Claude Code as the selector)

Pipeline lives in `__CLIP_DIR__/` and runs the SupoClip backend image
(`supoclip-backend`) via rootless Docker. Local Whisper transcribes, YOU choose the segments
(replacing SupoClip's LLM step), SupoClip renders (face-centred 9:16 crop, word-synced captions,
hook title). No Docker stack, DB, or API key needed.

## Steps

1. **Docker up?** `docker info` must work. If not, start the Docker daemon
   and retry.
2. **Fetch + transcribe** (slow on CPU; run in background for videos over ~10 min):
   `__CLIP_DIR__/clip fetch <youtube-url | /work/<file>>`
   Local files must sit under `__CLIP_DIR__/` (it is mounted as `/work`).
   Env `WHISPER_MODEL_SIZE=base|small|medium` (default `small`). Prints `job=<id>`.
3. **Read** `__CLIP_DIR__/jobs/<job>/transcript.txt` (lines like
   `[00:12 - 00:21] text`). Select clips yourself using the rules below.
4. **Write** `jobs/<job>/segments.json` (schema below).
5. **Render:** `clip render <job> /work/jobs/<job>/segments.json`
   Flags: `--clip-length short|medium|long`, `--caption-template <name>`, `--no-subtitles`,
   `--original` (keep aspect), `--exact` (use my timestamps verbatim; default lets SupoClip
   snap openings to sentence starts), `--max-seconds N`.
   Output: `__CLIP_DIR__/out/<job>/NN_*.mp4` + `manifest.json`.
6. **Verify** before reporting: `ffprobe` one clip (expect 1080x1920) and view a frame.

## Selection rules (from SupoClip's own prompt)

- Pick 3-7 segments for a typical video; roughly 1 per 5 min of source, max 10.
- Each is ONE contiguous range already in the transcript; never merge separate moments.
- 15-60 s (ideal 25-50 s) unless `--clip-length` says otherwise. Needs full setup AND payoff.
- `start_time` = first word of a self-contained sentence (no fillers, bare agreements, or
  references to context outside the clip). `end_time` finishes the last thought; do not include
  the next thought's opening words.
- Prefer strong hook, emotional charge, concrete value, surprise. Skip intros, sponsor reads,
  CTAs, contextless quotes, repeated points.
- Use only timestamps present in the transcript (MM:SS; HH:MM:SS for long videos).
- `text` is verbatim from the range. No fabrication. Accuracy beats "viral".
- `hook_title`: 3-9 words, plain text, in the transcript's language, grounded in the clip,
  no hashtags/emojis/quotes.

## segments.json

```json
[{
  "start_time": "00:12", "end_time": "00:58",
  "text": "verbatim transcript text of the range",
  "relevance_score": 0.85,
  "reasoning": "why this works as a standalone clip",
  "virality": {"hook_score": 20, "engagement_score": 18, "value_score": 20,
               "shareability_score": 17, "total_score": 75, "hook_type": "question"},
  "hook_title": "Why most founders quit too early"
}]
```
Scores are 0-25 each, total is their sum (0-100).

## Notes

- First `fetch` downloads the Whisper model (~460 MB for `small`) into `supoclip-work/cache/`.
- Edit `clip.py` (bind-mounted, no rebuild) to change behaviour; the backend source is the
  upstream repo cloned by setup.sh into `__CLIP_DIR__/vendor/supoclip/` (AGPL-3.0).
