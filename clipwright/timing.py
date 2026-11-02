"""Source-to-clip time mapping and key-word matching. Pure functions, stdlib only."""

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

Range = Tuple[float, float]


def to_clip_time(t: float, keep_ranges: Sequence[Range]) -> Optional[float]:
    """Map a source time (seconds) to clip time, or None if it falls in a cut."""
    offset = 0.0
    for start, end in keep_ranges:
        if start <= t <= end:
            return offset + (t - start)
        offset += end - start
    return None


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", text.lower())


def match_key_words(
    words: Sequence[Dict[str, Any]],
    key_words: Sequence[str],
    keep_ranges: Sequence[Range],
) -> Tuple[List[Tuple[float, str]], List[str]]:
    """Find the first spoken occurrence of each key word or phrase inside the kept ranges.

    ``words`` items carry ``text``, ``start`` and ``end`` in milliseconds. Returns
    ``(matches, unmatched)``: matches are ``(clip_time, key_word)`` and unmatched
    lists key words that never appear.
    """
    spoken = []
    for word in words:
        clip_time = to_clip_time(word["start"] / 1000.0, keep_ranges)
        token = _norm(word.get("text", ""))
        if clip_time is not None and token:
            spoken.append((token, clip_time))

    matches: List[Tuple[float, str]] = []
    unmatched: List[str] = []
    for key in key_words:
        tokens = [t for t in (_norm(part) for part in key.split()) if t]
        found = None
        if tokens:
            for i in range(len(spoken) - len(tokens) + 1):
                if all(spoken[i + j][0] == tokens[j] for j in range(len(tokens))):
                    found = spoken[i][1]
                    break
        if found is None:
            unmatched.append(key)
        else:
            matches.append((found, key))
    return matches, unmatched
