# clipwright

Turn a long video into short vertical clips with Claude Code as the clip picker. No API keys, no web app, no database.

It wraps the render engine of [SupoClip](https://github.com/FujiwaraChoki/supoclip) (AGPL-3.0) in one Docker container.
Local Whisper transcribes. Claude Code reads the transcript, chooses the segments and the style, which replaces SupoClip's own LLM call.
Pass 1 (SupoClip) cuts and frames each clip. Pass 2 (Clipwright) adds your brand look and a mixed soundtrack.

```
you: "clip this <url>"
  1. clip fetch    yt-dlp download + Whisper transcript + video metadata     (container)
  2. Claude Code   reads transcript and metadata, writes segments.json       (judgement)
                   per clip: key words, a profile, small style overrides
  3. pass 1        SupoClip: cut, sentence snapping, 9:16 framing            (container)
  4. pass 2        captions, title block, handle, progress bar, sound        (container)
                   -> out/<id>/*.mp4, manifest.json, credits.txt
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

### Commands
| Command | What it does |
|---|---|
| `clip fetch <url\|file>` | Download, transcribe, save `transcript.txt` and `state.json` (with title, channel, description, tags when available). |
| `clip render <job> <segments.json>` | Pass 1 then pass 2. Flags: `--only N [N ...]`, `--recompose`, `--exact`, `--clip-length`, `--max-seconds`, `--original`, `--no-subtitles`, `--no-music/--no-whoosh/--no-pop/--no-sting`, `--allow-brand-override`. |
| `clip render ... --recompose` | Reuse the cached pass 1 and redo only pass 2. Use it to try style and sound changes. |
| `clip brand-preview <job> [--segment N]` | Render a 3 second sample into `out/<job>/preview_NN.mp4`. |
| `clip frames <job> --segment N [--every 4]` | Contact sheet of a segment (or `--from/--to`), one labelled frame every few seconds. Used to choose layouts from what is on screen. |
| `clip schema` | Print every style field and its bounds as JSON. |
| `clip profiles` | List the profiles with their resolved values. |
| `clip sounds add\|list` | Manage the sound library. |

An invalid style stops the run before anything renders and names the segment and field.

## Brand and style
Style is resolved in three layers, later layers winning: **`brand.json`** (identity and base style), then a **profile** in `profiles/`, then the **`style` block** of a segment.

- **`brand.json`** holds `handle`, `accent`, `text`, `outline`, `headline_font` (the identity) plus the base caption, title, progress bar and sound settings and the mix levels. It ships with placeholders (`@yourchannel`, yellow, Anton). Edit it for your channel. Fonts come from the image's 24 bundled fonts.
- **Locked identity.** Profiles and clip styles cannot change `handle`, `accent`, `text`, `outline`, `headline_font` or `title.text_color`. `--allow-brand-override` lifts that for one run.
- **Profiles** are partial styles by video type: `explainer` (commentary, diagrams), `performance` (music, no music bed), `interview` (calm captions, few effects), `tutorial` (large text, few effects). Add your own as `profiles/<name>.json` with `description` and `style`.
- **Per-clip `style`** adjusts within bounds, for example `{"profile": "explainer", "caption": {"words_per_line": 2}, "sound": {"music": "off"}}`. Run `clip schema` for all fields.
- **`key_words`** per segment are highlighted in the accent colour and trigger a quiet pop. **`source_music: true`** skips the music bed when the source already has music.

## Layout
A 16:9 source in a 9:16 video is either **filled** (a full-height portrait crop around the speaker) or **fitted** (the whole frame over a blurred copy). `layout.mode` is `auto`, `fill` or `fit` per clip, and a segment's `layout_ranges` mix them over time, for example `[{"from": "04:05.5", "to": "04:13.5", "layout": "fill"}]`.

- **Why you decide:** SupoClip's own planner (`auto` with no ranges) chooses from face detection. On a wide presenter shot it found a face in only 18% of frames (it needs 25%), so it showed a thin strip. Claude Code looks at `clip frames` contact sheets instead: presenter to camera fills, charts, text, news and two-person shots fit.
- **Boundaries** snap to the nearest real shot change within 1 second, so rough times are enough.
- **How it renders:** clips with a fill or fit layout are framed by Clipwright's own ffmpeg step, using SupoClip's face tracker only to place the crop. `auto` clips go through SupoClip unchanged. Changing a clip's layout needs a full render, not `--recompose`, and the tool tells you.
- **Trade-off:** fill keeps about a third of the frame width, and the title block can touch a presenter's hair for a few seconds.

## Sound
Per clip, as each sound's level (`off`, `low`, `normal`) allows: a music bed that ducks under speech, a whoosh on shot changes (at most one per 4 s), pops on key words (at most 3), an intro sting and an outro tone. The final mix is normalised to about -14 LUFS (measured -14.4 to -15.4 on 7 clips) with a -3 dB true-peak ceiling, so encoded peaks stay below -2 dBFS.

- **Built in:** whoosh, pop, sting and outro are synthesized by ffmpeg, so they carry no licence. A placeholder ambient pad is the music bed until you add tracks. It is not good music.
- **Your own files:** `clip sounds add --file <path> --kind music --license own` (or `CC0`, or `CC-BY --author NAME`).
- **Freesound:** `clip sounds add <url-or-id> --kind <kind>` with `FREESOUND_API_KEY` set. Only CC0 and CC-BY are accepted, and a refused licence writes nothing. The Freesound field names are from their public docs and have not been checked against a live response. Freesound's API terms say commercial use of the API is negotiated with them, so use it for occasional curation and read [their terms](https://freesound.org/help/tos_api).
- **Credits:** CC-BY authors used in any clip are written to `out/<id>/credits.txt`. Paste them into the post description.

## Measured runs (2026-11-02)
Hardware: Ryzen 5 5500U laptop (6 cores, 12 threads, 30 GB RAM, no GPU). One run each, so treat these as a rough guide.

Fetch and transcribe, 15 minute video:

| Stage | Time | Notes |
|---|---|---|
| Download + cap to 1080p | 52 s | 131.5 MB source |
| Whisper `small` transcription | 15 min 41 s | 1.04x real time, about 640% CPU, 1.8 GB RAM |

Whisper is the bottleneck. A 5 minute video transcribed at 0.92x real time.

Stage 1 render, one 18 second clip:

| Step | Time |
|---|---|
| Full render (pass 1 and pass 2) | 62 s |
| `--recompose` (pass 2 only) | 34.5 s |
| `brand-preview` (3 second sample) | 19 s |

Cost: no API fees. It uses your Claude Code usage for the selection step only.

## Tests
```bash
python3 -m unittest discover -s tests -t .   # host: style, timing, sounds, compose arguments, CLI, ducking
bash tests/container.sh                       # in the image: real pass 1 then pass 2 on the cached test job
```
The container test needs the cached job `jNQXAC9IVRw` (fetch `https://www.youtube.com/watch?v=jNQXAC9IVRw` once).

## Limits
- CPU Whisper is the bottleneck. A one-hour video can take over an hour to transcribe.
- Whisper misspells names, and the captions copy the transcript spelling.
- No editor and no accounts. To change a clip, edit `segments.json` and run `clip render --recompose`.
- The transcript text and extracted frames go to Claude through your Claude Code session.
- Only tested on YouTube sources. Local files, Twitch and Kick are untested.
- Loudness (-14 LUFS) and the bottom safe zone (15%) are common short-form practice, not checked against each platform's current guidance.

## Legal
- Not affiliated with SupoClip or Anthropic. Claude Code and SupoClip are their owners' products.
- `clip.py` imports SupoClip's AGPL-3.0 code at run time, so this repo is licensed AGPL-3.0 too (see LICENSE).
- Clips you make from someone else's video are still their footage. Get permission before posting them.
  Downloading from YouTube may breach its terms. You are responsible for what you clip and publish.
- Music is your responsibility: the tools record licences and refuse the wrong ones, but do not decide fair use or platform policy.
- `out/`, `jobs/`, `tmp/`, `cache/` and `sounds/` are git-ignored so downloaded footage and audio never get committed.
