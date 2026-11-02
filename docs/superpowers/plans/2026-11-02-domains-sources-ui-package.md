# Domains, source finding, review UI and upload package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (the user chose inline execution) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-domain skills (tech, health, mythology) whose verification gate `clip render` enforces, a `clip sources` finder, a local review UI with tracking, and a per-clip upload package (title, description, hashtags, cover).

**Architecture:** Domains are data (`domains/<name>.json`) read by two pure modules (`domains.py` loads and validates a pack, `gate.py` checks each segment's `verification` record against it). `clip.py` wires them into `fetch` and `render`. `sources.py`, `tracker.py` and `package.py` are pure stdlib modules, driven by new `clip sources` and `clip package` commands. The UI is a single FastAPI file with Jinja2 templates and a vendored HTMX, on the host, importing the same pure modules and calling `./clip` for anything that needs Docker.

**Tech Stack:** Python stdlib `unittest` for the pure modules (host tests), FastAPI + Jinja2 + HTMX + uvicorn for the UI (PEP 723 inline deps, run with `uv`), yt-dlp search (already in the runtime image), ffmpeg, existing SupoClip container.

**Spec:** none written, by the user's choice on 2026-11-02. The design agreed in conversation is the binding authority and is recorded under "Agreed design" below. Existing spec for the base system: `docs/superpowers/specs/2026-11-02-clipwright-brand-and-sound-design.md`.

**Branch:** `feat/domains-sources-ui`, created from `main` (4e79730) before Task 1. Do not push. Do not merge without asking.

## Agreed design (from the conversation, 2026-11-02)

- Three domains: `tech`, `health`, `mythology` (Hindu mythology, English or Hinglish). Clipping other people's videos stays; copyright and YouTube reused-content risk is the user's informed choice.
- One thin skill per domain (`clip-tech`, `clip-health`, `clip-mythology`) loading a pack; base skill `supoclip` stays the generic engine.
- The gate is enforced in code. Claude writes a `verification` object per segment; `clip render` refuses clips that fail their domain's checks, still renders the others, exits non-zero, and writes `out/<job>/verification.md`.
- Health: question kept with the answer (`framing_time` inside the clip), speaker and credential burned in on screen, disclaimer line burned in, clips 30 to 90 s, `risk_flags` recorded but not blocking. Tech: lighter (`claims_checked`, `speaker`, optional `dated_claims` flag). Mythology: `source_text`, `variant_note`, `verses_checked`, `respect_check`.
- Optional `commentary` (at most 140 characters) per segment, shown as a card in the title slot after the title ends. Recorded, never required.
- `clip sources <domain>`: no download, no API key; yt-dlp search; lists candidates with licence flag, ranked CC BY first, then watchlist channels, then views. User verifies permission.
- Local UI (FastAPI + Jinja2 + HTMX, `127.0.0.1:8770`): Sources tab (search, preview, approve or reject, permission, notes, copy fetch commands) and Clips tab (play clip, see verification record, human OK or Needs fix, edit title/description/hashtags, pick cover, build package). Status tracking from found to posted.
- Upload package per clip: title (up to 100 characters), description (credits and disclaimer appended automatically), 3 to 6 hashtags, three cover candidates, in `out/<job>/upload/NN_slug/`.

## Global Constraints

- Python via uv. Host tests: `python3 -m unittest discover -s tests -t .` from the repo root (stdlib only). UI tests need extra packages and run with `uv run --with fastapi --with httpx --with jinja2 --with python-multipart python3 -m unittest tests.test_ui`.
- Pure modules are stdlib only and importable on the host. Only `clip.py` may import SupoClip (`src.*`); it runs in the `clipwright-runtime` container via `./clip`.
- No file under `vendor/supoclip` is modified. No new Python packages in the container image.
- Domain names match `^[a-z0-9][a-z0-9-]*$`; the pack filename equals its `name`.
- User-facing text (skills, README, UI copy, error messages) has no em dashes.
- UI binds `127.0.0.1` only; no external scripts or styles (HTMX vendored); the only third-party embed is the youtube-nocookie player iframe, loaded on click.
- Tracker and sources data are git-ignored (`tracker/`, `sources/`), like `jobs/` and `out/`.
- Segment JSON is UTF-8 and is written with `ensure_ascii=False` wherever this plan writes JSON that may carry user text.
- Commit footer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A segment whose `verification` is missing, `null`, a string or a list must be blocked with a message, never crash the gate or slip through. (Task 2)
2. `framing_time` exactly at the clip start (allowed), exactly at the end (blocked), unparseable (`"abc"`) and absent (blocked with the field named). (Task 2)
3. A job with no `domain` in `state.json` renders exactly as before; an unknown `--domain` fails at fetch listing the available packs. (Task 4)
4. UI media route: `..`, encoded slashes, absolute paths, other extensions and other jobs' folders must all be refused; tracker file corrupt or half-written must not lose data. (Tasks 6, 9)
5. Sources: the same video from two queries appears once; entries lacking `view_count` or `duration`, and one failed enrichment lookup, must not stop the run. (Task 7)
6. Package: hashtags without `#`, a 101-character title, a missing description, non-ASCII text (Hinglish with accents, Devanagari) preserved byte for byte, a clip with no title skipped with a warning while the others are packaged. (Task 8)

## File Structure

- Create `clipwright/domains.py`, `clipwright/gate.py`, `clipwright/tracker.py`, `clipwright/sources.py`, `clipwright/package.py`.
- Create `domains/tech.json`, `domains/health.json`, `domains/mythology.json`.
- Create `skill/domains/{tech,health,mythology}/SKILL.md`.
- Create `ui/app.py`, `ui/templates/*.html`, `ui/static/app.css`, `ui/static/htmx.min.js`, `clip-ui`.
- Modify `clipwright/compose.py` (title window helper, overlay ASS, `compose_clip(overlays=)`), `clipwright/pipeline.py` (parser: `fetch --domain`, `domains`, `sources`, `package`), `clip.py` (wiring), `setup.sh` (install domain skills), `skill/SKILL.md`, `README.md`, `.gitignore`.
- Tests: `tests/test_domains.py`, `test_gate.py`, `test_overlays.py`, `test_tracker.py`, `test_sources.py`, `test_package.py`, `test_domain_skills.py`, `test_ui.py`, additions to `test_cli.py`; container tests `tests/container/test_domains.py`, `test_package.py`.

---

### Task 1: Domain packs and loader

**Files:**
- Create: `clipwright/domains.py`, `domains/tech.json`, `domains/health.json`, `domains/mythology.json`
- Test: `tests/test_domains.py`

**Interfaces:**
- Produces: `class DomainError(ValueError)`; `load_pack(name: str, directory: Path) -> Dict[str, Any]` (validates, raises `DomainError` listing every problem); `list_packs(directory: Path) -> List[str]` (sorted names).
- Pack shape: `{"name", "description", "clip_seconds": {"min": int, "max": int}, "verification": {"text": [str], "true": [str], "time_inside": [str], "flags": [str]}, "overlays": {"speaker": bool, "disclaimer": str | null}, "sources": {"queries": [str], "watchlist": [str], "min_minutes": int, "min_views": int, "max_age_days": int | null, "per_query": int}}`. Unknown keys are errors.

- [ ] **Step 1: Write the failing tests** in `tests/test_domains.py`: `test_shipped_packs_load` (tech, health, mythology load and `pack["name"] == name`); `test_health_pack_values` (`clip_seconds == {"min": 30, "max": 90}`, `verification["text"] == ["speaker", "credential", "context_excerpt"]`, `["true"] == ["context_checked"]`, `["time_inside"] == ["framing_time"]`, `["flags"] == ["risk_flags"]`, `overlays == {"speaker": True, "disclaimer": "General information, not medical advice."}`); `test_tech_pack_values` (`text == ["speaker"]`, `true == ["claims_checked"]`, `flags == ["dated_claims"]`, `clip_seconds.min == 15`, speaker overlay False, disclaimer None); `test_mythology_pack_values` (`text == ["source_text", "variant_note"]`, `true == ["verses_checked", "respect_check"]`, `clip_seconds == {"min": 20, "max": 75}`); `test_unknown_domain_lists_available` (message equals `unknown domain 'nope'; available: health, mythology, tech`); `test_bad_name_rejected` (`"../x"` raises `DomainError`); `test_invalid_pack_reports_every_problem` (temp dir pack with `clip_seconds` min 90 max 30, `queries` not a list, an unknown key: one `DomainError` whose text mentions all three); `test_name_must_match_filename`; `test_list_packs_sorted`.
- [ ] **Step 2: Run to verify failure.** Run: `python3 -m unittest tests.test_domains -v`. Expected: ImportError / ModuleNotFoundError for `clipwright.domains`.
- [ ] **Step 3: Implement `clipwright/domains.py`** with the signatures above. Validate with explicit checks (no jsonschema dependency); collect all problems into one message.
- [ ] **Step 4: Write the three pack files.** Health: `clip_seconds` 30 to 90, verification as in the test, overlays as in the test, sources `queries` ["doctor explains podcast", "cardiologist interview", "nutrition science podcast", "psychiatrist interview mental health", "sleep science podcast"], `watchlist` [], `min_minutes` 20, `min_views` 20000, `max_age_days` 730, `per_query` 10. Tech: 15 to 60 s, queries ["AI founder interview", "startup founder podcast", "machine learning researcher interview", "software engineering podcast", "AI agents explained"], `min_minutes` 15, `min_views` 10000, `max_age_days` 365, `per_query` 10. Mythology: 20 to 75 s, queries ["Ramayana explained", "Mahabharata story podcast", "Hindu mythology explained", "Puranas stories explained", "Bhagavad Gita explained"], `min_minutes` 15, `min_views` 20000, `max_age_days` null, `per_query` 10. Each has a one-sentence `description`.
- [ ] **Step 5: Run to verify pass.** Run: `python3 -m unittest tests.test_domains -v` then the full suite `python3 -m unittest discover -s tests -t .`. Expected: all pass (204 existing plus new).
- [ ] **Step 6: Commit.** `git add clipwright/domains.py domains tests/test_domains.py && git commit -m "feat: domain packs (tech, health, mythology) and loader"` with the footer.

---

### Task 2: Verification gate

**Files:**
- Create: `clipwright/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `layout.parse_time(str) -> float` (raises `ValueError`), pack dict from Task 1.
- Produces, all pure:
  - `COMMENTARY_MAX = 140`
  - `check_segment(pack: Optional[Dict], segment: Dict, number: int) -> List[str]`: problems, each starting `segment {number}:`. With `pack=None` only `commentary` is checked.
  - `check_all(pack: Optional[Dict], segments: Sequence[Dict]) -> Dict[int, List[str]]` (1-based, only segments with problems).
  - `partition(pack, segments, indexes: Sequence[int]) -> Tuple[List[int], Dict[int, List[str]]]` (allowed indexes in order, blocked map for the selected ones).
  - `overlays_for(pack: Optional[Dict], segment: Dict) -> Dict[str, str]`: keys `speaker` (`"{speaker}, {credential}"`, only if the pack's `overlays.speaker` and both fields are non-empty), `commentary`, `disclaimer` (from the pack), present only when applicable.
  - `report_markdown(pack: Dict, segments: Sequence[Dict], blocked: Dict[int, List[str]]) -> str`.

- [ ] **Step 1: Write the failing tests** in `tests/test_gate.py` with fixture helpers `health_segment(**over)` (start `00:12`, end `00:58`, verification: speaker "Dr Rao", credential "cardiologist", context_excerpt "the doctor adds this applies only to adults", context_checked True, framing_time `00:15`, risk_flags []), `tech_segment`, `myth_segment`. Tests: `test_complete_health_segment_passes`; `test_missing_verification_blocked` and `test_verification_wrong_type_blocked` (None, "ok", `[]`: problem text contains `segment 2` and `verification`; no exception); `test_blank_text_field_blocked` (whitespace `speaker` names `speaker`); `test_true_field_must_be_exactly_true` (`"yes"` and `1` blocked); `test_framing_inside_clip` (`00:12` allowed, `00:58` blocked, `00:05` blocked, `"abc"` blocked, absent blocked; each message names `framing_time`); `test_duration_bounds` (health 20 s blocked with `30-90`, 100 s blocked, 30 s and 90 s pass); `test_tech_light_gate` (18 s with only speaker and `claims_checked` passes; 10 s blocked); `test_mythology_requires_all_four`; `test_commentary_limit` (140 characters passes, 141 blocked, non-string blocked, absent passes; also with `pack=None`); `test_flags_must_be_list_of_strings` (absent passes); `test_partition_respects_indexes` (blocked map only has selected indexes; allowed keeps order); `test_overlays_for_health` (speaker line `Dr Rao, cardiologist`, disclaimer text, commentary included when set); `test_overlays_for_tech_has_no_speaker_or_disclaimer`; `test_overlays_for_none_pack_only_commentary`; `test_report_lists_each_clip` (contains `BLOCKED` and the problem text for a blocked clip, `OK` for a passing one, the flag values, the commentary, and the `context_excerpt`).
- [ ] **Step 2: Run to verify failure.** Run: `python3 -m unittest tests.test_gate -v`. Expected: ModuleNotFoundError for `clipwright.gate`.
- [ ] **Step 3: Implement `clipwright/gate.py`.** Duration is `parse_time(end) - parse_time(start)` checked against `pack["clip_seconds"]` inclusive; `time_inside` fields must satisfy `start <= t < end`; every failure message names the field and the rule (for example `segment 3: framing_time 00:58 is not inside the clip (00:12 to 00:58); include the question that frames the answer`). Unparseable segment times add a problem and skip the dependent checks.
- [ ] **Step 4: Run to verify pass.** Same command, then the full suite. Expected: all pass.
- [ ] **Step 5: Commit.** `feat: verification gate (check, partition, overlays, report)`.

---

### Task 3: On-screen overlays (speaker, commentary, disclaimer)

**Files:**
- Modify: `clipwright/compose.py`
- Test: `tests/test_overlays.py`; container check in `tests/container/test_domains.py` (created here, extended in Task 4)

**Interfaces:**
- Consumes: existing `title_ass`, `ass_color`, `ass_time`, `_escape`, `HANDLE_X`, `HANDLE_Y`, `TITLE_SIDE_MARGIN`.
- Produces:
  - `title_window(title: Dict[str, Any], duration: float) -> Tuple[float, float]`: the existing start/end rule (`(0.0, duration)` when `duration <= 0.8`, else `(TITLE_START, min(title["seconds"], max(TITLE_MIN_SECONDS, duration - TITLE_END_MARGIN)))`); `title_ass` is refactored to use it with unchanged output.
  - `overlay_ass(style: Dict[str, Any], duration: float, font_name: str, overlays: Dict[str, str], width: int = WIDTH, height: int = HEIGHT) -> Optional[str]`: `None` when `overlays` is empty or yields no event.
  - `compose_clip(..., overlays: Optional[Dict[str, str]] = None)`: writes `<stem>.overlay.ass` and appends it to `ass_files` when `overlay_ass` returns text.
- Placement rulings (verify visually in Step 6): speaker line top-left, anchor `\an7`, `\pos(60, round(0.015*height))`, 34 px, shown 0 to `min(6, duration)`; commentary in the title slot: starts at `title_window(...)[1]`, ends at `min(start + 5, duration - 0.2)`, dropped when shorter than 1.0 s, box style (BorderStyle 3, semi-opaque dark box, white text, not uppercased), `\an7\pos(60, round(height * title["top"]))`, 46 px, wrapped by `_balance` to at most 3 lines; disclaimer right-aligned `\an3\pos(width - HANDLE_X, round(height * HANDLE_Y))`, 28 px, whole clip, `\alpha&H30&`.

- [ ] **Step 1: Write the failing tests** in `tests/test_overlays.py`: `test_title_window_values` (duration 0.5 gives `(0.0, 0.5)`; duration 20 with seconds 4 gives `(0.1, 4.0)`; duration 3 gives `(0.1, 2.7)`); `test_title_ass_unchanged` (output for a fixed style and text equals a stored literal captured from the pre-refactor function in the same test run, written as an exact expected string); `test_empty_overlays_none`; `test_speaker_event` (one `Dialogue` with `Speaker` style, text `Dr Rao, cardiologist`, start `0:00:00.00`, end `0:00:06.00` for a 20 s clip, `\pos(60,29)` at height 1920); `test_disclaimer_event` (whole duration, `\an3`, `\pos(1040,1613)`); `test_commentary_starts_when_title_ends` (20 s clip: start `0:00:04.00`, end `0:00:09.00`); `test_commentary_dropped_when_no_room` (duration 4.5, seconds 4: no commentary event, `overlay_ass` returns `None` if nothing else); `test_special_characters_escaped` (`{x}` and a backslash do not appear raw inside the event text); `test_non_ascii_kept` (`Rāma ko kahānī` and `राम` present in the output string).
- [ ] **Step 2: Run to verify failure.** Run: `python3 -m unittest tests.test_overlays -v`. Expected: AttributeError / import failures for `title_window` and `overlay_ass`.
- [ ] **Step 3: Implement** `title_window`, refactor `title_ass` to call it, add `overlay_ass` and the `compose_clip` parameter. Use font style names `Speaker`, `Commentary`, `Disclaimer` in a header built like `title_ass`'s.
- [ ] **Step 4: Run host tests.** `python3 -m unittest discover -s tests -t .`. Expected: all pass, including the existing title tests.
- [ ] **Step 5: Container check.** Create `tests/container/test_domains.py` with `OverlayRenderTest.test_overlays_change_the_frame`: compose the cached test clip twice (with and without overlays `{"speaker": "Dr Rao, cardiologist", "disclaimer": "General information, not medical advice."}`), extract the frame at 0.5 s of each, and assert the top band (rows 0 to 120) and the handle-row band differ. Run: `tests/container.sh` (start rootless Docker first if it is not up; see memory `rootless-docker-setup`). Expected: pass.
- [ ] **Step 6: Visual check.** Render one overlay clip to the scratchpad, read frames at 0.5 s, 5 s and 8 s, and confirm the speaker line does not touch the title box, the commentary sits in the title slot, and the disclaimer shares the handle's row without overlapping it. Adjust px and positions in `compose.py` (not the tests' relational expectations) if not.
- [ ] **Step 7: Commit.** `feat: speaker, commentary and disclaimer overlays`.

---

### Task 4: Wire domains and the gate into the CLI

**Files:**
- Modify: `clipwright/pipeline.py` (parser), `clip.py`, `tests/test_cli.py`
- Test: `tests/test_cli.py`, `tests/container/test_domains.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces: `fetch --domain NAME`; `domains` command (prints each pack's name, description, required verification keys and overlays); `state.json["domain"]`; `render` enforces `gate.partition` (always, `pack=None` when the job has no domain); `out/<job>/verification.md` written when the job has a domain; `_compose_one(..., pack)` passes `gate.overlays_for(pack, seg)` to `compose.compose_clip`.

- [ ] **Step 1: Write failing parser tests** in `tests/test_cli.py`: `fetch URL --domain health` parses `domain == "health"`; `fetch URL` has `domain is None`; `domains` parses as `cmd == "domains"`.
- [ ] **Step 2: Run to verify failure.** `python3 -m unittest tests.test_cli -v`. Expected: the new tests fail (unrecognized argument / invalid choice).
- [ ] **Step 3: Implement parser changes** in `pipeline.build_parser`, then re-run: new tests pass.
- [ ] **Step 4: Implement `clip.py` wiring.** `DOMAINS = WORK / "domains"`. `fetch`: when `--domain` is given, `domains.load_pack` it (on `DomainError` exit with its message), store `"domain"` in `state`, print `domain=<name>`. `domains` command prints the packs. `render`: load the pack from `state.get("domain")`; after `indexes` are validated call `allowed, blocked = gate.partition(pack, segments, indexes)`; print each blocked problem to stderr; if `pack`, write `out_dir/verification.md` from `gate.report_markdown(pack, segments, gate.check_all(pack, segments))`; if `allowed` is empty exit with `Nothing was rendered: every selected clip failed the {domain or "commentary"} gate.`; render only `allowed`; at the end exit non-zero naming blocked and failed segments together. Add `DomainError` to the caught exceptions in `main`. Add the pack to `_compose_one` and pass overlays.
- [ ] **Step 6: Container tests** in `tests/container/test_domains.py` (class `GateRenderTest`, temp job under `/work/jobs/gate-test`, removed in `tearDownClass`, source = cached `jNQXAC9IVRw` video, run `python /work/clip.py render ...` through `subprocess` with `PYTHONPATH=/work:/app`): `test_missing_verification_renders_nothing` (state domain `tech`, segment without `verification`: exit code non-zero, output mentions `tech gate`, no `.mp4` in `out/gate-test`); `test_verified_clip_renders_with_report` (segment `00:00` to `00:17` with `verification: {"speaker": "Jawed", "claims_checked": true}` and `commentary: "The first video ever uploaded."`: exit 0, one clip, `verification.md` contains `OK`); `test_job_without_domain_unchanged` (no `domain` in state: renders as before).
- [ ] **Step 7: Run everything.** `python3 -m unittest discover -s tests -t .` then `tests/container.sh`. Expected: all pass. Look at one frame of the rendered clip at 6 s to confirm the commentary card shows.
- [ ] **Step 8: Commit.** `feat: fetch --domain, domains command and gate enforcement in render`.

---

### Task 5: Domain skills

**Files:**
- Create: `skill/domains/tech/SKILL.md`, `skill/domains/health/SKILL.md`, `skill/domains/mythology/SKILL.md`
- Modify: `setup.sh`, `skill/SKILL.md`
- Test: `tests/test_domain_skills.py`

**Interfaces:**
- Consumes: pack verification keys (Task 1).
- Produces: installed skills `~/.claude/skills/clip-<domain>/SKILL.md` (placeholder `__CLIP_DIR__` replaced by `sed`, as for the base skill).

- [ ] **Step 1: Write the failing test** `tests/test_domain_skills.py`: for each domain `d`: the skill file exists; frontmatter has `name: clip-{d}` and a `description:` line; the text contains `__CLIP_DIR__`, `clip fetch --domain {d}`, and every key from the pack's `verification.text`, `.true`, `.time_inside`, `.flags` and (when set) the disclaimer text; it names `supoclip` as the base skill; it contains no em dash (U+2014). A second test asserts `setup.sh` mentions `skill/domains`.
- [ ] **Step 2: Run to verify failure.** `python3 -m unittest tests.test_domain_skills -v`. Expected: file-not-found failures.
- [ ] **Step 3: Write the three skills.** Each: when to use (trigger phrases, such as "clip this health podcast"); steps (run `clip sources <domain>` or take the user's URLs, `clip check`, `clip fetch --domain <d> <url>`, then follow the base skill `supoclip` for transcript reading, `clip frames`, layout, `segments.json` and render); the domain's selection rules; the exact `verification` keys to write per segment and how to fill each one honestly. Required content: **health**: only clips where the question or setup that frames the answer is inside the clip (`framing_time` is that moment); read at least two minutes of transcript on each side before choosing, and put the qualifying sentence in `context_excerpt` (or `none needed: <why>`); never clip a bare one-line quote; list dosage, treatment, stop-medication and cure content in `risk_flags` and tell the user which clips carry flags; `speaker` and `credential` come from the video's description or on-screen text, never guessed (ask the user when unknown); the disclaimer and speaker line are burned in automatically. **tech**: check every number, date, funding figure and product claim against the transcript, set `claims_checked` true only after doing so, put `dated_claims` in `flags` when a claim will go stale, name the speaker as the video does. **mythology**: name the scripture or tradition in `source_text` (or `folk or regional tradition`), say in `variant_note` when versions differ (or `no known variants`), check quoted verses and set `verses_checked` true only after (true also when no verse is quoted), set `respect_check` true only when the clip does not mock a community or deity and frames belief as "according to tradition". All three: `commentary` is optional, at most 140 characters, one line of the user's own context.
- [ ] **Step 4: Update `setup.sh`** to install each `skill/domains/<d>/SKILL.md` to `~/.claude/skills/clip-<d>/SKILL.md` with the same `sed`. Update `skill/SKILL.md` with a "Domains" section (which skill to use, `--domain`, the `verification` object, `commentary`) and the new segment fields in its schema block.
- [ ] **Step 5: Run to verify pass.** Domain-skill test and the full suite. Expected: all pass.
- [ ] **Step 6: Install and check.** Run the install part of `setup.sh` (or its `sed` lines by hand) and confirm `~/.claude/skills/clip-health/SKILL.md` exists with the repo path substituted.
- [ ] **Step 7: Commit.** `feat: clip-tech, clip-health and clip-mythology skills`.

---

### Task 6: Tracker

**Files:**
- Create: `clipwright/tracker.py`
- Modify: `.gitignore` (add `tracker/` and `sources/`)
- Test: `tests/test_tracker.py`

**Interfaces:**
- Produces, pure and stdlib only:
  - `SOURCE_STATUSES = ("found", "approved", "rejected", "fetched", "clipped", "verified", "posted")`, `PERMISSIONS = ("unchecked", "asked", "granted", "cc")`, `CLIP_MARKS = ("ok", "fix")`
  - `class TrackerError(ValueError)`
  - `load(path: Path) -> Dict` (`{"sources": {}, "clips": {}}` when missing; `TrackerError` naming the path when unreadable JSON), `save(path: Path, state: Dict) -> None` (write temp file in the same folder then `os.replace`)
  - `upsert_source(state, cand: Dict, domain: str, now: str) -> Dict` (new ids get `status "found"`, `permission "unchecked"`, empty note; existing ids keep status, permission and note, and only refresh metadata)
  - `set_source(state, video_id: str, *, status=None, permission=None, note=None, now: str) -> Dict` (validates; unknown id raises)
  - `rejected_ids(state) -> Set[str]`
  - `set_clip(state, job: str, number: int, *, mark=None, note=None, posted: Optional[Dict] = None, now: str) -> Dict` (key `f"{job}/{number:02d}"`; `posted` is `{"platform", "url"}`)
  - `sync_statuses(state, jobs: Dict[str, Dict]) -> None`: `jobs[video_id] = {"fetched": bool, "clips": int, "verified": bool}`; only advances along `SOURCE_STATUSES` order, never touches `rejected`.

- [ ] **Step 1: Write the failing tests** in `tests/test_tracker.py`: `test_load_missing_is_empty`; `test_round_trip`; `test_save_is_atomic` (patch `os.replace` to raise, existing file content unchanged and no temp file left); `test_corrupt_file_names_path`; `test_upsert_keeps_user_edits` (approve, add a note, upsert again with new view count: status, permission and note kept, views updated); `test_invalid_values_rejected` (status, permission, mark); `test_unknown_source_raises`; `test_rejected_ids`; `test_sync_advances_only` (found becomes fetched, `clips` > 0 becomes clipped, verified flag becomes verified, posted stays posted, rejected stays rejected, approved is not downgraded by `fetched: False`); `test_set_clip_keys_and_posted`; `test_non_ascii_note_round_trips`.
- [ ] **Step 2: Run to verify failure.** `python3 -m unittest tests.test_tracker -v`. Expected: ModuleNotFoundError.
- [ ] **Step 3: Implement `clipwright/tracker.py`**; `save` writes `ensure_ascii=False, indent=2`.
- [ ] **Step 4: Run to verify pass**, then the full suite.
- [ ] **Step 5: Commit.** `feat: tracker (sources and clip status, atomic JSON store)`.

---

### Task 7: `clip sources`

**Files:**
- Create: `clipwright/sources.py`
- Modify: `clipwright/pipeline.py` (parser), `clip.py`
- Test: `tests/test_sources.py`, additions to `tests/test_cli.py`

**Interfaces:**
- Consumes: pack `sources` rules (Task 1), `licence.classify`, `tracker.rejected_ids`.
- Probe facts (verified 2026-11-02 with yt-dlp `extract_flat`): flat search entries carry `id`, `title`, `channel`, `uploader`, `channel_id`, `duration` (seconds), `view_count`, `url`; they have no `upload_date`, `license` or follower count. A full lookup (about 3.5 s each) adds `license`, `upload_date` (`YYYYMMDD`), `channel_follower_count`.
- Produces, pure and stdlib only:
  - `candidate_from_flat(entry: Dict) -> Optional[Dict]` (`{"id","title","channel","channel_id","duration","views","url"}`; `None` without an id)
  - `prefilter(cands: Sequence[Dict], rules: Dict, seen: Set[str], watchlist: Sequence[str]) -> List[Dict]` (dedupe by id, drop seen ids, drop duration below `min_minutes * 60` or `None`, drop views below `min_views` or `None` unless the channel is on the watchlist; sets `watchlist: bool`)
  - `enrich(cand: Dict, info: Optional[Dict], today: date) -> Dict` (adds `license_kind`, `license_label`, `reuse_ok`, `upload_date`, `age_days`, `followers`; with `info=None` sets `license_kind "unchecked"` and label `Licence not checked`)
  - `postfilter(cands, rules) -> List[Dict]` (drop when `age_days` exceeds `max_age_days`; unknown age is kept)
  - `rank(cands) -> List[Dict]` (tier 0 CC BY, tier 1 watchlist, tier 2 rest; then views descending)
  - `to_markdown(domain: str, cands: Sequence[Dict], generated: str) -> str`, `to_json(cands) -> str` (UTF-8, `ensure_ascii=False`)
- CLI: `clip sources <domain> [--query Q ...] [--limit N]` runs inside the container; searches `ytsearch{per_query}:{query}` for each pack query plus `--query` extras, and channel URLs in `watchlist` as flat playlists (plain-text watchlist entries are searched by name); `seen` is the folder names under `jobs/` plus `tracker.rejected_ids`; enrichment of the top 24 by (watchlist, views) uses a thread pool of 4, one failure leaves that candidate unenriched; writes `sources/<domain>.json` and `sources/<domain>.md`; prints the count and the top five.

- [ ] **Step 1: Write the failing tests** in `tests/test_sources.py` using a fixture entry copied from the probe (`id TBMMR7GBIKA`, `duration 8680`, `view_count 5693697`, channel and url as probed): `test_candidate_from_flat_maps_fields`; `test_candidate_without_id_is_none`; `test_prefilter_dedupes_across_queries`; `test_prefilter_drops_seen_short_and_low_views`; `test_prefilter_keeps_missing_views_only_for_watchlist`; `test_missing_duration_dropped`; `test_enrich_cc_by_flags_reuse_ok` (`info["license"] = "Creative Commons Attribution license (reuse allowed)"`); `test_enrich_without_info_is_unchecked`; `test_age_days_from_upload_date`; `test_postfilter_age_and_unknown_age`; `test_rank_order` (cc-by first, then watchlist, then by views); `test_markdown_rows` (title, channel, URL, duration as `H:MM`, views, licence label and `permission: unchecked` appear; health output also contains a line telling the user to check the speaker's credentials); `test_json_round_trip_non_ascii`. Parser tests in `tests/test_cli.py`: `sources health --limit 5 --query "x" --query "y"` parses; `sources` without a domain fails.
- [ ] **Step 2: Run to verify failure.** `python3 -m unittest tests.test_sources tests.test_cli -v`. Expected: ModuleNotFoundError and parser failures.
- [ ] **Step 3: Implement `clipwright/sources.py`** and the parser entry.
- [ ] **Step 4: Implement `sources_command` in `clip.py`** using `yt_dlp` (flat search, then full lookup per enriched candidate); catch per-query failures and print them to stderr without stopping.
- [ ] **Step 5: Run host tests**, then a live run: `./clip sources tech --limit 3` (start Docker first). Expected: `sources/tech.json` and `sources/tech.md` exist, at least one row, CC BY rows (if any) first. Read the markdown and check titles, channels and the licence column look sane. Report honestly if search returns nothing.
- [ ] **Step 6: Commit.** `feat: clip sources (domain video search with licence flag and ranking)`.

---

### Task 8: Upload package

**Files:**
- Create: `clipwright/package.py`
- Modify: `clipwright/pipeline.py` (parser), `clip.py`
- Test: `tests/test_package.py`, `tests/container/test_package.py`, parser tests in `tests/test_cli.py`

**Interfaces:**
- Consumes: segment fields `title`, `description`, `hashtags`, `thumbnail_time` (Claude writes them), `jobs/<job>/post_edits.json` (`{"<n>": {"title", "description", "hashtags", "cover"}}`, written by the UI), `state.json` (`source`, `title`, `channel`, `attribution`), pack overlays, `out/<job>/manifest.json`.
- Produces, pure and stdlib only:
  - `TITLE_MAX = 100`, `HASHTAG_MIN, HASHTAG_MAX = 3, 6`
  - `check_post(segment: Dict, number: int) -> List[str]` (title non-empty and at most 100 characters, description non-empty, hashtags a list of 3 to 6 strings each matching `^#\w+$` with Unicode word characters, `thumbnail_time` a non-negative number when present)
  - `merge_edits(segment: Dict, edits: Optional[Dict]) -> Dict` (edits win for `title`, `description`, `hashtags`; `cover` in `a|b|c` carried through)
  - `build_post(segment: Dict, *, state: Dict, pack: Optional[Dict], credits: Sequence[str]) -> Dict` returning `{"title", "description", "hashtags", "caption"}`; `description` = the written description, a blank line, a source line (`Source: {title} by {channel}, {url}`; for a CC BY source the `state["attribution"]` line instead), a `Sound: ...` line per credit, the pack disclaimer when set, a blank line, then the hashtags joined by spaces; `caption` = title, blank line, the first five hashtags
  - `post_text(post: Dict) -> str` (copy-paste text with labelled sections)
  - `cover_times(duration: float, chosen: Optional[float]) -> List[float]` (three candidate times: `[clamp(chosen or 1.5, 0.2, duration - 0.2), duration * 0.4, duration * 0.75]`, each rounded to 2 places)
  - `slug(title: str, number: int) -> str` (`f"{number:02d}_{ascii-slug}"`, at most 40 characters, `clip` when empty)
  - `frame_args(video: str, t: float, out: str) -> List[str]` (`ffmpeg -y -v error -ss T -i VIDEO -frames:v 1 -q:v 2 OUT`)
  - `write_clip_package(folder: Path, video: Path, post: Dict, times: Sequence[float], cover: str, run=subprocess.run) -> None` (copies the video to `video.mp4`, writes `cover_a/b/c.jpg` through `run(frame_args(...))`, copies the chosen one to `cover.jpg`, writes `post.txt` and `post.json` with `ensure_ascii=False`)
- CLI: `clip package <job> [--segments PATH]` builds `out/<job>/upload/NN_slug/` for every clip in the manifest, writes `out/<job>/upload/README.md` (clips in suggested posting order with the permission reminder for non-CC sources), skips clips with problems (warning per clip) and exits non-zero if any were skipped.

- [ ] **Step 1: Write the failing tests** in `tests/test_package.py`: `test_check_post_ok`; `test_title_limit` (100 passes, 101 blocked); `test_hashtags_rules` (missing `#`, 2 tags, 7 tags, a tag with a space, `#राम` accepted); `test_missing_description_blocked`; `test_bad_thumbnail_time`; `test_merge_edits_wins`; `test_build_post_description_order` (written text, then source line, then sound credits, then disclaimer, then hashtags, in that order); `test_cc_by_uses_attribution_line`; `test_health_disclaimer_appended`; `test_caption_has_five_hashtags_at_most`; `test_cover_times` (duration 30, chosen None gives `[1.5, 12.0, 22.5]`; chosen 40 clamps to `29.8`); `test_slug` (`1`, `"Why Karna never..."`, empty title, Devanagari-only title gives `01_clip`); `test_frame_args_exact`; `test_write_clip_package_files` (fake `run` that touches the output path: folder holds `video.mp4`, three covers, `cover.jpg`, `post.txt`, `post.json`; `post.json` round-trips Hinglish text `Rāma aur Sītā ki kahānī` unchanged). Parser tests: `package job1 --segments s.json`.
- [ ] **Step 2: Run to verify failure.** `python3 -m unittest tests.test_package tests.test_cli -v`. Expected: ModuleNotFoundError.
- [ ] **Step 3: Implement `clipwright/package.py`**, the parser entry, and `package_command` in `clip.py` (reads manifest, segments, `post_edits.json`, `credits.txt` lines per clip from the manifest entry's `credits`).
- [ ] **Step 4: Container test** `tests/container/test_package.py`: make a 3 s test clip with ffmpeg lavfi, call `write_clip_package` for real, assert the three covers exist, are JPEGs of the clip's size, and differ from each other.
- [ ] **Step 5: Run everything**, then run `./clip package` on a rendered job with fixture `title`, `description`, `hashtags` added to a copy of its segments; look at one `cover.jpg` and read `post.txt`. Expected: files present, text correct, Hinglish intact.
- [ ] **Step 6: Commit.** `feat: clip package (title, description, hashtags, cover candidates per clip)`.

---

### Task 9: Review UI

**Files:**
- Create: `ui/app.py`, `ui/templates/base.html`, `ui/templates/sources.html`, `ui/templates/clips.html` (plus small partials), `ui/static/app.css`, `ui/static/htmx.min.js`, `clip-ui`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: `tracker`, `sources` (markdown not needed; reads `sources/<domain>.json`), `gate`, `package`, `domains`.
- Produces: `create_app(root: Path, runner: Callable[[List[str]], Dict] = default_runner) -> FastAPI`. `default_runner(args)` runs `[root/"clip", *args]` with `subprocess.run`, returns `{"code": int, "output": str}`. `app.py` carries a PEP 723 header with `fastapi`, `uvicorn`, `jinja2`, `python-multipart`; run as `uv run ui/app.py` (the `clip-ui` launcher does this) on `127.0.0.1:8770`.
- Routes: `GET /` redirects to `/sources`; `GET /sources?domain=` lists `sources/<domain>.json` joined with the tracker (domain tabs for tech, health, mythology; status filter; each row has click-to-load youtube-nocookie player, licence label, permission select, note, Approve and Reject buttons); `POST /sources/search` (form `domain`; starts `runner(["sources", domain])` in a background thread, one at a time, 409 partial when busy); `GET /sources/search/status` (polling partial); `POST /sources/{video_id}` (form `status` in found, approved, rejected only, `permission`, `note`; returns the updated row); `GET /sources/{domain}/commands` (partial with `./clip fetch --domain D URL` for each approved, not yet fetched, source); `GET /clips` (jobs found in `out/*/manifest.json`; per clip a player, the verification record from the job's `segments.json`, its gate problems, editable title, description and hashtags with live `package.check_post` problems, three cover candidates when a package exists, Mark OK and Needs fix buttons); `POST /clips/{job}/{n}/mark` (form `mark`, `note`); `POST /clips/{job}/{n}/post` (form `title`, `description`, `hashtags` split on whitespace or commas, `cover`; writes `jobs/<job>/post_edits.json` atomically, returns the clip partial); `POST /clips/{job}/package` (409 with the clip numbers when any clip in the manifest is not marked ok; otherwise `runner(["package", job])` and shows its output); `GET /media/{path:path}` serves only `.mp4` and `.jpg` under `root/out/`, every path part matching `^[\w.\-]+$`, resolved path checked to stay inside `out/`.
- Every page load calls `tracker.sync_statuses` from facts on disk (job folder present means fetched, manifest clip count, all clips marked ok means verified) and saves.

- [ ] **Step 1: Write the failing tests** in `tests/test_ui.py` (skip the module with `unittest.skipUnless(importlib.util.find_spec("fastapi") and importlib.util.find_spec("httpx"), ...)`; use `fastapi.testclient.TestClient` on a temp `root` laid out like the repo with a fixture `sources/tech.json` of two candidates, a fixture job with `out/J1/manifest.json`, two tiny `.mp4` files and `jobs/J1/{state.json,segments.json}`): `test_media_serves_clip_inside_out`; `test_media_refuses_traversal` (`/media/../jobs/J1/state.json`, `/media/%2e%2e/x.mp4`, `/media//etc/passwd`, `/media/J1/notes.txt`, a symlink pointing outside `out/`: each 404 or 400, never 200); `test_sources_page_lists_rows`; `test_approve_persists_in_tracker_file`; `test_invalid_status_rejected` (`fetched` is 400); `test_search_runs_one_at_a_time` (fake runner blocks on an event; second POST gets 409); `test_commands_partial_lists_approved_only`; `test_mark_ok_persists`; `test_package_refuses_unmarked_clips` (409 and the runner not called); `test_package_runs_when_all_marked` (runner called with `["package", "J1"]`); `test_post_edit_writes_file_and_reports_problems` (101-character title shows the problem text and the file still holds the edit; hashtags typed as `a, b c` are split but reported as missing `#`); `test_clip_page_shows_gate_problems` (job with domain health and no verification shows the blocked reason); `test_pages_load_no_external_assets` (every `<script src` and `<link href` starts with `/static/`; the string `youtube-nocookie.com` appears only inside a data attribute or click handler, not as a `src`).
- [ ] **Step 2: Run to verify failure.** `uv run --with fastapi --with httpx --with jinja2 --with python-multipart python3 -m unittest tests.test_ui -v`. Expected: ModuleNotFoundError for `ui.app` (add `ui/__init__.py` so the test imports `ui.app.create_app`).
- [ ] **Step 3: Vendor HTMX.** Download `htmx.org@2.0.4` `dist/htmx.min.js` into `ui/static/htmx.min.js` (for example `curl -sSL https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js -o ui/static/htmx.min.js`) and record its sha256 in a comment at the top of `ui/app.py`.
- [ ] **Step 4: Implement `ui/app.py`**, templates and CSS. CSS: colour tokens on `:root`, dark values under `prefers-color-scheme: dark`, explicit body background, readable at phone width, a visible focus state, status badges with text (not colour alone). Sources rows load the embedded player only on click; no inline event handlers that fetch remote assets on load.
- [ ] **Step 5: Run to verify pass** (the command from Step 2), then the full host suite (`ui` tests skip there). Expected: all pass.
- [ ] **Step 6: Launcher.** Write `clip-ui` (`#!/usr/bin/env bash`, `cd` to its own folder, `exec uv run ui/app.py`) and `chmod +x`.
- [ ] **Step 7: Live check.** Start `./clip-ui` in the background, `curl -s http://127.0.0.1:8770/sources?domain=tech` and `/clips`, fetch one media file with a `Range` header (expect 206 or 200), then stop the server. If a headless Chromium is installed, take a screenshot of both tabs at 1280 and 390 px widths and read them; if not, say so plainly in the report and do not claim a visual check.
- [ ] **Step 8: Commit.** `feat: local review UI (sources, clips, tracking, package build)`.

---

### Task 10: Docs and wrap-up

**Files:**
- Modify: `README.md`, `skill/SKILL.md`, memory `clipwright-project.md`
- Test: full suites

- [ ] **Step 1: README.** Add sections: Domains (the three packs, gates, `--domain`, `clip domains`, `verification.md`), Finding sources (`clip sources`, what it can and cannot tell you), Upload package (`clip package`, files, segment fields), Review UI (`./clip-ui`, the two tabs, where state lives, that it is local and unauthenticated, tests command), and the commands table. State the known limits plainly: gate records Claude's checks but cannot judge truth; Anton has no Devanagari glyphs, so Devanagari titles would not render (Hinglish in Latin script is fine); search results are what YouTube returns; Shorts cover upload support per platform is unverified; YouTube's reused-content policy applies even with permission and Shorts reach for clip-only channels is reduced (cite the YouTube Help page and the 2 October 2026 announcement as read on 2026-11-02).
- [ ] **Step 2: Base skill.** Make sure `skill/SKILL.md` documents `clip sources`, `clip package`, `./clip-ui`, and the segment fields `title`, `description`, `hashtags`, `thumbnail_time`, `commentary`, `verification`; re-run the `sed` install and confirm the installed copy matches.
- [ ] **Step 3: Full verification.** Run `python3 -m unittest discover -s tests -t .`, the UI tests command, and `tests/container.sh`. Expected: all pass; record the counts.
- [ ] **Step 4: Memory.** Update `clipwright-project.md` (new commands, packs, UI, test counts, what is unverified, branch state) and keep the `MEMORY.md` pointer line current.
- [ ] **Step 5: Commit.** `docs: README and skill for domains, sources, package and UI`.
- [ ] **Step 6: Final review** per the executing-plans skill (frontier model, whole branch), fix Critical and Important findings with failing tests first, ledger the minors, then use superpowers:finishing-a-development-branch. Ask before merging and before any push.
