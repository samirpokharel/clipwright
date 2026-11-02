# Clipwright Stage 1: Brand Pack, Sound and Per-Video Style Implementation Plan

> **Status: executed 2026-11-02 and merged.** This is the plan as written. Where the build differed, the spec (sections 5 to 12) and the commit history are the record. Known differences: true-peak ceiling is -3 dB (not -1.5), the handle sits at 0.84 of frame height, there is no `duck_db`, the `--caption-template` flag was removed, and the package is found through `PYTHONPATH=/work` (no `/app/clipwright` mount).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second render pass to Clipwright that applies a brand look, key-word captions and a mixed soundtrack, with style chosen per video through profiles and per-clip overrides.

**Architecture:** Pass 1 is SupoClip's existing renderer with no captions or title, cached per job. Pass 2 (`clipwright/compose.py`) builds captions with SupoClip's `build_assemblyai_ass_subtitles`, draws the title block, handle and progress bar, mixes sound, and encodes once with ffmpeg. A pure-Python `style.py` merges brand, profile and clip override into one validated style.

**Tech Stack:** Python 3.11 (container `.venv`, host `python3` stdlib for tests), ffmpeg/libass, `unittest`, SupoClip backend image `supoclip-backend` at the commit pinned in `setup.sh`.

**Spec:** `docs/superpowers/specs/2026-11-02-clipwright-brand-and-sound-design.md`

## Global Constraints

- No SupoClip file is modified. SupoClip code is imported lazily inside functions so host tests need only stdlib.
- Output is 1080x1920, H.264 video, AAC audio.
- Text stays out of the bottom 15% of the frame and the far-right edge. The handle sits at 0.84 of frame height, bottom-left.
- Locked identity fields (`handle`, `accent`, `text`, `outline`, `headline_font`, `title.text_color`) never change via profile or clip style unless `--allow-brand-override`.
- A style value out of bounds, an unknown field, or an unknown profile is an error naming segment and field. Nothing is clamped. No clip renders until every segment validates.
- Licences accepted by tooling: `none`, `CC0`, `CC-BY`, `own`. Freesound sounds only CC0 and CC-BY.
- Loudness target -14 LUFS, true peak -1.5 dB (superseded: built with -3 dB, see spec 6.3). Whoosh at most one per 4 s, pops at most 3 per clip, shot-change threshold 0.35.
- Python via `uv` for any script needing dependencies. Tests are stdlib `unittest`.
- Em dashes are not used in docs or page text.

## Review Focus

Failure modes the spec implies that no single feature task would otherwise test, most likely first:

1. A `key_words` entry that never appears in the spoken words. Expect a warning naming it, and the clip still renders.
2. A clip cut from several `keep_ranges`. Caption, pop and whoosh times must map through the cuts, not through the source timeline.
3. A segment `style` with an unknown profile, an out-of-range value or a locked identity field. Expect one error naming the segment and field, and no partial renders from other segments.
4. An empty `library.json`, or a library entry whose file is missing. Empty means the built-in placeholder pad is the music bed. A missing file is a hard error naming the entry id.
5. A pass-1 clip with no audio track, or a clip shorter than the title duration. Expect a render with sound effects only, and a title shortened to fit.

Each line has its test in the owning task below (marked **RF1** to **RF5**).

---

## File Structure

| Path | Responsibility |
|---|---|
| `clipwright/__init__.py` | Package marker. |
| `clipwright/style.py` | Load brand and profiles, merge three layers, validate, describe schema. |
| `clipwright/timing.py` | Source-to-clip time mapping and key-word matching. Pure. |
| `clipwright/sounds.py` | Synthesized sounds, library loading, shot-change detection, mix plan, credits. |
| `clipwright/freesound.py` | Licence allowlist and one-sound fetch. |
| `clipwright/compose.py` | Caption template, title and handle ASS, filter graph, ffmpeg args, `compose_clip`. |
| `clip.py` | CLI wiring (modify). |
| `clip` | Wrapper: mount the package (modify). |
| `brand.json`, `profiles/*.json`, `sounds/library.json` | Data files, committed with placeholders. |
| `tests/test_*.py` | Host unit tests. `tests/container/test_render.py` runs in the image. |
| `skill/SKILL.md`, `README.md` | Documentation. |

---

### Task 1: Style engine

**Files:**
- Create: `clipwright/__init__.py`, `clipwright/style.py`, `brand.json`, `profiles/explainer.json`, `profiles/performance.json`, `profiles/interview.json`, `profiles/tutorial.json`, `tests/test_style.py`

**Interfaces:**
- Produces: `class StyleError(ValueError)`; `load_brand(path: Path) -> dict`; `load_profile(name: str, profiles_dir: Path) -> dict`; `list_profiles(profiles_dir: Path) -> dict[str, dict]`; `resolve_style(brand: dict, profile: dict | None, override: dict | None, *, where: str, allow_brand_override: bool = False) -> dict`; `schema() -> dict`. Constants `CAPTION_PX = {"small": 52, "medium": 64, "large": 80}` and `TITLE_PX = {"small": 52, "medium": 64, "large": 80}`.
- Resolved style shape: `{"identity": {handle, accent, text, outline, headline_font}, "caption": {...}, "title": {...}, "progress_bar": {...}, "sound": {music, whoosh, pop, sting}, "mix": {...}}`, with field names and bounds exactly as spec section 4.4.

- [ ] **Step 1: Write failing tests in `tests/test_style.py`**: `test_clip_override_beats_profile_beats_base` (base words_per_line 3, profile 5, clip 2 gives 2); `test_deep_merge_keeps_sibling_keys` (override `sound.music` leaves `sound.pop`); `test_out_of_bounds_names_field` (`caption.words_per_line: 9` raises `StyleError` whose message contains `segment 2` and `caption.words_per_line`); `test_unknown_field_rejected`; `test_unknown_profile_rejected`; `test_identity_locked_in_profile_and_clip` and `test_allow_brand_override_lifts_lock`; `test_source_music_forces_music_off` is covered in Task 3; `test_schema_lists_every_bound` (every row of spec 4.4 table appears); `test_starter_profiles_validate` (all four resolve against `brand.json`); **RF3** `test_invalid_style_in_one_segment_reports_segment_number`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_style -v`. Expected: FAIL, module missing.
- [ ] **Step 3: Implement** `clipwright/style.py` as one table `BOUNDS` mapping dotted field paths to a validator (enum list, int range, float range, bool), used by both `resolve_style` and `schema`. Deep-merge with plain dicts. Validate the merged result, and separately reject identity keys found in profile or override. Write `brand.json` per spec 4.1 and the four profiles per spec 4.4 table.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `git add clipwright tests brand.json profiles && git commit -m "feat: style engine with profiles and per-clip overrides"`.

### Task 2: Timing helpers

**Files:**
- Create: `clipwright/timing.py`, `tests/test_timing.py`

**Interfaces:**
- Produces: `to_clip_time(t: float, keep_ranges: list[tuple[float, float]]) -> float | None` (source seconds to clip seconds, `None` if `t` falls in a cut); `match_key_words(words: list[dict], key_words: list[str], keep_ranges) -> tuple[list[tuple[float, str]], list[str]]` returning matched `(clip_time, key_word)` pairs and the list of unmatched key words. Each `words` item has `text`, `start`, `end` in milliseconds as in SupoClip's cache.

- [ ] **Step 1: Write failing tests**: `test_single_range_offsets_from_range_start` (range (10,20), t=12 gives 2.0); `test_two_ranges_skip_the_cut` (ranges (10,12),(20,25), t=21 gives 3.0); `test_time_in_cut_returns_none`; `test_match_is_case_and_punctuation_insensitive` ("Powerful," matches "powerful"); `test_phrase_matches_consecutive_words` ("iron core"); `test_unmatched_key_word_listed` **RF1**; **RF2** `test_match_times_map_through_cuts`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_timing -v`. Expected: FAIL.
- [ ] **Step 3: Implement** both functions. Normalise tokens by lowercasing and stripping non-alphanumerics. Words outside every keep range are ignored.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: source-to-clip timing and key-word matching`.

### Task 3: Sounds, library and mix plan

**Files:**
- Create: `clipwright/sounds.py`, `sounds/library.json` (content `[]`), `tests/test_sounds.py`
- Modify: `.gitignore` (ignore `sounds/*` except `sounds/library.json`)

**Interfaces:**
- Consumes: resolved style from Task 1, `match_key_words` and `to_clip_time` from Task 2.
- Produces: `@dataclass Event(kind: str, file: str, start: float, gain_db: float)`; `@dataclass MixPlan(events: list[Event], music: dict | None)` where `music` is `{"file", "gain_db"}`; `ensure_synth(sounds_dir: Path) -> None` (writes `whoosh.wav`, `pop.wav`, `sting.wav`, `outro.wav`, `pad.wav` into `sounds_dir/synth/` via ffmpeg `lavfi`, skipping existing files); `load_library(sounds_dir: Path) -> list[dict]` (synth entries plus `library.json`, validated); `detect_shot_changes(video: Path, keep_ranges, threshold: float = 0.35) -> list[float]` (clip seconds); `plan_mix(style: dict, duration: float, pops: list[float], shots: list[float], library: list[dict], clip_index: int, source_music: bool) -> MixPlan`; `credits(plans: list[MixPlan], library: list[dict]) -> list[str]`.

- [ ] **Step 1: Write failing tests**: `test_whoosh_spacing_at_least_four_seconds` (shots at 1,2,3,9 give events at 1 and 9); `test_pops_capped_at_three`; `test_sting_at_zero_and_outro_before_end` (outro start = `duration - 0.6`); `test_off_removes_sound_and_low_adds_offset` (low gain = normal + `low_offset_db`); `test_source_music_forces_no_music_bed`; **RF4** `test_empty_library_uses_builtin_pad` (`music["file"]` ends with `synth/pad.wav`), `test_real_music_track_beats_pad`, and `test_missing_library_file_is_error_naming_entry`; `test_disallowed_licence_fails_validation`; `test_credits_lists_only_cc_by_used`; `test_music_pick_is_deterministic_by_clip_index`; **RF5** `test_title_events_clamped_when_clip_shorter_than_sting` (outro start never below 0).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_sounds -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Synth recipes by ffmpeg `lavfi` per spec 6.1 (whoosh: 0.4 s band-passed pink noise, fade in 0.1 s, fade out 0.3 s; pop: 80 ms 180 Hz sine, exponential decay; sting: 0.6 s rising sine 300 to 700 Hz with a low 90 Hz hit at the end; outro: 0.6 s falling sine 500 to 250 Hz; pad: 30 s of 220, 277 and 330 Hz sines with 0.2 Hz tremolo, looping seamlessly). Decision: the pad is a valid music bed so the mix works out of the box, and a real track with `kind: music` in `library.json` wins over it. `detect_shot_changes` runs ffmpeg `select='gt(scene,T)',showinfo` per keep range and parses `pts_time`, then maps through `to_clip_time`.
- [ ] **Step 4: Run.** Expected: PASS. Also run `python3 -c "from clipwright.sounds import ensure_synth; ..."` into a temp dir and confirm five non-empty `.wav` files exist.
- [ ] **Step 5: Commit** `feat: sound library, synthesized sounds and mix plan`.

### Task 4: Freesound helper

**Files:**
- Create: `clipwright/freesound.py`, `tests/test_freesound.py`

**Interfaces:**
- Produces: `class LicenceRefused(ValueError)`; `licence_label(license_url: str) -> str` (maps Freesound licence URLs or names to `CC0` or `CC-BY`, raises `LicenceRefused` otherwise); `parse_sound_id(url_or_id: str) -> int`; `fetch_sound(sound_id: int, kind: str, api_key: str, sounds_dir: Path, *, http_get=None) -> dict` returning the new library entry after writing the preview file and appending to `library.json`. `http_get` is injectable for tests.

- [ ] **Step 1: Write failing tests** with a fake `http_get` returning fixture JSON: `test_cc0_accepted`; `test_cc_by_accepted_with_attribution_text`; `test_noncommercial_refused_and_library_unchanged`; `test_sampling_plus_refused`; `test_parse_url_and_bare_id` (`https://freesound.org/s/123456/` and `123456`); `test_missing_api_key_is_clear_error`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_freesound -v`. Expected: FAIL.
- [ ] **Step 3: Implement** using `urllib.request` (no new dependency). Metadata from `https://freesound.org/apiv2/sounds/<id>/?token=<key>&fields=id,name,username,license,url,previews`, preview from `previews["preview-hq-mp3"]`. Field names are from public docs and are not verified against a live response: print a notice on first use and report this at the end of the run.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: Freesound licence-checked fetch helper`.

### Task 5: Compose pass

**Files:**
- Create: `clipwright/compose.py`, `tests/test_compose_args.py`, `tests/container/test_render.py`, `tests/container.sh`

**Interfaces:**
- Consumes: resolved style (Task 1), `MixPlan` (Task 3), SupoClip `media.captions.build_assemblyai_ass_subtitles`.
- Produces: `caption_template(style: dict) -> dict` (SupoClip template dict: font from `identity.headline_font`, `highlight_color` and `emphasis_color` from accent, `font_color` from text, `stroke_color` from outline, `stroke_width`, `uppercase`, `max_words_per_line`, `animation: "pop"`, `word_box: False`, `emoji: False`); `title_ass(text: str, style: dict, duration: float, width: int = 1080, height: int = 1920) -> str` (opaque tilted box per line, fades in and out, shortened to `min(title.seconds, duration - 0.3)`) and `handle_ass(...)` merged into the same file; `build_ffmpeg_args(pass1: Path, out: Path, ass_files: list[Path], style: dict, mix: MixPlan, duration: float, has_audio: bool, fonts_dir: str) -> list[str]`; `compose_clip(entry: dict, style: dict, mix: MixPlan, out: Path, workdir: Path) -> None`.

- [ ] **Step 1: Write failing host tests** in `tests/test_compose_args.py`: `test_caption_template_uses_accent_and_text`; `test_title_ass_box_uses_accent_and_tilt` (contains accent in ASS BGR form and `\frz-2`); `test_title_shortened_for_short_clip` **RF5**; `test_progress_bar_uses_overlay_expression_not_drawbox_t` (args contain `overlay=x='-w+w*t/`); `test_audio_graph_has_sidechain_and_loudnorm_when_music` (contains `sidechaincompress` and `loudnorm=I=-14:TP=-1.5`); `test_no_audio_track_uses_anullsrc` **RF5**; `test_no_music_no_sidechain`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_compose_args -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the four functions. Decisions: progress bar is a `color` lavfi input of height `progress_bar.height_px` overlaid with `x='-w+w*t/DUR'` over a static track made with `drawbox` (drawbox has no `t`); ducking constants threshold 0.05, ratio 8, attack 20, release 400 live in `compose.py` (the spec's `duck_db` is dropped, see Task 7); effect events use `adelay` then `volume`; mix with `amix=normalize=0`; encode `libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart`. Mirror SupoClip's own call to the caption builder in `video_utils.create_optimized_clip` (around lines 440 to 470) for width, height and font handling, and pass `font_px_override` from `CAPTION_PX`, `position_y_override` from the style, `highlight_words` from key words, `hook_title=None`.
- [ ] **Step 4: Run** host tests. Expected: PASS.
- [ ] **Step 5: Write container test** `tests/container/test_render.py`. Its setup renders pass 1 once for job `jNQXAC9IVRw` (segment 00:00 to 00:18, via SupoClip `create_video_clips` with `add_subtitles=False`, about 45 s) into `tmp/test-pass1/` and reuses it on later runs. It then runs `compose_clip` on that clip and asserts: 1080x1920 with an audio stream; accent colour present in the title region at 1 s and absent at 6 s; accent pixels in the bottom 8 px row near 100% width at the last frame and near 0% at the first; integrated loudness (`ffmpeg -af ebur128`) within 1 LU of -14; with music on, music-only energy 6 dB lower in a speech window than in a silent one (render music-only variant by `--no-voice` test flag in `compose_clip`: parameter `voice: bool = True`); **RF1** unmatched key word still renders. `tests/container.sh` runs `docker run` with the same mounts as `clip` and `python -m unittest discover -s /work/tests/container`.
- [ ] **Step 6: Run** `bash tests/container.sh`. Expected: PASS. If libass does not draw the tilted opaque box, switch to the spec 5.3 fallback and record that in the commit message.
- [ ] **Step 7: Commit** `feat: pass 2 compose with brand title, captions, progress bar and sound`.

### Task 6: CLI wiring

**Files:**
- Modify: `clip.py`, `clip`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces CLI: `clip schema`, `clip profiles`, `clip sounds add|list`, `clip brand-preview <job> [--segment N]`, `clip render` flags `--recompose`, `--allow-brand-override`, `--no-music`, `--no-whoosh`, `--no-pop`, `--no-sting` (existing flags and `--only` unchanged). `clip fetch` also writes `title`, `channel`, `description`, `categories`, `tags` into `jobs/<id>/state.json` when yt-dlp returns them.

- [ ] **Step 1: Write failing host tests** for the argument parser and pure helpers only: `test_render_flags_parse`; `test_validate_all_segments_before_any_render` (a bad style in segment 3 raises before anything is rendered, using a stub renderer) **RF3**; `test_no_music_flag_overrides_style`; `test_schema_command_prints_json`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_cli -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Render flow: load brand and profiles, resolve and validate every segment's style first, then pass 1 (SupoClip `create_video_clips`, `add_subtitles=False`, segments with `hook_title=None`) writing `jobs/<id>/pass1/NN.mp4` and `pass1/manifest.json` (clip path, `keep_ranges`, source path, duration, hook title, key words, style), then pass 2 per clip into `out/<id>/NN_*.mp4`, then `credits.txt`, then `manifest.json` as today. `--recompose` skips pass 1 and reads the manifest. Update `clip` wrapper with `-v "$HERE/clipwright":/app/clipwright:ro`. Metadata in `fetch` comes from yt-dlp `extract_info(download=False)`, wrapped so any failure leaves the fields out.
- [ ] **Step 4: Run** host tests. Expected: PASS. Run `./clip schema | python3 -m json.tool >/dev/null && echo ok`. Expected: `ok`.
- [ ] **Step 5: Commit** `feat: CLI for styles, sounds, recompose and brand preview`.

### Task 7: Docs, skill and spec fix

**Files:**
- Modify: `skill/SKILL.md`, `README.md`, `docs/superpowers/specs/2026-11-02-clipwright-brand-and-sound-design.md`, `.gitignore`

- [ ] **Step 1: Spec fix.** Remove `duck_db` from the `brand.json` example and the `mix` description, state that ducking constants live in `compose.py`, and move the handle to 0.84 of frame height in sections 5.3 and 5.5.
- [ ] **Step 2: Skill.** Add to `skill/SKILL.md`: how to read `state.json` metadata, the profile-selection guidance (spec 4.4 table and the examples: commentary gets `explainer`, music gets `performance` with `source_music` when lyrics appear), how to write `key_words` and `style`, running `clip schema` and `clip profiles`, and the preview-and-recompose loop. Then regenerate the installed copy with the `sed` line from `setup.sh`.
- [ ] **Step 3: README.** Add sections on `brand.json`, profiles, per-clip styles, the sounds library and licences, and the new commands. Commit the earlier uncommitted `--only` work with it.
- [ ] **Step 4: Verify** that no em dash (U+2014) remains in `README.md`, `skill/SKILL.md` or the spec (a `grep -c` for that character prints 0 for each), then **Commit** `docs: brand, profiles, sounds, skill guidance`.

### Task 8: Run all three cached videos

**Files:**
- Create (git-ignored): `jobs/jNQXAC9IVRw/segments.json` (update), `jobs/aMoVyJ9_M24/segments.json` (update), `jobs/nEaJMdM1djM/segments.json` (update)

- [ ] **Step 1: Add `key_words` and `style` blocks** to each job's `segments.json`. Commentary job `nEaJMdM1djM` uses `explainer`. Music job `aMoVyJ9_M24` uses `performance`, with `source_music: true` only where the segment contains song audio. Test job `jNQXAC9IVRw` uses `interview`.
- [ ] **Step 2: Render each job from its cached source and transcript** with `./clip render <job> /work/jobs/<job>/segments.json --exact`. No fetch is run.
- [ ] **Step 3: Verify every clip**: `ffprobe` shows 1080x1920 H.264 and AAC; extract a frame at 1.5 s and mid-clip and view them; loudness within 1 LU of -14 via `ebur128`; confirm the three jobs show visibly different resolved styles with the same accent, font and handle. Record timings for pass 1 and pass 2.
- [ ] **Step 4: Time `--recompose`** on one clip and confirm the spec's under-30-seconds estimate, or report the measured figure.
- [ ] **Step 5: Run full tests** (`python3 -m unittest discover -s tests -v` and `bash tests/container.sh`). Expected: all PASS. Report any failure plainly.
