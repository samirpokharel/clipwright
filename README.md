# clipwright

Turn a long video into short vertical clips with Claude Code as the clip picker. No API keys, no web app, no database.

It wraps the render engine of [SupoClip](https://github.com/FujiwaraChoki/supoclip) (AGPL-3.0) in one Docker container.
Local Whisper transcribes. Claude Code reads the transcript and chooses the segments, which replaces SupoClip's own LLM call.
SupoClip then renders 9:16 clips with face-centred crop, word-synced captions and a hook title.

```
you: "clip this <url>"
  1. clip fetch   yt-dlp download + Whisper transcript        (container)
  2. Claude Code  reads transcript.txt, writes segments.json  (judgement)
  3. clip render  crop, captions, hook title -> out/<id>/*.mp4 (container)
```

## Requirements
- Docker (rootless works), git, about 8 GB free disk
- Claude Code, if you want the "clip this" skill. The scripts also work by hand.
- No GPU needed. Whisper runs on CPU.

## Setup
```bash
git clone https://github.com/polymorphisma/clipwright && cd clipwright
./setup.sh        # builds the backend image from a pinned upstream commit, installs the skill
```

## Use
In Claude Code: `clip this https://www.youtube.com/watch?v=VIDEO_ID`

By hand:
```bash
./clip fetch <youtube-url>                                  # prints job=<id>
# write jobs/<id>/segments.json (format in skill/SKILL.md)
./clip render <id> /work/jobs/<id>/segments.json --exact
```
Local files must live inside this folder (it is mounted as `/work`).
`WHISPER_MODEL_SIZE=base|small|medium` trades speed for accuracy (default `small`).

## Measured run (2026-11-02)
One 15-minute YouTube video on a Ryzen 5 5500U laptop (6 cores, 12 threads, 30 GB RAM, no GPU).

| Stage | Time | Notes |
|---|---|---|
| Download + cap to 1080p | 52 s | 131.5 MB source |
| Whisper `small` transcription | 15 min 41 s | 1.04x real time, 2,327 words, about 640% CPU, 1.8 GB RAM |
| Claude Code picks segments | about 1 min | 277 transcript lines, 17 KB |
| Render 3 clips | 3 min 37 s | 57 s, 47 s and 27 s clips |
| **End to end** | **21 min 2 s** | **1.4x the video length** |

Whisper is about 75% of the total. The three clips are 131 s of the 903 s source, 14.5%, and 40 MB on disk.
Rendering took 1.5x to 1.8x each clip's length, and the first clip includes container startup.
One run on one machine and one video. Treat these as a rough guide, not a benchmark.
Cost: no API fees. It uses your Claude Code usage for the selection step only.

## Limits
- CPU Whisper is the bottleneck. A one-hour video can take over an hour to transcribe.
- Whisper misspells names, and the captions copy the transcript spelling.
- No editor and no accounts. To change a clip, edit `segments.json` and render again.
- The transcript text goes to Claude through your Claude Code session.
- Only tested on YouTube sources. Local files, Twitch and Kick are untested.

## Legal
- Not affiliated with SupoClip or Anthropic. Claude Code and SupoClip are their owners' products.
- `clip.py` imports SupoClip's AGPL-3.0 code at run time, so this repo is licensed AGPL-3.0 too (see LICENSE).
- Clips you make from someone else's video are still their footage. Get permission before posting them.
  Downloading from YouTube may breach its terms. You are responsible for what you clip and publish.
- `out/`, `jobs/`, `tmp/` and `cache/` are git-ignored so downloaded footage never gets committed.
