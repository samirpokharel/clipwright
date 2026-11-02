"""Source-to-clip time mapping and key-word matching. Pure functions, stdlib only."""

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

Range = Tuple[float, float]


def to_clip_time(
    t: float, keep_ranges: Sequence[Range], offsets: Optional[Sequence[float]] = None
) -> Optional[float]:
    """Map a source time (seconds) to clip time, or None if it falls in a cut.

    ``offsets`` gives where each kept range starts on the rendered clip, as SupoClip's
    ``output_offsets_for_ranges`` returns it (crossfades pull later ranges earlier).
    Without it, ranges are assumed to be concatenated back to back.
    """
    cursor = 0.0
    for index, (start, end) in enumerate(keep_ranges):
        if start <= t <= end:
            base = offsets[index] if offsets is not None else cursor
            return base + (t - start)
        cursor += end - start
    return None


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", text.lower())


def _phrase_tokens(key: str) -> List[str]:
    return [t for t in (_norm(part) for part in key.split()) if t]


def _find(tokens: Sequence[str], phrase: Sequence[str]) -> Optional[int]:
    """Index of the first run of consecutive tokens equal to ``phrase``, or None."""
    if not phrase:
        return None
    for i in range(len(tokens) - len(phrase) + 1):
        if all(tokens[i + j] == phrase[j] for j in range(len(phrase))):
            return i
    return None


def phrase_indices(
    words: Sequence[Dict[str, Any]], key_words: Sequence[str]
) -> Tuple[Optional[List[int]], List[str]]:
    """Positions (in ``words``) of the first spoken occurrence of each key word or phrase.

    Returns every word of a matched phrase, so SupoClip's ``emphasis_indices`` highlights exactly
    those words and nothing else (a phrase like "chopped in half" never lights up another "in").
    Returns ``(None, [])`` when there are no key words, so SupoClip's automatic emphasis applies.
    """
    if not key_words:
        return None, []
    tokens = [_norm(word.get("text", "")) for word in words]
    indices: List[int] = []
    unmatched: List[str] = []
    for key in key_words:
        phrase = _phrase_tokens(key)
        start = _find(tokens, phrase)
        if start is None:
            unmatched.append(key)
        else:
            indices.extend(range(start, start + len(phrase)))
    return sorted(set(indices)), unmatched


def match_key_words(
    words: Sequence[Dict[str, Any]],
    key_words: Sequence[str],
    keep_ranges: Sequence[Range],
    offsets: Optional[Sequence[float]] = None,
) -> Tuple[List[Tuple[float, str]], List[str]]:
    """Find the first spoken occurrence of each key word or phrase inside the kept ranges.

    ``words`` items carry ``text``, ``start`` and ``end`` in milliseconds. Returns
    ``(matches, unmatched)``: matches are ``(clip_time, key_word)`` and unmatched
    lists key words that never appear.
    """
    spoken = []
    for word in words:
        clip_time = to_clip_time(word["start"] / 1000.0, keep_ranges, offsets)
        token = _norm(word.get("text", ""))
        if clip_time is not None and token:
            spoken.append((token, clip_time))

    tokens = [token for token, _ in spoken]
    matches: List[Tuple[float, str]] = []
    unmatched: List[str] = []
    for key in key_words:
        start = _find(tokens, _phrase_tokens(key))
        if start is None:
            unmatched.append(key)
        else:
            matches.append((spoken[start][1], key))
    return matches, unmatched
