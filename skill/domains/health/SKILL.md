---
name: clip-health
description: Use when the user wants to clip a healthcare, medicine, nutrition, mental health or fitness podcast or interview ("clip this health podcast", "find health videos to clip"). Applies the health verification gate (the question stays with the answer, speaker and credential on screen, disclaimer burned in, risky claims flagged) on top of the supoclip clipping skill.
---

# Clipwright healthcare clips

A professional's sentence cut out of its context can say the opposite of what they meant. This skill
exists to stop that. It builds on the `supoclip` skill (fetch, frames, layout, style, segments.json,
render): read that for the common steps. Everything here is what changes for health content.
`clip render` enforces the gate: a clip without a complete `verification` record is not rendered.

## Steps

1. **Sources.** Run `__CLIP_DIR__/clip sources health` (or use the review UI, `__CLIP_DIR__/clip-ui`), or take the
   user's URLs. The user checks permission and the speaker's credentials, not you.
2. `__CLIP_DIR__/clip check <url>` for the licence. Say it in one line.
3. `__CLIP_DIR__/clip fetch --domain health <url>`. The domain is stored with the job.
4. Read `jobs/<job>/transcript.txt` and `state.json`. Choose clips with the rules below. Use the
   `interview` profile for talking heads, and look at `clip frames` before choosing a layout.
5. Write `jobs/<job>/segments.json` with a `verification` object on every segment.
6. `__CLIP_DIR__/clip render <job> /work/jobs/<job>/segments.json`. Blocked clips are listed with the
   reason; fix them and render again with `--only N`. Read `out/<job>/verification.md`.
7. Tell the user which clips carry `risk_flags`, in plain words, before they post anything.

## Selection rules

- **Clip length is 30 to 90 seconds.** A short clip cannot carry its context.
- **Keep the question with the answer.** The clip must include the question or setup that frames what
  the professional says. Never clip a bare one-line quote. `framing_time` is the moment inside the clip
  where that question or setup is spoken.
- **Read two minutes of transcript on each side** of the range before choosing it. Look for a caveat
  that follows ("but this only applies to...", "talk to your doctor"). If the caveat is outside the
  clip, extend the clip to include it, or drop the clip.
- Prefer explanations, prevention and general education. Be very cautious with dosages, treatments,
  stopping medication and cure claims. They may still be clipped when the context is complete, but
  they go in `risk_flags` and you tell the user.
- Skip sponsor reads, supplement or product pitches, and anything where the speaker is relaying a
  claim they then say is unproven.
- Accuracy beats "viral". `text` is verbatim.

## The verification record

Write this on every segment. `clip render` checks that each field is filled and, where it can, that it holds.

```json
"verification": {
  "speaker": "Dr Anita Rao",
  "credential": "cardiologist",
  "context_excerpt": "Right after the clip: 'this applies to adults without existing heart conditions.'",
  "context_checked": true,
  "framing_time": "12:41",
  "risk_flags": []
}
```

- `speaker` and `credential`: from the video's description, title or on-screen text. Never guess. If
  you cannot find them, ask the user. Both are burned into the clip as "Name, credential".
- `context_excerpt`: the sentence or two just before or after the clip that qualify the claim, quoted
  from the transcript, or `none needed: <why>`. It must not be empty.
- `context_checked`: `true` only after you read the surrounding two minutes and found that the clip
  does not turn a caveat into a claim. Never set it to make the gate pass.
- `framing_time`: a time inside the clip (at or after `start_time`, before `end_time`).
- `risk_flags`: a list such as `["dosage", "stop medication", "cure claim"]`. Empty when none. It does
  not block the clip, it makes the risk visible in `verification.md`.

The disclaimer "General information, not medical advice." is burned into every health clip
automatically and added to the post description.

## Commentary (optional)

`"commentary": "..."` is one line of your own context, at most 140 characters, shown as a card after
the title. It is optional and recorded in `verification.md`. Use it to add the caveat when the clip
needs one, for example "Applies to adults without heart conditions."
