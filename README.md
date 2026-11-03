# clipwright

Turn a long video into short vertical clips with Claude Code as the clip picker. No API keys, no hosted service, no database.

It wraps the render engine of [SupoClip](https://github.com/FujiwaraChoki/supoclip) (AGPL-3.0) in one Docker container.
Local Whisper transcribes. Claude Code reads the transcript, chooses the segments and the style, which replaces SupoClip's own LLM call.
Pass 1 (SupoClip) cuts and frames each clip. Pass 2 (Clipwright) adds your brand look and a mixed soundtrack.

```
you: "clip this <url>"
  1. clip fetch    yt-dlp download + faster-whisper transcript + metadata    (container)
  2. Claude Code   reads transcript and metadata, writes segments.json       (judgement)
                   per clip: key words, a profile, small style overrides
  3. pass 1        SupoClip: cut, sentence snapping, 9:16 framing            (container)
  4. pass 2        captions, title block, handle, progress bar, sound        (container)
                   -> out/<id>/*.mp4, manifest.json, credits.txt
  5. clip package  title, description, hashtags, cover images per clip      (container)
```

Around that core: three **domains** (tech, health, mythology) with a verification gate, `clip sources` to find candidate videos, and a **local review UI** (`./clip-ui`) to verify sources and clips and track their status.

## Requirements
- Docker (rootless works), git, about 8 GB free disk
- Claude Code, if you want the "clip this" skill. The scripts also work by hand.
- No GPU needed. Whisper runs on CPU.

## Setup
```bash
git clone https://github.com/polymorphisma/clipwright && cd clipwright
./setup.sh        # builds the backend image from a pinned upstream commit, adds faster-whisper
                  # (the clipwright-runtime image), installs the skill
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
`WHISPER_MODEL_SIZE=base|small|medium` trades speed for accuracy (default `small`). `WHISPER_BACKEND=auto|faster|openai` picks the transcriber: `auto` (the default) uses faster-whisper, and `openai` falls back to SupoClip's original openai-whisper. The first run downloads the model (about 460 MB for `small`) into `cache/`.

### Commands
| Command | What it does |
|---|---|
| `clip check <url> [<url> ...]` | Read each video's licence and title without downloading. Creative Commons (CC BY) is reusable with credit, anything else needs the creator's permission. |
| `clip fetch <url\|file> [--domain D]` | Download, transcribe, save `transcript.txt` and `state.json` (with title, channel, description, tags when available). `--domain` stores the content domain so `render` applies its verification gate. |
| `clip domains` | List the domains (tech, health, mythology) and what each one's gate requires. |
| `clip sources <domain> [--query Q] [--limit N]` | Find candidate videos for a domain, no download. Writes `sources/<domain>.md` and `.json`. |
| `clip package <job>` | Build `out/<job>/upload/NN_slug/` per clip: `video.mp4`, `cover.jpg` plus three candidates, `post.txt`, `post.json`. |
| `clip render <job> <segments.json>` | Pass 1 then pass 2. Flags: `--only N [N ...]`, `--recompose`, `--exact`, `--clip-length`, `--max-seconds`, `--original`, `--no-subtitles`, `--no-music/--no-whoosh/--no-pop/--no-sting`, `--allow-brand-override`. |
| `clip render ... --recompose` | Reuse the cached pass 1 and redo only pass 2. Use it to try style and sound changes. |
| `clip brand-preview <job> [--segment N]` | Render a 3 second sample into `out/<job>/preview_NN.mp4`. |
| `clip frames <job> --segment N [--every 4]` | Contact sheet of a segment (or `--from/--to`), one labelled frame every few seconds. Used to choose layouts from what is on screen. |
| `clip schema` | Print every style field and its bounds as JSON. |
| `clip profiles` | List the profiles with their resolved values. |
| `clip sounds add\|list` | Manage the sound library. |

An invalid style stops the run before anything renders and names the segment and field.

## Source licence
YouTube reports a licence only for Creative Commons videos (`Creative Commons Attribution license (reuse allowed)`). Every other video comes back with none, which means the standard licence: all rights stay with the creator. `clip check` and `clip fetch` print the result and warn when reuse needs permission. For a CC BY source, the attribution line (`"Title" by Channel, URL, licensed under Creative Commons Attribution (CC BY)`) is written first in `out/<id>/credits.txt` on every render, so paste `credits.txt` into the post description. Only plain CC BY counts as reusable: other Creative Commons variants (NonCommercial and so on) are flagged to read, and a local file is your responsibility. This is a screen, not legal advice, and it does not know whether a creator has given you permission some other way.

## Domains and the verification gate
A domain is a pack in `domains/<name>.json` plus a skill (`skill/domains/<name>/SKILL.md`, installed as `clip-<name>`): `tech` (tech, AI, startups), `health` (healthcare) and `mythology` (Hindu mythology in English or Hinglish). `clip fetch --domain health <url>` stores the domain with the job. A pack may carry a `brand` block with any of the identity fields (`handle`, `accent`, `text`, `outline`, `headline_font`); it is laid over `brand.json` for every render of that domain, so each domain can be its own channel. The shipped packs set the handles `@shlokaclips` (mythology), `@gradientcuts` (tech) and `@vagusclips` (health). Claude writes a `verification` object on every segment, and **`clip render` refuses to render a clip whose record is incomplete**: the other clips still render, the command exits non-zero and says why, and `out/<job>/verification.md` lists every clip with its record.

| Domain | Clip length | The record must show | On screen |
|---|---|---|---|
| `health` | 30 to 90 s | `speaker`, `credential`, `context_excerpt`, `context_checked: true`, `framing_time` inside the clip (the question that frames the answer); `risk_flags` are recorded, not blocking | speaker and credential, disclaimer "General information, not medical advice." |
| `tech` | 15 to 60 s | `speaker`, `claims_checked: true`; `dated_claims` recorded | nothing extra |
| `mythology` | 20 to 75 s | `source_text`, `variant_note`, `verses_checked: true`, `respect_check: true` | nothing extra |

Any segment may also carry an optional `commentary` (140 characters at most): one line of your own context, shown as a card in the title slot after the title ends. The gate checks that the record is complete and, where it can, that it holds (clip length, framing moment). It cannot judge whether a claim is true. It records what Claude says it checked, for you to audit. Jobs without a domain render as before.

## Finding sources
`clip sources <domain>` searches YouTube with the pack's queries (and any `--query` you add, and the pack's `watchlist` of channels), drops videos already fetched or rejected, short or unpopular ones, looks up each remaining candidate's licence and upload date, and ranks them: CC BY first, then watchlist channels, then by views. Nothing is downloaded and no API key is needed. It lists what YouTube search returns, which is not necessarily the best material, and it cannot know whether you have permission: you check that, then approve in the UI or tell Claude which URLs to clip.

## Upload package
Claude writes `title` (100 characters at most), `description`, `hashtags` (3 to 6, each starting with `#`) and optionally `thumbnail_time` on each segment. `clip package <job>` validates them, appends the source credit (or the CC BY attribution line), the sound credits and the domain disclaimer to the description, and writes per clip a folder with the video, three cover candidates (the first at `thumbnail_time`, default 1.5 s, where the brand title is on screen; the others 40 % and 75 % through), the chosen `cover.jpg`, `post.txt` (title, description, a short caption for TikTok and Reels) and `post.json`. A clip with a problem is skipped with a message and the others are still packaged. Platform limits differ and are not verified here, so the limits used are conservative. Whether a platform accepts a custom cover for a Short is also unverified.

## Review UI
```bash
./clip-ui            # http://127.0.0.1:8770/  (needs uv; dependencies are declared inline)
```
A local page, bound to `127.0.0.1`, with no login. **Sources**: pick a domain, press Search, preview each video, set the permission (unchecked, asked, granted, cc), add a note, approve or reject, and copy the fetch commands for the approved ones. **Clips**: play each rendered clip, see its verification record and gate problems, edit title, description and hashtags, choose a cover, mark it OK or Needs fix, and build the upload package (only when every clip of the job is marked OK). Status (found, approved, fetched, clipped, verified, posted) is kept in `tracker/state.json` and follows the files on disk. Edits go to `jobs/<job>/post_edits.json`. Searching and packaging run `./clip`, so Docker must be up. Fetching and rendering stay on the command line (or in Claude Code).

## Brand and style
Style is resolved in three layers, later layers winning: **`brand.json`** (identity and base style), then a **profile** in `profiles/`, then the **`style` block** of a segment.

- **`brand.json`** holds `handle`, `accent`, `text`, `outline`, `headline_font` (the identity) plus the base caption, title, progress bar and sound settings and the mix levels. It ships with placeholders (`@yourchannel`, yellow, Anton). Edit it for your channel, or set per-domain identity in the pack's `brand` block (see Domains). Fonts come from the image's 24 bundled fonts.
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
- **Your own files:** `clip sounds add --file <path> --kind music --license own` (or `CC0`, or `CC-BY --author NAME`). A licence is required, and the path must be inside this folder (the container sees it as `/work/...`). Adding a name that already exists is refused.
- **Freesound:** `clip sounds add <url-or-id> --kind <kind>` with `FREESOUND_API_KEY` set. Only CC0 and CC-BY are accepted, and a refused licence writes nothing. The Freesound field names are from their public docs and have not been checked against a live response. Freesound's API terms say commercial use of the API is negotiated with them, so use it for occasional curation and read [their terms](https://freesound.org/help/tos_api).
- **Credits:** CC-BY authors used in any clip are written to `out/<id>/credits.txt`. Paste them into the post description.

## Measured runs (2026-11-02)
Hardware: Ryzen 5 5500U laptop (6 cores, 12 threads, 30 GB RAM, no GPU). One run each, so treat these as a rough guide.

Transcription, 5 min 25 s of audio (same laptop, `small` model):

| Backend | Time | Speed | Words |
|---|---|---|---|
| openai-whisper (`WHISPER_BACKEND=openai`) | 298 s | 0.92x real time | 1151 |
| faster-whisper int8 (the default) | 161 s | 2.02x real time | 1152 |

The whole `clip fetch` of a local copy of that video (no download) took 164 s and produced 1153 words. For comparison, the first fetch of a 15 minute video with openai-whisper took 52 s to download and 15 min 41 s to transcribe (1.04x real time, about 640% CPU, 1.8 GB RAM); faster-whisper should take about half that, extrapolated and not measured on a 15 minute video. faster-whisper writes shorter segments (130 transcript lines against 82 for the same video), so `transcript.txt` is longer but finer-grained.

Stage 1 render, one 18 second clip:

| Step | Time |
|---|---|
| Full render (pass 1 and pass 2) | 62 s |
| `--recompose` (pass 2 only) | 34.5 s |
| `brand-preview` (3 second sample) | 19 s |

Stage 2 layout render (pass 1 through pass 2 together, so the whole clip):

| Job | Output | Time |
|---|---|---|
| Three Drumeo clips with fill ranges | 131 s | 297 s |
| One 18 s clip, whole-clip fill | 18 s | 50 s |

Cost: no API fees. It uses your Claude Code usage for the selection step only.

## Tests
```bash
python3 -m unittest discover -s tests -t .   # host: style, timing, sounds, layout, compose arguments, CLI, ducking, domains, gate, overlays, tracker, sources, package
uv run --with fastapi --with httpx --with jinja2 --with python-multipart python3 -m unittest tests.test_ui   # the review UI (skipped on a plain interpreter)
bash tests/container.sh                       # in the image: real pass 1 then pass 2, key-phrase highlights, multi-range timing, fill/fit layouts, faster-whisper, overlays, the gate through `clip render`, covers and `clip package`
```
The container tests need two cached jobs: `jNQXAC9IVRw` (render tests) and `aMoVyJ9_M24` (layout tests). Fetch each once with `clip fetch https://www.youtube.com/watch?v=<id>`.

## Limits
- CPU transcription is still the bottleneck: about 2x real time with faster-whisper, so a one-hour video takes about half an hour (extrapolated). A Google Colab GPU would likely be faster still; that is not measured here, it needs manual upload and download steps, and it would send the audio to Google, so it is not for client or office material.
- Whisper misspells names, and the captions copy the transcript spelling.
- No editor and no accounts. To change a clip, edit `segments.json` and run `clip render --recompose`. The review UI changes post text and marks only; it does not edit clips.
- The transcript text and extracted frames go to Claude through your Claude Code session.
- **YouTube bot check from the container (seen on 2026-11-02).** Inside the Docker image, yt-dlp lookups and SupoClip's download were answered with YouTube's "Sign in to confirm you're not a bot", while yt-dlp on the host worked from the same connection. Flat searches still work, so `clip sources` lists candidates but marks their licence "Licence not checked", `clip check` cannot read metadata, and a `clip fetch` of a video that is not already cached failed in a test the same day. This is not fixed here and may be temporary; the usual remedy yt-dlp itself suggests is giving it your own cookies, which is your decision to make.
- Caption and title fonts: Anton has no Devanagari glyphs, so Devanagari text would not render. Hinglish in Latin script is fine.
- The gate cannot tell whether what Claude recorded is true; read `verification.md`, especially the health `risk_flags`.
- A YouTube id can start with `-` (about 1 in 64), and the command line then reads it as a flag. Put `--` before the id: `./clip package -- -abc123`. The same applies to `render` and the other job commands, and the UI's package button does not do this yet.
- Only tested on YouTube sources. Local files, Twitch and Kick are untested. Local file names are cleaned to letters, digits, `_` and `-` for the job id.
- Loudness (-14 LUFS) and the bottom safe zone (15%) are common short-form practice, not checked against each platform's current guidance.

## Legal
- Not affiliated with SupoClip or Anthropic. Claude Code and SupoClip are their owners' products.
- `clip.py` imports SupoClip's AGPL-3.0 code at run time, so this repo is licensed AGPL-3.0 too (see LICENSE).
- Clips you make from someone else's video are still their footage. Get permission before posting them.
  YouTube's own reused-content policy applies even with the creator's permission, and from October 2026 Shorts distribution is reduced for channels that mostly repost others' clips without meaningful changes (commentary, analysis or storytelling). Permission settles copyright, not that policy. Read YouTube's current rules before you rely on a clips-only channel.
  Downloading from YouTube may breach its terms. You are responsible for what you clip and publish.
- Music is your responsibility: the tools record licences and refuse the wrong ones, but do not decide fair use or platform policy.
- `out/`, `jobs/`, `tmp/`, `cache/`, `sounds/`, `sources/` and `tracker/` are git-ignored so downloaded footage and audio never get committed.
