---
name: clip-mythology
description: Use when the user wants to clip Hindu mythology, epics or scripture content in English or Hinglish ("clip this Ramayana video", "find Mahabharata stories to clip"). Applies the mythology verification gate (source text named, variants noted, verses checked, respectful framing) on top of the supoclip clipping skill.
---

# Clipwright mythology clips

Mythology clips go wrong when a story is presented as the only version, when a verse is misquoted,
or when belief is mocked or stated as plain history. This skill builds on the `supoclip` skill
(fetch, frames, layout, style, segments.json, render): read that for the common steps. `clip render`
enforces the gate: a clip without a complete `verification` record is not rendered.

## Steps

1. **Sources.** `__CLIP_DIR__/clip sources mythology` (or the review UI, `__CLIP_DIR__/clip-ui`), or the user's URLs.
2. `__CLIP_DIR__/clip check <url>` for the licence, said in one line.
3. `__CLIP_DIR__/clip fetch --domain mythology <url>`. Narration that is Hindi or Hinglish transcribes
   less accurately than English: read the transcript sceptically, and prefer English or Hinglish
   sources. Captions are in Latin script. Devanagari text in a title will not render (the brand font has
   no Devanagari glyphs), so write titles in Latin script.
4. Read the transcript and `state.json`, choose clips with the rules below, then follow the base
   skill for frames, layout and style (`explainer` for narrated stories, `interview` for talks).
5. Write `segments.json` with a `verification` object on every segment, render, and read
   `out/<job>/verification.md`.

## Selection rules

- **Clip length is 20 to 75 seconds.** A story beat needs its setup and its payoff.
- Pick a self-contained moment: a turning point, a moral dilemma, a "why did X do Y" answer, a
  little-known detail. Start where the story starts, not mid-sentence.
- Skip clips that need the previous episode to make sense, and anything that ridicules a deity, a
  community or a belief.
- Frame belief as tradition: "according to the Ramayana", not "this happened". Do not clip a
  speaker's personal political or sectarian claims about living people or communities.
- Quoted verses and shlokas must be exactly right. If the speaker recites a verse, check it.

## The verification record

```json
"verification": {
  "source_text": "Valmiki Ramayana, Yuddha Kanda",
  "variant_note": "In the Tulsidas Ramcharitmanas the order of events differs.",
  "verses_checked": true,
  "respect_check": true
}
```

- `source_text`: the scripture or epic the story comes from (Ramayana, Mahabharata, a named Purana, the
  Bhagavad Gita), with the book or section when you know it, or `folk or regional tradition`. Not blank.
  If the speaker does not say and you are not sure, ask the user rather than guess.
- `variant_note`: say when versions differ across texts or regions, or write `no known variants`.
  Not blank. The clip must not present one version as the only one.
- `verses_checked`: `true` only after you checked any quoted verse and its translation against the
  source. It is also `true` when no verse is quoted.
- `respect_check`: `true` only when the clip does not mock a community or deity and frames belief as
  "according to tradition".

## Commentary (optional)

`"commentary": "..."` is one line of your own context, at most 140 characters, shown as a card after
the title. Optional. Good for naming the source or version, for example "From the Valmiki Ramayana."
