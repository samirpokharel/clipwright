"""Licence-checked fetch of one Freesound sound into the local library.

Only CC0 and CC-BY sounds are accepted. The HQ MP3 preview is downloaded, which needs
only an API key (originals need OAuth2). The metadata field names (license, username,
name, url, previews) come from Freesound's public API documentation and have not been
checked against a live response: verify with one real fetch.

Freesound's API terms say commercial use of the API itself is negotiated with them.
This helper is meant for occasional curation, not for use while rendering.
"""

import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from .sounds import KINDS

API = "https://freesound.org/apiv2/sounds/{id}/?token={key}&fields=id,name,username,license,url,previews"


class FreesoundError(ValueError):
    """The request cannot be completed."""


class LicenceRefused(FreesoundError):
    """The sound's licence is not one this tool accepts."""


def licence_label(value: str) -> str:
    """Map a Freesound licence URL or name to 'CC0' or 'CC-BY', or refuse."""
    text = (value or "").strip().lower()
    if "publicdomain/zero" in text or text in ("creative commons 0", "cc0"):
        return "CC0"
    if re.search(r"/licenses/by/\d", text) or text == "attribution":
        return "CC-BY"
    raise LicenceRefused(f"licence {value!r} is not accepted (only CC0 and Attribution/CC-BY)")


def parse_sound_id(value: Union[str, int]) -> int:
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    match = re.search(r"freesound\.org/(?:s/|people/[^/]+/sounds/)(\d+)", text)
    if not match:
        raise FreesoundError(f"cannot find a sound id in {value!r}")
    return int(match.group(1))


def _default_get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed https hosts
        return response.read()


def fetch_sound(
    sound_id: Union[int, str],
    kind: str,
    api_key: str,
    sounds_dir: Path,
    *,
    http_get: Optional[Callable[[str], bytes]] = None,
) -> Dict[str, Any]:
    """Check the licence, download the preview and append an entry to library.json."""
    if not api_key:
        raise FreesoundError("set FREESOUND_API_KEY (free key from freesound.org/apiv2/apply)")
    if kind not in KINDS:
        raise FreesoundError(f"kind {kind!r} must be one of {', '.join(KINDS)}")
    get = http_get or _default_get
    sound_id = parse_sound_id(sound_id)
    sounds_dir = Path(sounds_dir)

    library_path = sounds_dir / "library.json"
    library = json.loads(library_path.read_text()) if library_path.exists() else []
    entry_id = f"fs-{sound_id}"
    if any(e.get("id") == entry_id for e in library):
        raise FreesoundError(f"{entry_id} is already in the library")

    meta = json.loads(get(API.format(id=sound_id, key=api_key)))
    label = licence_label(meta.get("license", ""))  # refuse before downloading anything
    preview = (meta.get("previews") or {}).get("preview-hq-mp3")
    if not preview:
        raise FreesoundError(f"sound {sound_id} has no HQ MP3 preview")

    folder = "music" if kind == "music" else "fx"
    relative = f"{folder}/{entry_id}.mp3"
    (sounds_dir / folder).mkdir(parents=True, exist_ok=True)
    (sounds_dir / relative).write_bytes(get(preview))

    author = meta.get("username") or "unknown"
    entry = {
        "id": entry_id, "kind": kind, "file": relative, "source": "freesound", "license": label,
        "author": author, "url": meta.get("url") or f"https://freesound.org/s/{sound_id}/",
    }
    if label == "CC-BY":
        entry["attribution"] = f"{meta.get('name', entry_id)} by {author} (CC BY)"
    library.append(entry)
    library_path.write_text(json.dumps(library, indent=2) + "\n")
    return entry
