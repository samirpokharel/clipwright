# Decisions

One entry per decision, newest last. Each says what was decided, why, and what it depends on.
Add an entry whenever a name, a default, a rule or a tool choice is settled, so it is not re-decided from scratch.

## 2026-11-02: Overnight runs download on the host, never work around the bot check

The container's yt-dlp gets "Sign in to confirm you're not a bot". The rule is: download with yt-dlp on the host into `tmp/dl/`,
fetch the file as local, and if the host is blocked too, stop that video and report. No cookies, proxies, client tricks or patches.
Set in `tmp/overnight-goal.md`; followed on the first overnight run.

## 2026-11-03: A repo fix during an unattended run goes on a branch, test first, unmerged

The first overnight run found two bugs in `clip.py` (segment order lost after the opening review, layout clips capped at 60 s).
They were fixed on `fix/render-order-and-cap` (commit 980acae) with `tests/test_render_order.py` written first. Merging is Shrawan's call.
Until then the checkout stays on the fix branch so the container runs the fixed code.

## 2026-11-03: One channel per domain, with these handles

| Domain | Handle | Why |
|---|---|---|
| mythology | `@shlokaclips` | shloka means verse; matches the "verses checked" gate |
| tech | `@gradientcuts` | an AI training term that reads well in English |
| health | `@vagusclips` | the vagus nerve; matches the neuroscience content |

Chosen from 40 candidates. Every plain "X clips" or "X cuts" name (stackcuts, founderclips, vitalclips, pulseclips, healthcuts and
others) was already taken. A "katha" family (siliconkatha, swasthkatha, founderkatha) was free but every mythology katha handle was
taken, so the family idea was dropped. Full list in `tmp/handle-check.md` (not tracked).

## 2026-11-03: How handle availability is checked

YouTube: `GET https://www.youtube.com/@handle`, 200 means taken, 404 means free. TikTok: the oembed endpoint for the profile URL,
200 means taken, 400 means free. Both calibrated against a known channel and an impossible handle on 3 November 2026.
Instagram refuses unauthenticated lookups with a login wall and is checked by hand in the app; no workaround is attempted.
"Free" means free at check time. Nothing is reserved until the accounts are created.

## 2026-11-03: Brand identity lives per domain in the pack, over a shared brand.json

`brand.json` keeps the shared look (base style, mix) and the fallback identity. A pack's optional `brand` block may set any of
`handle`, `accent`, `text`, `outline`, `headline_font` and is laid over `brand.json` before validation for every render and
brand-preview of that domain. Jobs without a domain use `brand.json` alone. Chosen over separate brand files per domain because
the look is shared and only the identity differs. Branch `feat/per-domain-brand`.

## 2026-11-03: Clips already rendered get the real handle by recompose, not re-cut

The handle is drawn in pass 2 only, so `clip render <job> /work/jobs/<job>/segments.json --recompose` followed by `clip package`
is enough. The recompose cache compares times and layout only, so a handle change never forces a re-cut.

## 2026-11-03: Render caps follow the pack

Mythology clip 2 needed `--max-seconds 75` and the health clips `--max-seconds 90 --exact`; a plain `clip render` cuts them at
60 s. Open: make the renderer take the cap from the pack's `clip_seconds.max` so the flag is not needed. Not done yet.

## 2026-11-03: Facebook Pages join the platform set

Each domain also gets a Facebook Page with the same handle, under Shrawan's existing Meta profile, no new profile. Reason: a Reel
posted to Instagram cross-posts to the linked Page in one step, so it costs nothing per clip. YouTube channels are Brand Accounts
under one Google account; Instagram accounts are added under the same Meta profile; only TikTok needs a fresh account per channel,
signed up with a Gmail alias. Facebook handle availability is not checked unauthenticated; if taken, the fallback handle applies
to all four platforms of that domain. Runbooks RB-001 and RB-002 updated.
