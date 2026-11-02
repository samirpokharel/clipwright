"""What a source video's licence lets you do. Pure functions, stdlib only.

yt-dlp reports a licence only for Creative Commons videos, as the text
"Creative Commons Attribution license (reuse allowed)". Every other YouTube video comes back
with no licence at all, which means the standard licence: all rights stay with the creator.
Verified on 2026-11-02 against a Creative Commons video and two standard ones.
"""

from typing import Any, Dict, Optional

CC_BY_LABEL = "Creative Commons Attribution (CC BY)"


def classify(raw: Optional[str], local: bool = False) -> Dict[str, Any]:
    """{"kind": cc-by | cc-other | standard | local, "label": str, "reuse_ok": bool}."""
    if local:
        return {"kind": "local", "label": "Local file (licence unknown)", "reuse_ok": False}
    text = (raw or "").strip()
    lowered = text.lower()
    if "creative commons" in lowered:
        if "attribution" in lowered and not any(x in lowered for x in ("noncommercial", "noderiv", "sharealike", "non-commercial")):
            return {"kind": "cc-by", "label": CC_BY_LABEL, "reuse_ok": True}
        return {"kind": "cc-other", "label": text, "reuse_ok": False}
    return {"kind": "standard", "label": "Standard YouTube licence (all rights reserved)", "reuse_ok": False}


def attribution(title: Optional[str], channel: Optional[str], url: Optional[str], kind: str) -> Optional[str]:
    """The credit line a CC BY video needs in the post description. None for other licences."""
    if kind != "cc-by":
        return None
    by = f" by {channel}" if channel else ""
    where = f", {url}" if url else ""
    return f'"{title or "Untitled"}"{by}{where}, licensed under {CC_BY_LABEL}'


def warning(kind: str) -> Optional[str]:
    """One line to show the user, or None when the licence allows reuse with credit."""
    if kind == "cc-by":
        return None
    if kind == "cc-other":
        return "Creative Commons, but not plain CC BY: read its terms before reusing (NonCommercial rules out a monetised channel)."
    if kind == "local":
        return "Local file: you are responsible for having the rights to reuse it."
    return "Standard YouTube licence: reusing this video needs the creator's permission. Clipping it without permission can get posts removed or strikes issued."
