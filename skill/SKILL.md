---
name: supoclip
description: Use when the user wants to turn a long video (YouTube URL or local file) into short vertical 9:16 clips with branded captions, title, key-word highlights and a mixed soundtrack, "clip this", "make shorts from", SupoClip, Clipwright. Claude Code picks the segments and the per-video style itself; no API keys.
---

# Clipwright clipping (Claude Code picks the clips and the style)

Pipeline lives in `__CLIP_DIR__/` and runs the SupoClip backend image (`supoclip-backend`) via Docker.
Local Whisper transcribes. YOU choose the segments and the style (replacing SupoClip's LLM step).
Pass 1 (SupoClip) cuts and frames. Pass 2 (Clipwright) adds brand captions, title block, handle,
progress bar and sound. No Docker stack, DB, or API key needed.

## Steps

1. **Docker up?** `docker info` must work. If not, start the Docker daemon and retry.
2. **Fetch + transcribe** (slow on CPU; run in background for videos over ~10 min):
   `__CLIP_DIR__/clip fetch <youtube-url | /work/<file>>`
   Local files must sit under `__CLIP_DIR__/` (mounted as `/work`).
   Env `WHISPER_MODEL_SIZE=base|small|medium` (default `small`) and `WHISPER_BACKEND=auto|faster|openai`
   (default `auto` = faster-whisper, about 2x real time on CPU; `openai` is the slower original).
   Prints `job=<id>`.
   Non-English (e.g. Nepali): Whisper is poor; use `--captions ne` to take YouTube's own
   (auto) captions with word timings instead. Fast and far more accurate. Danda (।) counts
   as a sentence end and captions use complex shaping, so Devanagari renders correctly.
   `TRANSCRIPTION_LANGUAGE=<code>` forces Whisper's language. Timestamps may be plain seconds
   ("87.55") for sub-second cuts with `--exact`.
3. **Read** `__CLIP_DIR__/jobs/<job>/transcript.txt` (lines like `[00:12 - 00:21] text`) and
   `jobs/<job>/state.json` (title, channel, description, categories, tags when available).
4. **Choose clips and a style** for each (rules below). Run `clip profiles` and `clip schema` if you
   need the exact presets and bounds.
5. **Look before choosing a layout:** for every clip run `clip frames <job> --segment N --every 4`
   (needs a draft `segments.json`), then Read the PNG it prints. See "Choosing the layout" below.
6. **Write** `jobs/<job>/segments.json` (schema below).
7. **Render:** `clip render <job> /work/jobs/<job>/segments.json`. An invalid style stops the run
   before anything renders, with the segment number and field.
8. **Verify** before reporting: `ffprobe` one clip (1080x1920, H.264 plus AAC), then view frames at
   about 1.5 s (title) and mid-clip (captions, key-word colour), and confirm the title does not cover
   the speaker's face. For clips with a layout, view one frame inside each fill run and each fit run.
9. **Tweak loop** (do not re-render everything): edit `style` or `key_words` in `segments.json`, then
   `clip render <job> <segments> --recompose --only N` redoes pass 2 for segment N in about half a
   minute. `clip brand-preview <job> --segment N` renders a 3 second sample. Changing a
   segment's `start_time`, `end_time` or layout needs a render without `--recompose` (it tells you).

Other commands: `clip frames` (contact sheet), `clip schema`, `clip profiles`, `clip sounds`.
Render flags: `--only N [N ...]`, `--recompose`, `--exact` (use my start AND end verbatim; default snaps
openings to sentence starts), `--clip-length short|medium|long`, `--max-seconds N`, `--original`
(keep aspect), `--letterbox` (upstream blurred-background layout for "auto" clips; default is a
full-bleed crop tracking the speaker), `--no-subtitles`, `--no-music --no-whoosh --no-pop --no-sting`, and
`--allow-brand-override` (lets a profile or clip style change locked identity fields; never use it
unless the user asks). Output: `__CLIP_DIR__/out/<job>/NN_*.mp4`, `manifest.json`, `credits.txt`.

## Produce from an idea (autopilot, `./post produce`)

When given a brand and an idea (unattended, from `./post produce`, or when the user asks), go from idea
to reviewable clips. Run every command from `__CLIP_DIR__`. Never upload or post: a human approves each
clip on the review page first.

1. **Find sources:** `./post discover "<idea as a search>" "<the science/expert angle>" "<a synonym>"`
   returns ranked JSON (views, duration, channel). Prefer an on-camera expert (a scientist, doctor or
   professor; a TED/TEDx talk; a major podcast or publisher channel) whose talk actually makes the
   idea's point. Skip motivational reupload channels, faceless AI narration, and anything under about
   10k views unless nothing else fits. Before fetching, confirm the point is in the video:
   `yt-dlp --skip-download --write-auto-subs --sub-langs en --sub-format vtt -o "jobs/_subs/%(id)s" <url>`
   and Grep the .vtt for the idea's key words. If no source makes the point, stop and report failed.
2. **Fetch** the best one: `./clip fetch <url>`.
3. **Cut exactly:** find the moment in `jobs/<id>/transcript.txt`, then get word timings with
   `./post words <id> --from <s> --to <s>`. Start on the first word of a self-contained sentence
   that hooks on its own. End just after the last word of the payoff. Use plain seconds ("920.45") with
   `--exact`. Aim for 30-75 s. A clip over 60 s needs `--max-seconds 80`.
4. **Music:** if the transcript shows `[Music]`, or the source is a produced explainer or documentary,
   run `./post strip-music <id>` before rendering. It keeps the voice and drops music that would
   trigger Content ID. Always render with `--no-music`, so the user adds platform-library music.
5. **Layout:** `./clip frames <id> --from <MM:SS> --to <MM:SS> --every 6` and Read the PNG. Put
   `"style": {"profile": "explainer", "layout": {"mode": "fill"}}` for a presenter, and
   `layout_ranges` with `fit` for charts, text cards or slides (see "Choosing the layout").
   The layout mode lives under `style.layout.mode`, not at the top of the segment.
6. **Render:** write `jobs/<id>.segments.json`, then
   `./clip render <id> /work/jobs/<id>.segments.json --exact --no-music --max-seconds 80 --brand <brand>`.
   Output lands in `out/<brand>/<id>/`. Check the printed duration matches your range. View frames
   at about 1 s, mid-clip, and inside every fit range (`ffmpeg -loglevel error -y -ss <t> -i <clip>
   -frames:v 1 -vf scale=360:-1 jobs/_produce/<name>.png`, then Read it). If a frame shows a cropped
   text card, add a fit range and render again.
7. **Write the copy** to `out/<brand>/<id>/<clip name>.post.json` (same name as the .mp4, with
   `.post.json`), then run `./post validate <path>`:
   ```json
   {"brand": "<brand>", "file": "out/<brand>/<id>/<clip>.mp4", "duration": 53.5,
    "source_url": "https://www.youtube.com/watch?v=<id>",
    "credit": "Credit: <channel name>",
    "platforms": {
      "youtube":   {"title": "...", "description": "...", "tags": ["...", "..."]},
      "tiktok":    {"caption": "..."},
      "facebook":  {"caption": "..."},
      "instagram": {"caption": "..."}}}
   ```
   Include only the platforms in `brands/<brand>/accounts.json`. The `credit` string must appear word
   for word in every platform's text (the validator refuses it otherwise). Name the speaker too
   ("🎤 Dr Lila Landowski, neuroscientist").
   - **Hooky but true:** curiosity gaps ("That panic after a mistake? It's your brain getting
     smarter"), a surprising result, a named authority ("Harvard professor"). Every claim must be
     something the clip says. A title the video doesn't deliver makes people swipe away and comment
     "fake", which kills reach.
   - **YouTube:** title max 100 chars with search words early, and 1-2 emojis at most. The description
     opens with a 2-line hook, then a comment question, the speaker and credit lines, and 3-5 hashtags
     ending in `#shorts`. 8-14 tags.
   - **TikTok:** the caption is the title. Put the hook in the first 70 characters (shown before
     "more"), then one line of payoff and the credit, then 4-5 hashtags mixing broad and niche.
   - **Facebook / Instagram:** conversational. Open with a direct "be honest…" or "this study…" line,
     add one line of payoff and a question to drive comments, then the credit and 2-3 hashtags
     (Instagram can take up to 5).
   - Add the brand's `hashtags` from accounts.json.

## Selection rules (from SupoClip's own prompt)

- Pick 3-7 segments for a typical video; roughly 1 per 5 min of source, max 10.
- Each is ONE contiguous range already in the transcript; never merge separate moments.
- 15-60 s (ideal 25-50 s) unless `--clip-length` says otherwise. Needs full setup AND payoff.
- `start_time` = first word of a self-contained sentence (no fillers, bare agreements, or
  references to context outside the clip). `end_time` finishes the last thought; do not include
  the next thought's opening words. `end_time` snaps to the end of its sentence, so end one second
  before the next sentence's first word, or its opening word leaks into the clip.
- Prefer strong hook, emotional charge, concrete value, surprise. Skip intros, sponsor reads,
  CTAs, contextless quotes, repeated points.
- Use only timestamps present in the transcript (MM:SS; HH:MM:SS for long videos).
- `text` is verbatim from the range. No fabrication. Accuracy beats "viral".
- `hook_title`: 3-9 words, plain text, in the transcript's language, grounded in the clip,
  no hashtags/emojis/quotes. It becomes the brand title block.

## Choosing the layout

The picture is a 16:9 frame inside a 9:16 video. Without a choice, SupoClip's own planner decides per
shot from face detection. It misses a presenter who looks down or sits far from the camera, then shows
the whole frame as a thin strip over blur. So you decide, from what is on screen.

1. Run `clip frames <job> --segment N --every 4` and Read the PNG. Labels are source times.
2. Sort each shot:
   - **fill** (full-height portrait crop around the face): a person talking to camera, centred,
     with nothing important at the sides.
   - **fit** (the whole frame over blur): charts, diagrams, slides, tweets, articles, filings, news
     footage, anything with text or a lower-third, two people side by side, wide shots of a room.
3. Set it in `segments.json`:
   - Whole clip is one presenter: `"style": {"layout": {"mode": "fill"}}` (the `interview` profile
     does this by default).
   - Mostly cutaways with the presenter now and then: leave `mode` as `auto` and add
     `"layout_ranges": [{"from": "04:05.5", "to": "04:13.5", "layout": "fill"}]`. Time outside a
     range shows the whole frame.
   - No presenter at all (charts, screen recordings): change nothing. `auto` with no ranges keeps
     SupoClip's planner, which also zooms into text so it stays readable.
4. Range times are source times (as in the transcript), `MM:SS` or `MM:SS.s`. Frames are seconds
   apart, so each boundary snaps to the nearest real shot change within 1 second. If a boundary
   matters, look closer with `clip frames <job> --from 04:04 --to 04:08 --every 0.5`.

Fill keeps only about a third of the frame width. Never fill a shot that has text, a lower-third or
two people. A filled presenter puts his head near the top, so the title can touch his hair for a few
seconds; if it covers a face, use `"title": {"size": "small"}`.

## Choosing the style

Brand identity (accent colour, headline font, handle) is fixed in `brand.json` and never changes per
clip. You choose how the clip behaves with a profile plus small overrides.

**Pick the profile from the video type**, using title, channel, description, categories and tags in
`state.json`, then the transcript. Say which profile you chose and why.

| Profile | Use for | What it does |
|---|---|---|
| `explainer` | Commentary, news, tech, diagrams, screen recordings | 3-word captions, music low, whooshes and pops on |
| `performance` | Music, drumming, live shows | Music bed off, larger 5 s title, light effects |
| `interview` | Podcasts, conversations | 5-word sentence-case captions, no whooshes or pops |
| `tutorial` | How-to, lessons | Large captions, music off, light effects |

**Per-clip adjustments** go in the segment's `style` block, only when the clip needs them, and only
within the bounds `clip schema` prints. Examples:
- Dense, fast speech: `"caption": {"words_per_line": 2}`.
- A clip that is all talking with no visuals: `"sound": {"whoosh": "off"}`.
- A very short clip: `"title": {"seconds": 2}`.

**`key_words`**: 2 to 4 words or short phrases that carry the meaning (a number, a name, the
payoff), spelled as spoken. They are highlighted in the accent colour and trigger a quiet pop. A
word that is not spoken in the clip is reported and ignored.

**`source_music`**: set `true` when the transcript shows the source has music or lyrics under the
speech (song lines, "[Music]"). The music bed is then skipped.

## segments.json

```json
[{
  "start_time": "00:12", "end_time": "00:58",
  "text": "verbatim transcript text of the range",
  "relevance_score": 0.85,
  "reasoning": "why this works as a standalone clip",
  "virality": {"hook_score": 20, "engagement_score": 18, "value_score": 20,
               "shareability_score": 17, "total_score": 75, "hook_type": "question"},
  "hook_title": "Why most founders quit too early",
  "key_words": ["10 million", "quit"],
  "source_music": false,
  "style": {"profile": "explainer", "caption": {"words_per_line": 3}},
  "layout_ranges": [{"from": "00:20", "to": "00:31", "layout": "fill"}]
}]
```
Scores are 0-25 each, total is their sum (0-100). `key_words`, `source_music`, `style` and `layout_ranges` are optional.

## Sounds and licensing

- Whooshes, pops and stings are synthesized by ffmpeg and carry no licence. A built-in placeholder
  pad is the music bed until real tracks are added. It is not good music.
- Add real tracks with `clip sounds add --file <path> --kind music --license <own|CC0|CC-BY> [--author ...]`
  or `clip sounds add <freesound-url-or-id> --kind <kind>` (needs `FREESOUND_API_KEY` in the
  environment; only CC0 and CC-BY are accepted). `clip sounds list` shows the library.
- The user clips other people's videos for a public channel. Music must be cleared for that use. If
  `credits.txt` is not empty, tell the user to paste its lines into the post description.
- The footage belongs to its creators. Remind the user to get permission before posting.

## Notes

- First `fetch` downloads the Whisper model (~460 MB for `small`) into `cache/` in this folder. faster-whisper writes shorter transcript lines than openai-whisper (about 1.6x as many), which is fine for choosing cut points.
- Names in captions come from Whisper's spelling and can be wrong.
- Edit `clip.py` and `clipwright/` (bind-mounted, no rebuild) to change behaviour; the backend source
  is the upstream repo cloned by setup.sh into `__CLIP_DIR__/vendor/supoclip/` (AGPL-3.0).
