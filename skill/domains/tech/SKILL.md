---
name: clip-tech
description: Use when the user wants to clip tech, AI, software or startup content ("clip this AI podcast", "find startup interviews to clip"). Applies the tech verification gate (claims checked, speaker named, dated claims flagged) on top of the supoclip clipping skill.
---

# Clipwright tech, AI and startup clips

This builds on the `supoclip` skill (fetch, frames, layout, style, segments.json, render): read that
for the common steps. Here is what changes for tech content. `clip render` enforces a light gate: a
clip without a complete `verification` record is not rendered.

## Steps

1. **Sources.** `__CLIP_DIR__/clip sources tech` (or the review UI, `__CLIP_DIR__/clip-ui`), or the user's URLs.
2. `__CLIP_DIR__/clip check <url>` for the licence, said in one line.
3. `__CLIP_DIR__/clip fetch --domain tech <url>`.
4. Read the transcript and `state.json`. Choose clips with the rules below. Podcasts and interviews fit
   the `interview` profile with `fill`; talks with slides fit `explainer` with `fit` or `auto`.
5. Write `segments.json` with a `verification` object on every segment, then render and read
   `out/<job>/verification.md`.

## Selection rules

- **Clip length is 15 to 60 seconds.**
- Pick a surprising claim, a concrete number, a prediction, a clear explanation or a candid story.
  Skip pleasantries, sponsor reads and a claim whose point depends on an earlier slide.
- A forecast or an opinion is fine, but the clip must not present it as settled fact if the speaker
  did not.
- Funding amounts, benchmark scores, dates, product names and version numbers must be exactly as spoken.

## The verification record

```json
"verification": {
  "speaker": "Jane Doe, CEO of Acme",
  "claims_checked": true,
  "dated_claims": ["valuation figure from March 2026"]
}
```

- `speaker`: who is talking, named as the video names them. Not blank.
- `claims_checked`: `true` only after you went through every number, date, funding figure and named
  product in the clip and confirmed it matches the transcript. If a claim looks wrong in the world, flag it
  to the user.
- `dated_claims`: a list of claims that will go stale (prices, versions, "the best model right now").
  Empty or omitted when none. It does not block the clip. The user decides whether to post it.

## Commentary (optional)

`"commentary": "..."` is one line of your own take or context, at most 140 characters, shown as a
card after the title. Optional. Useful for a one-line "why this matters".
