# clipwright

> Uses **YouTube API Services**. [Privacy Policy](PRIVACY.md) · [Terms of Service](TERMS.md) · [YouTube Terms of Service](https://www.youtube.com/t/terms) · [Google Privacy Policy](https://policies.google.com/privacy)

Turn a long video into short vertical clips with Claude Code as the clip picker. Clipping needs no API keys, web app or database.
The optional [autopilot](#autopilot-ideas-in-scheduled-posts-out) goes further: video ideas in, approved clips posted on a schedule to YouTube, TikTok, Facebook and Instagram, for several brands, from your own laptop.

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

autopilot (optional): ideas.md -> ./post produce -> ./post review (you approve) -> ./post publish-due
                      -> YouTube, TikTok, Facebook Reels, Instagram Reels via their official APIs
```

## Requirements
- Docker (rootless works), git, about 8 GB free disk
- Claude Code, if you want the "clip this" skill. The scripts also work by hand.
- No GPU needed. Whisper runs on CPU.
- For the autopilot: Python 3.9+ on the host (stdlib only, no pip installs), systemd for the timers, a developer app per platform, and optionally [Demucs](https://github.com/adefossez/demucs) in `tmp/demucs-env/.venv` to strip source music.

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
| `clip fetch <url\|file>` | Download, transcribe, save `transcript.txt` and `state.json` (with title, channel, description, tags when available). |
| `clip render <job> <segments.json>` | Pass 1 then pass 2. Flags: `--only N [N ...]`, `--recompose`, `--exact`, `--clip-length`, `--max-seconds`, `--original`, `--no-subtitles`, `--no-music/--no-whoosh/--no-pop/--no-sting`, `--allow-brand-override`, `--brand NAME`. |
| `clip render ... --recompose` | Reuse the cached pass 1 and redo only pass 2. Use it to try style and sound changes. |
| `clip brand-preview <job> [--segment N]` | Render a 3 second sample into `out/<job>/preview_NN.mp4`. |
| `clip frames <job> --segment N [--every 4]` | Contact sheet of a segment (or `--from/--to`), one labelled frame every few seconds. Used to choose layouts from what is on screen. |
| `clip schema` | Print every style field and its bounds as JSON. |
| `clip profiles` | List the profiles with their resolved values. |
| `clip sounds add\|list` | Manage the sound library. |
| `post ...` | The autopilot (host side): `produce`, `review`, `publish-due`, `queue`, `connect`, `discover`, `words`, `strip-music`, `validate`. See [Autopilot](#autopilot-ideas-in-scheduled-posts-out). |

An invalid style stops the run before anything renders and names the segment and field.

## Brand and style
Style is resolved in three layers, later layers winning: **`brand.json`** (identity and base style), then a **profile** in `profiles/`, then the **`style` block** of a segment.

- **`brand.json`** holds `handle`, `accent`, `text`, `outline`, `headline_font` (the identity) plus the base caption, title, progress bar and sound settings and the mix levels. It ships with placeholders (`@yourchannel`, yellow, Anton). Edit it for your channel, or keep one per brand in `brands/<name>/brand.json` and render with `--brand <name>` (clips then go to `out/<name>/<job>/`). Fonts come from the image's 24 bundled fonts.
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

## Autopilot: ideas in, scheduled posts out
You write ideas and approve clips. Everything else runs on this laptop:

```
brands/<brand>/ideas.md ──(01:30 nightly)──▶ ./post produce   headless Claude Code: discover a source,
                                                               fetch, cut, strip music, render, write copy
                                   ▼
                       ./post review      local page: watch, edit copy per platform, approve or reject
                                   ▼  approve books the brand's next free slots in queue.db
                       ./post publish-due (every 15 min) ─▶ YouTube · TikTok · Facebook Reels · Instagram Reels
```

### Brands
Each brand is a folder, `brands/<name>/` (git-ignored; `brands/example/` is the template):
- `brand.json`: the look (handle, colours, font), as described above. Render with `--brand <name>`, and clips go to `out/<name>/<job>/`.
- `accounts.json`: the timezone, the daily `slots` (such as `["09:00","13:00","19:30"]`), `stagger_minutes` between platforms, extra `hashtags`, and the `platforms` this brand posts to. Facebook needs `page_id` and Instagram needs `ig_user_id`. Set `"audited": true` on `youtube` or `tiktok` once that platform approves your app.
- `ideas.md`: one `- [ ] idea` per line. `produce` takes the first one, then marks it `- [x]` (done, with job ids) or `- [!]` (failed, with the reason).

One clip goes to one brand. Never post the same clip to several accounts on one platform, because platforms treat that as spam.

### Developer apps (one-time, about an hour, then the audits take weeks)
Official APIs only, so each platform needs an app of yours. Put the credentials in `secrets/apps.json` (git-ignored):
```json
{"google": {"client_id": "...", "client_secret": "..."},
 "tiktok": {"client_key": "...", "client_secret": "..."},
 "meta":   {"app_id": "...", "app_secret": "...", "graph_version": "v23.0", "config_id": "..."}}
```
Register `http://localhost:8765/callback` as the redirect URI in each app. **Step-by-step, with the exact use cases and permissions per platform: [docs/platform-setup.md](docs/platform-setup.md).**

| Platform | Create | Before the audit | Audit |
|---|---|---|---|
| YouTube | Google Cloud project, enable YouTube Data API v3, OAuth client of type "Desktop", add yourself as a test user | Uploads stay **private** (YouTube locks unverified API projects) | YouTube API Services audit form. The default quota is 100 uploads a day per project (`videos.insert` has its own bucket) |
| TikTok | developers.tiktok.com app with Login Kit (Desktop) and Content Posting API (Direct Post) | Posts are **private** (SELF_ONLY), for up to 5 accounts, and the TikTok account itself must be set to private | App review for Direct Post. TikTok requires posting controls in the app before it approves (creator name, a privacy choice with no default, comment/duet/stitch toggles, a content disclosure, consent text). The review page does not have them yet |
| Facebook + Instagram | developers.facebook.com "Business" app with Facebook Login. Link each Instagram Business/Creator account to its Page | Works in development mode for Pages and IG accounts you admin | Only needed to post for people who are not app admins or testers |

Then, per brand: `./post connect <brand> google`, `./post connect <brand> tiktok` and `./post connect <brand> meta`. Each one opens the consent page, and tokens land in `secrets/<brand>/` (chmod 600). For Meta, tick the brand's Page and its Instagram account. `connect` prints the Page and IG ids to copy into `accounts.json`.

The endpoints and fields follow each platform's public documentation. They are covered by tests against recorded request shapes, not yet by live accounts, so do your first real post per platform by hand: approve one clip, then run `./post publish-due` and watch it.

### YouTube bot check
Repeated downloads from one home IP soon get "Sign in to confirm you're not a bot". Then the producer marks the idea failed with that reason, rather than retrying and making the block longer. To get past it, export signed-in cookies once:
```bash
yt-dlp --cookies-from-browser chromium --cookies secrets/youtube-cookies.txt --skip-download "https://www.youtube.com/watch?v=jNQXAC9IVRw"
```
`./clip`, `./post discover` and the producer pick up `secrets/youtube-cookies.txt` automatically (inside the container it is `YTDLP_COOKIES=/work/secrets/youtube-cookies.txt`). Use a spare Google account's browser profile: heavy automated downloading can get the signed-in account flagged. Re-export when fetches start failing again, because the cookies expire.

### Daily use
```bash
echo "- [ ] Why cold showers wake your brain up" >> brands/ojastra_mind/ideas.md
./post produce --brand ojastra_mind   # or wait for the 01:30 run; a desktop notification says when clips are ready
./post review                         # approve or reject; approve books the slots
./post publish-due --dry-run          # what would upload now
./post queue                          # every queued post, status, link, last error
scripts/install-timers.sh             # once: publish every 15 min, produce nightly (systemd --user)
```
- **YouTube and Facebook** are uploaded up to 48 hours early with the platform's own schedule (`publishAt`, `scheduled_publish_time`), so they go live on time even if the laptop is asleep then.
- **TikTok and Instagram** have no API scheduling. They upload at the slot, or as soon as the laptop wakes if it was asleep (timers are `Persistent`).
- **Safety:** a clip is queued only by approving it. `(clip, platform)` is unique, so nothing posts twice. Errors that can't resolve themselves (a 4xx, a policy rejection) fail at once. 5xx and 429 errors retry after 15 then 60 minutes. A post interrupted mid-upload is never retried automatically, because it may already be live: check the platform, then `./post retry <id>` or `./post cancel <id>`. Failures send a desktop notification.
- **Music:** `./post strip-music <video_id>` separates the voice with Demucs (install it into `tmp/demucs-env/.venv`, or set `DEMUCS`) and swaps it into the cached source. Render with `--no-music`, then add music from each platform's own library if you want it.

## Tests
```bash
python3 -m unittest discover -s tests -t .   # host: style, timing, sounds, layout, compose arguments, CLI, ducking,
                                              # brands, queue and slots, post.json, review, produce, platform adapters
bash tests/container.sh                       # in the image: real pass 1 then pass 2, key-phrase highlights, multi-range timing, fill/fit layouts, faster-whisper
```
The container tests need two cached jobs: `jNQXAC9IVRw` (render tests) and `aMoVyJ9_M24` (layout tests). Fetch each once with `clip fetch https://www.youtube.com/watch?v=<id>`.

## Limits
- CPU transcription is still the bottleneck: about 2x real time with faster-whisper, so a one-hour video takes about half an hour (extrapolated). A Google Colab GPU would likely be faster still; that is not measured here, it needs manual upload and download steps, and it would send the audio to Google, so it is not for client or office material.
- Whisper misspells names, and the captions copy the transcript spelling.
- No editor. To change a clip, edit `segments.json` and run `clip render --recompose`.
- The autopilot's platform adapters follow each platform's public API documentation and are tested against recorded request shapes, not yet against live accounts. Make the first post on each platform by hand and watch it.
- YouTube and TikTok keep API uploads private until your app passes their audits (weeks). The YouTube Data API allows 100 uploads a day per Google Cloud project by default.
- The autopilot runs only while the laptop is on. Missed timers run on wake, and YouTube and Facebook get videos up to 48 hours early so they publish on time regardless.
- The transcript text and extracted frames go to Claude through your Claude Code session.
- Only tested on YouTube sources. Local files, Twitch and Kick are untested. Local file names are cleaned to letters, digits, `_` and `-` for the job id.
- Loudness (-14 LUFS) and the bottom safe zone (15%) are common short-form practice, not checked against each platform's current guidance.

## Legal
- Not affiliated with SupoClip or Anthropic. Claude Code and SupoClip are their owners' products.
- `clip.py` imports SupoClip's AGPL-3.0 code at run time, so this repo is licensed AGPL-3.0 too (see LICENSE).
- Clips you make from someone else's video are still their footage. Get permission before posting them.
  Downloading from YouTube may breach its terms. You are responsible for what you clip and publish.
- Music is your responsibility: the tools record licences and refuse the wrong ones, but do not decide fair use or platform policy.
- Every autopilot post must carry a credit line naming the source: `./post validate` and the review page refuse copy without it. A credit is not permission.
- Posting through the platforms' APIs is subject to their developer terms and content policies. Do not post the same clip to several accounts on one platform.
- `out/`, `jobs/`, `tmp/`, `cache/` and `sounds/` are git-ignored so downloaded footage and audio never get committed. So are `brands/*` (except `brands/example/`), `secrets/` (OAuth tokens, cookies) and `queue.db`.
