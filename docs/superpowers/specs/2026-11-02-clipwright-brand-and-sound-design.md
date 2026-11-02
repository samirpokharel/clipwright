# Clipwright stage 1: brand pack and sound

Status: draft for review. Written 2026-11-02. Scope: stage 1 only. Stage 2 (per-shot layout, push-in motion) is described in the last section and is not built here.

## 1. Problem and goal

Clipwright turns long videos into 1080x1920 clips. The owner reported three problems with the output:

1. **Framing looks low-effort.** Wide shots sit as a thin 16:9 strip over a blurred copy of themselves, and nothing moves.
2. **Style is generic.** Every clip used SupoClip's `default` caption template and a plain white hook title.
3. **No sound design.** The original audio passes through. There is no music, effect or mix.

**Goal of stage 1:** fix problems 2 and 3 completely, with no fork of SupoClip. Problem 1 is deferred to stage 2 and stage 1 must not make it harder.

**Success looks like:** a clip rendered with stage 1 carries the owner's brand (accent colour, headline font, title block, handle, progress bar), highlights meaningful key words, and has a mixed soundtrack that is loud, balanced and legally cleared for a public channel.

### Non-goals
An editor, auto-posting, music generation, voice changes, and any change to framing (stage 2).

## 2. Decisions already made (brainstorm 2026-11-02)

| Topic | Decision |
|---|---|
| Use case | Clipping other people's videos for a public channel. Music must be cleared for public use. |
| Framing | Pick per shot: fill crop that follows the face for people, designed card for diagrams and slides. Stage 2. |
| Style | One brand pack, values in `brand.json`, placeholders until the owner sets them. |
| Sound | All four: music bed under speech, transition whooshes, pops on emphasis words, intro and outro sting. |
| Build approach | Two stages, no fork. Stage 1 is a second pass on top of SupoClip's renderer. |
| Sound sources | Synthesized effects (no licence), Freesound CC0 and CC-BY (curated once), owner-supplied files. |
| Per-video style | Three layers: brand identity (fixed), profiles by video type, per-clip overrides written by Claude Code. The interface is validated JSON plus commands, not an MCP server. Added 2026-11-02. |

Snapshots of the mockup screens that led to these choices are on the local review page `http://127.0.0.1:8765/personal/clipwright/2026-11-02-supoclip-upgrade-brainstorm.html`.

## 3. Architecture

### 3.1 Pipeline

```
clip fetch            (unchanged)  download, Whisper transcript, word timings
Claude picks          (extended)   segments.json now also carries key_words and source_music
clip render
  pass 1  cut+frame   SupoClip create_video_clips, add_subtitles=False, hook_title=None
  pass 2  compose     Clipwright: captions + title + handle + progress bar + sound, one ffmpeg run
out/<id>/NN_*.mp4, manifest.json, credits.txt
```

Pass 1 uses SupoClip exactly as today for cutting, sentence snapping and framing. Its output is cached so pass 2 can re-run alone.

### 3.2 Units

| Unit | File | Purpose | Depends on |
|---|---|---|---|
| Style | `brand.json`, `profiles/*.json`, `clipwright/style.py` | Load, merge (brand, profile, clip override), validate and describe the style | none |
| Compose | `compose.py` | Build the ASS file and the ffmpeg command for pass 2 | brand, sounds plan, SupoClip caption builder |
| Sounds | `sounds.py` | Library lookup, synthesis, mix plan, credits | `sounds/library.json`, ffmpeg |
| Freesound helper | `freesound.py` | Check licence and fetch one sound into the library | Freesound API, `FREESOUND_API_KEY` |
| CLI | `clip.py` | Wire the steps, flags, caching | all of the above |

Each unit has one purpose, can be tested alone, and talks to the others through plain data (JSON files and dicts).

### 3.3 Where code runs
All of `clip.py` and its modules run inside the `supoclip-backend` container, as today. The new modules live in a `clipwright/` package next to `clip.py`. Both are bind-mounted (the package at `/app/clipwright`), so no image rebuild is needed. Modules import SupoClip code lazily, inside functions, so the pure-logic tests run on the host with plain `python3 -m unittest`.

## 4. Data formats

### 4.1 `brand.json`

`brand.json` holds the channel identity and the base style. Profiles and per-clip overrides (4.4) change the base style, never the identity.

```json
{
  "handle": "@yourchannel",
  "accent": "#FFD400",
  "text": "#FFFFFF",
  "outline": "#000000",
  "headline_font": "Anton-Regular",
  "base": {
    "caption": {"size": "medium", "words_per_line": 3, "uppercase": true, "position_y": 0.75, "outline_px": 3},
    "title": {"enabled": true, "seconds": 4, "size": "medium", "max_lines": 2, "tilt_degrees": -2, "top": 0.05, "text_color": "#111111"},
    "progress_bar": {"enabled": true, "height_px": 5, "track_alpha": 0.25},
    "sound": {"music": "low", "whoosh": "normal", "pop": "normal", "sting": "normal"}
  },
  "mix": {"music_db": -20, "whoosh_db": -18, "pop_db": -22, "sting_db": -16, "low_offset_db": -6, "target_lufs": -14}
}
```

Fonts come from the image's `fonts/` folder (24 bundled). Validation rejects unknown keys, bad hex colours, missing fonts, and out-of-range values. Each error names the field.

### 4.2 `segments.json` additions
Three optional fields per segment, ignored by older tools (`style` is described in 4.4):

- `"key_words": ["powerful", "iron core"]`: 2 to 4 words or short phrases that are spoken in the segment. Matched case-insensitively against the word timings.
- `"source_music": true`: the source already has music under the speech. The music bed is skipped for this clip.
- `"style": {...}`: a profile name and bounded overrides for this clip. See 4.4.

If `key_words` is absent, SupoClip's automatic emphasis is used. If a key word is not found in the spoken words, compose logs a warning naming it and continues.

Not verified: whether the caption builder's `highlight_words` matches multi-word phrases. If it matches single words only, compose splits a phrase into its words and highlights each. The plan confirms this with a test.

### 4.3 `sounds/library.json`

```json
[{"id": "whoosh-synth-1", "kind": "whoosh", "file": "fx/whoosh-synth-1.wav",
  "source": "synthesized", "license": "none", "author": null, "url": null},
 {"id": "fs-123456", "kind": "music", "file": "music/fs-123456.mp3",
  "source": "freesound", "license": "CC-BY", "author": "username",
  "url": "https://freesound.org/s/123456/", "attribution": "Title by username (CC BY)"}]
```

`kind` is one of `music`, `whoosh`, `pop`, `sting`, `outro`. `license` is one of `none`, `CC0`, `CC-BY`, `own`. Any other value fails validation. Files live under `sounds/` and are git-ignored. Only `library.json` is committed, and only as an empty list `[]` template. It holds only entries the owner adds. The synthesized sounds (6.1) are defined in code, generated into `sounds/synth/` on first use, and merged with the library at run time.

### 4.4 Profiles and per-clip style

The style of one clip is resolved in three layers, later layers winning, by a deep merge:

1. **Base:** `brand.json` `base` and `mix`.
2. **Profile:** `profiles/<name>.json`, a partial style chosen by video type.
3. **Clip override:** the segment's `style` block, written by Claude Code.

Result: one fully specified style per clip, validated against the bounds below. Any value outside its bound is an error, never silently clamped.

```json
"style": {
  "profile": "explainer",
  "caption": {"size": "large", "words_per_line": 3},
  "title": {"seconds": 3},
  "sound": {"music": "off", "pop": "normal"}
}
```

| Field | Allowed values |
|---|---|
| `caption.size` | `small`, `medium`, `large` (font scale 0.8, 1.0, 1.25) |
| `caption.words_per_line` | integer 1 to 6 |
| `caption.uppercase` | true or false |
| `caption.position_y` | 0.55 to 0.80 (fraction of frame height) |
| `caption.outline_px` | integer 0 to 6 |
| `title.enabled`, `progress_bar.enabled` | true or false |
| `title.seconds` | 1 to 8 |
| `title.size` | `small`, `medium`, `large` |
| `title.max_lines` | 1 to 3 |
| `title.tilt_degrees` | -5 to 5 |
| `title.top` | 0.03 to 0.12 |
| `progress_bar.height_px` | integer 2 to 10 |
| `sound.music`, `sound.whoosh`, `sound.pop`, `sound.sting` | `off`, `low`, `normal` |

`low` plays at `low_offset_db` below `normal`. `off` disables that sound. A `source_music: true` segment forces `sound.music` to `off`.

**Locked identity.** `handle`, `accent`, `text`, `outline`, `headline_font` and `title.text_color` cannot appear in a profile or a clip `style`. They fail validation. A run flag `--allow-brand-override` lifts this for one run.

**Starter profiles**, chosen by video type:

| Profile | Fits | Caption | Title | Sound |
|---|---|---|---|---|
| `explainer` | Commentary, news, diagrams | 3 words per line, medium | 4 s | music low, whoosh normal, pop normal, sting normal |
| `performance` | Music, drumming, live shows | 3 words per line, medium | 5 s, large | music off, whoosh low, pop off, sting low |
| `interview` | Podcasts, conversations | 5 words per line, medium, sentence case | 3 s | music low, whoosh off, pop off, sting low |
| `tutorial` | How-to, lessons | 3 words per line, large | 4 s | music off, whoosh low, pop low, sting normal |

**Discovery.** `clip schema` prints the fields and bounds above as JSON, and `clip profiles` lists each profile with its resolved values. Claude Code reads these instead of relying on memory. The `supoclip` skill carries guidance for choosing a profile and for typical adjustments, and states that Claude chooses from the title, channel, description and transcript.

### 4.5 Pass 1 cache
`jobs/<id>/pass1/NN.mp4` and `jobs/<id>/pass1/manifest.json`, holding per clip: the pass-1 path, `keep_ranges` (source seconds, as returned in SupoClip's clip info), the source video path, duration, and the segment's hook title and key words. `--recompose` reads this and skips pass 1.

## 5. Pass 2: compose

### 5.1 Inputs
The pass-1 clip, its `keep_ranges`, the word timings cached beside the source video, `brand.json`, the segment, and a mix plan from `sounds.py`.

### 5.2 Captions
Call SupoClip's `build_assemblyai_ass_subtitles` (in `media/captions.py`) with:
`keep_ranges` from the pass-1 manifest (this maps source word times onto the cut clip), `template_override` set to a template dict derived from the clip's resolved style (4.4) and the brand identity, `highlight_words` set to the segment's `key_words`, `hook_title=None`, and 1080 by 1920 output. No SupoClip file is edited.

### 5.3 Brand title, handle, progress bar
- **Title block.** A second ASS file (or a second event set) drawn by `compose.py`: accent-coloured opaque box, headline font, tilted by `tilt_degrees`, at `top`, for `seconds`, with at most `max_lines` lines. If libass cannot render the tilted box faithfully, the fallback is SupoClip's `hook_editor_style` on the built-in title. Choosing between them is the first task of the plan.
- **Handle.** One ASS event, bottom-left at 0.84 of the frame height (just above the bottom safe zone), for the whole clip.
- **Progress bar.** An ffmpeg `drawbox` pair: a faint full-width track and an accent bar whose width grows with `t / duration`.

### 5.4 One ffmpeg run
Inputs: the pass-1 clip, optional music, optional effect files. Video filter: `subtitles` for the caption ASS and title ASS, plus the two `drawbox` filters. Audio filter graph: see section 6. Output: H.264 video, AAC audio, 1080x1920, written to `out/<id>/`.

### 5.5 Safe zones
Text stays out of the bottom 15% of the frame and the far-right edge, where platform buttons and captions appear. These margins come from general practice and are not checked against any platform's current published guidance.

## 6. Sound

### 6.1 Synthesized effects
Generated once into `sounds/fx/` on first use by ffmpeg `lavfi` recipes in `sounds.py`. Intent for each, exact filter strings chosen in the plan:

- **whoosh:** about 0.4 s of band-passed pink noise with a fast fade in and a longer fade out.
- **pop:** about 80 ms low sine burst with a quick decay.
- **sting (intro):** about 0.6 s rising tone ending in a soft low hit.
- **outro:** about 0.6 s soft falling tone.

- **pad (placeholder music):** a 30 s looping ambient pad (layered sines with a slow tremolo) so the music bed and ducking work before the owner adds real tracks. It is a placeholder, not good music.

Because they are generated, they carry no licence and are not committed.

### 6.2 Freesound helper
`clip sounds add <freesound-url-or-id> --kind <kind>`:

1. Read the sound's metadata with the owner's `FREESOUND_API_KEY` (environment variable, never stored in the repo).
2. Accept only the licences Creative Commons 0 and Attribution. Refuse every other licence, including NonCommercial and Sampling+, with a message naming the licence.
3. Download the HQ MP3 preview. Original files need OAuth2 and are not used.
4. Append an entry to `sounds/library.json`, including the attribution text for CC-BY.

Field names (`license`, `username`, `previews`) and the preview key are taken from Freesound's public API documentation and must be confirmed against a live response during implementation. Search is not part of this helper. The owner finds sounds on the website.

Freesound's API terms say commercial use of the API is negotiated case by case. The helper is for occasional curation, not rendering-time queries. The owner is responsible for reading `https://freesound.org/help/tos_api` and deciding whether their use is covered. Sounds fetched by hand from the website under CC0 or CC-BY do not involve the API terms.

`clip sounds add --file <path> --kind <kind> --license <own|CC0|CC-BY> [--author ...]` records an owner-supplied file. `clip sounds list` prints the library.

### 6.3 Mix plan
`sounds.py` returns, per clip, a list of `(file, start_seconds, gain_db)` events plus a music decision. A sound's gain is its `mix.<kind>_db` value for `normal`, that value plus `mix.low_offset_db` for `low`, and the sound is absent for `off`. The `<kind>_db` names in the table below stand for these resolved gains.

| Sound | Event time (clip seconds) | Rule | Gain |
|---|---|---|---|
| Intro sting | 0 | Always, if enabled | `sting_db` |
| Outro | `duration - 0.6` | Always, if enabled | `sting_db` |
| Whoosh | Source shot changes mapped through `keep_ranges` | At most one per 4 s | `whoosh_db` |
| Pop | Start of the first matched word of each key word or phrase | At most 3 per clip | `pop_db` |
| Music bed | 0 to `duration` | Skipped if `source_music` is true or `sound.music` is `off`. With no music track in the library, the built-in pad is used. | `music_db` (plus `low_offset_db` for `low`), then ducked by sidechain compression while speech is present |

**Shot changes** come from ffmpeg's scene-change filter on the source over the kept ranges, threshold 0.35, then mapped to clip time.

**Ducking.** The speech track is the key for `sidechaincompress` on the music. Constants in `compose.py`: threshold 0.05, ratio 8, attack 20 ms, release 400 ms. Measured on a synthetic clip, these duck the music by about 14.6 dB while speech plays. There is no separate `duck_db` setting.

**Music bed.** Looped to clip length, 0.5 s fade in, 1 s fade out. When several music tracks exist, the pick is deterministic by clip number, so re-runs match.

**Loudness.** The final mix goes through `loudnorm` to `target_lufs` (default -14) with a true-peak ceiling of -3 dB before AAC encoding. At -1.5 dB the encoded clips peaked up to +0.1 dBFS (measured 2026-11-02), so the ceiling leaves headroom; the cost is that integrated loudness lands 0.4 to 1.4 LU below the target on speech-heavy clips. The -14 figure is a common short-form target, not verified per platform.

### 6.4 Credits
After rendering, write `out/<id>/credits.txt` with one line per CC-BY sound used in any clip of the job. The file is empty (or absent) when none were used.

## 7. CLI

```
clip fetch <url|file>                       unchanged, and also saves title, channel, description,
                                            categories and tags to jobs/<id>/state.json when available
clip schema                                 print the style fields and bounds as JSON
clip profiles                               list profiles with their resolved values
clip render <job> <segments.json>           pass 1 then pass 2
      --allow-brand-override                allow identity fields in profiles or clip styles
      --recompose                           reuse pass 1, redo pass 2 only
      --only N [N ...]                      unchanged
      --no-music --no-whoosh --no-pop --no-sting   override brand.json for this run
      (existing flags unchanged: --exact, --clip-length, --max-seconds, --original)
clip brand-preview <job> [--segment N]      3-second pass-2 sample from the cached pass 1
clip sounds add|list                        see 6.2
```

`--no-subtitles` and `--original` keep their meaning: pass 2 skips captions or runs on the original aspect. With `--original`, the title block and progress bar are scaled to the clip size.

## 8. Errors

- `brand.json` and `sounds/library.json` are validated before any rendering. Errors name the file and field.
- A library entry whose file is missing fails the run with the entry id. Nothing is skipped silently.
- An unmatched key word logs a warning and continues.
- If pass 2 fails for a clip, the pass-1 file is kept and the error includes the last lines of ffmpeg's stderr. Other clips continue.
- A refused Freesound licence stops that `sounds add` call with a message and changes nothing.
- A style value outside its bound, an unknown field, an unknown profile, or a locked identity field in a profile or clip style is an error naming the segment number and the field. Nothing is clamped. No clip renders until every segment's style is valid.

## 9. Testing

**Host, pure logic (no ffmpeg, no container):** style merging (brand, profile, clip override) including deep merge and the identity lock, bound checks for every field in 4.4, schema output, profile resolution, brand validation, key-word matching against word timings, `keep_ranges` time mapping, mix-plan arithmetic including the per-4-seconds whoosh limit and the 3-pop limit, the licence allowlist, and library validation.

**Container, ffmpeg:** render a fixed 5-second sample from a small fixture with a fixed `brand.json`, then assert:

- the file is 1080 by 1920 with H.264 video and AAC audio, and the duration matches the pass-1 clip;
- a frame at 1 s contains the accent colour inside the title region, and a frame at 6 s (after the title) does not;
- the progress bar's accent width is about 0% near the start and about 100% at the end;
- integrated loudness is within 2 LU of `target_lufs`;
- with music enabled, music-only energy is at least 6 dB lower in a window containing speech than in a window of silence from the speech track.

The existing manual flow (render a real clip, extract frames, look at them) stays as the final check.

## 10. Acceptance criteria for stage 1

1. `clip render` on an existing job produces clips with the brand look: title block, handle, progress bar and accent-highlighted key words.
2. A clip with sound enabled has the four sound types present as designed, with CC-BY credits written when applicable.
3. `--recompose` on a cached job finishes in under 30 seconds per clip on the owner's laptop. (Estimate, to be measured.)
4. `brand-preview` finishes in under 15 seconds. (Estimate, to be measured.)
5. All tests in section 9 pass.
6. No SupoClip file is modified.
7. `README.md` documents `brand.json`, profiles and clip styles, the sounds library, licensing, and the new flags.
8. Two clips from different video types (for example commentary and music) render with visibly different resolved styles chosen through profiles, with identity unchanged.
9. An invalid `style` block stops the run with an error naming the segment and field.

## 11. Risks and open questions

| Risk | Handling |
|---|---|
| The caption builder is internal SupoClip code, not a stable API. | The upstream commit is pinned in `setup.sh`. Compose isolates all calls to it in one function. |
| libass may not render the tilted opaque title box as designed. | Fallback in 5.3. Decided first in the plan. |
| Word timings for clips with internal cuts could drift. | The builder takes `keep_ranges`, which is what pass 1 returns. The container test checks caption timing on a clip with a cut. |
| Mixing sidechain ducking by ear on a laptop speaker may not translate to phones. | The numeric test in section 9 sets a floor. The owner reviews on a phone. |
| Freesound API terms may not cover the owner's use. | Helper is for occasional curation. Owner reads the terms. Manual downloads and own files are alternatives. |
| `source_music` is a manual flag set by Claude from the transcript. | Documented. Wrong flags are fixed by editing `segments.json` and using `--recompose`. |
| Loudness target and safe-zone margins are unverified per platform. | Both live in `brand.json` or constants, easy to change. |
| Choosing a profile depends on Claude's judgement of the video type, from metadata that yt-dlp may not return for every source. | Metadata is saved when available. Claude falls back to the transcript and says which profile it chose. Wrong picks are fixed by editing `style` and using `--recompose`. |
| Bounds on style fields may be too tight or too loose in practice. | Bounds live in one table in `style.py` and the schema output, so they change in one place. |
| Music from the owner's own library is the owner's licensing responsibility. | `sounds add --file` requires a licence value and records it. |

Open question, deferred to stage 2: whether a slow push-in belongs in pass 2 (possible with an ffmpeg zoom on the framed video) or in layout code.

## 12. Stage 2 (not in this spec)

Per-shot layout (fill crop for faces, designed card for diagrams and slides) and push-in motion. It begins with a short spike that reads SupoClip's `media/reframing.py` and its layout modules to answer: can fit-versus-crop be steered per shot, and can face boxes be read out? The answer chooses between a vendored patch and an own compositor. `compose.py` takes a layout parameter for title placement so stage 1 needs no rework.

## 13. Licensing and responsibility

This repository is AGPL-3.0 because it imports SupoClip's AGPL-3.0 code. Clips made from other people's videos remain those creators' footage, and the owner is responsible for permission to publish them. Music and sounds are the owner's responsibility: the tools record licences and refuse the wrong ones, but do not decide fair use or platform policy.
