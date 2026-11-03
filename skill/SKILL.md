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
   Prints `job=<id>` and the source's `licence=` line.
   **Licence:** before spending a long fetch on a candidate, `clip check <url> [<url> ...]` shows its licence
   and title with no download. Tell the user the licence in one line. A Creative Commons (CC BY) video can be
   reused with credit, and its attribution line is written to `credits.txt` for the post description. A
   standard-licence video needs the creator's permission: say so plainly, then continue if the user decides
   to. Local files are the user's responsibility.
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

Other commands: `clip check` (licence screen), `clip frames` (contact sheet), `clip schema`, `clip profiles`, `clip sounds`,
`clip domains`, `clip sources <domain>` (find candidate videos), `clip package <job>` (upload package per clip). The user's
review page is `__CLIP_DIR__/clip-ui` (local, http://127.0.0.1:8770/).
Render flags: `--only N [N ...]`, `--recompose`, `--exact` (use my timestamps verbatim; default snaps
openings to sentence starts), `--clip-length short|medium|long`, `--max-seconds N`, `--original`
(keep aspect), `--no-subtitles`, `--no-music --no-whoosh --no-pop --no-sting`, and
`--allow-brand-override` (lets a profile or clip style change locked identity fields; never use it
unless the user asks). Output: `__CLIP_DIR__/out/<job>/NN_*.mp4`, `manifest.json`, `credits.txt`.

## Domains

Some content needs more than clip selection. Three domains each have their own skill and a
verification gate that `clip render` enforces: `clip-tech` (tech, AI, startups), `clip-health`
(healthcare) and `clip-mythology` (Hindu mythology in English or Hinglish). When the user names one,
use that skill: it tells you how to choose clips and what to write in each segment's `verification`
object. Fetch with `clip fetch --domain <name> <url>` so the job remembers its domain. A clip whose
record is incomplete is not rendered, the others still are, and `out/<job>/verification.md` shows
what was recorded. `clip domains` lists the packs. Jobs without a domain behave as before.

Any segment can carry an optional `commentary`: one line of your own context, at most 140 characters,
shown as a card after the title.

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

Brand identity (accent colour, headline font, handle) is fixed in `brand.json`, with a per-domain
override in the pack's `brand` block (`domains/<name>.json`), and never changes per clip. You choose how the clip behaves with a profile plus small overrides.

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
  "layout_ranges": [{"from": "00:20", "to": "00:31", "layout": "fill"}],
  "commentary": "One line of your own context",
  "verification": {"speaker": "Jane Doe", "claims_checked": true},
  "title": "Why most founders quit too early", "description": "One or two lines of value.",
  "hashtags": ["#startups", "#founders", "#advice"], "thumbnail_time": 1.5
}]
```
Scores are 0-25 each, total is their sum (0-100). `key_words`, `source_music`, `style`, `layout_ranges`, `commentary` and `verification` are optional (`verification` is required for a job with a domain; its fields are in that domain's skill). `title` (100 characters at most), `description`, `hashtags` (3 to 6, each with `#`) and `thumbnail_time` are needed for `clip package`: write them after the clips render, accurate to the clip, hook first, no promise the clip does not keep. Then run `clip package <job>` and tell the user the folder, and that they review and mark clips in the UI.

## Sounds and licensing

- Whooshes, pops and stings are synthesized by ffmpeg and carry no licence. A built-in placeholder
  pad is the music bed until real tracks are added. It is not good music.
- Add real tracks with `clip sounds add --file <path> --kind music --license <own|CC0|CC-BY> [--author ...]`
  or `clip sounds add <freesound-url-or-id> --kind <kind>` (needs `FREESOUND_API_KEY` in the
  environment; only CC0 and CC-BY are accepted). `clip sounds list` shows the library.
- The user clips other people's videos for a public channel. Music must be cleared for that use. If
  `credits.txt` is not empty, tell the user to paste its lines into the post description.
- The footage belongs to its creators unless the licence says otherwise (see Licence above). For CC BY sources, tell the user to paste `credits.txt` into the description: the source credit is the first line.

## Notes

- First `fetch` downloads the Whisper model (~460 MB for `small`) into `cache/` in this folder. faster-whisper writes shorter transcript lines than openai-whisper (about 1.6x as many), which is fine for choosing cut points.
- Names in captions come from Whisper's spelling and can be wrong.
- Edit `clip.py` and `clipwright/` (bind-mounted, no rebuild) to change behaviour; the backend source
  is the upstream repo cloned by setup.sh into `__CLIP_DIR__/vendor/supoclip/` (AGPL-3.0).
