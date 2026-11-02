"""Where each candidate video and each clip stands: found, approved, fetched, clipped, verified, posted.

One small JSON file (tracker/state.json), shared by the review UI and the CLI. Pure, stdlib only.
Writes are atomic (temp file then rename) so a crash never leaves half a file.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Set

SOURCE_STATUSES = ("found", "approved", "rejected", "fetched", "clipped", "verified", "posted")
PERMISSIONS = ("unchecked", "asked", "granted", "cc")
CLIP_MARKS = ("ok", "fix")


class TrackerError(ValueError):
    """The tracker file is unreadable, or a value is not one the tracker knows."""


def load(path: Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"sources": {}, "clips": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TrackerError(f"{path}: cannot read the tracker file ({exc}); fix or move it aside") from None
    if not (isinstance(state, dict) and isinstance(state.get("sources"), dict) and isinstance(state.get("clips"), dict)):
        raise TrackerError(f"{path}: not a tracker file (needs 'sources' and 'clips' objects); fix or move it aside")
    return state


def save(path: Path, state: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tracker-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def upsert_source(state: Dict[str, Any], cand: Dict[str, Any], domain: str, now: str) -> Dict[str, Any]:
    """Add a candidate as ``found``, or refresh its metadata and keep the user's status, permission and note."""
    video_id = cand["id"]
    row = state["sources"].get(video_id)
    if row is None:
        row = {"status": "found", "permission": "unchecked", "note": "", "found_at": now, "domain": domain}
        state["sources"][video_id] = row
    row.update(cand)
    row.setdefault("domain", domain)  # a video found under two domains stays under the first
    row["updated_at"] = now
    return row


def set_source(state: Dict[str, Any], video_id: str, *, status: Optional[str] = None,
               permission: Optional[str] = None, note: Optional[str] = None, now: str) -> Dict[str, Any]:
    row = state["sources"].get(video_id)
    if row is None:
        raise TrackerError(f"unknown source {video_id!r}")
    if status is not None and status not in SOURCE_STATUSES:
        raise TrackerError(f"status must be one of {', '.join(SOURCE_STATUSES)}")
    if permission is not None and permission not in PERMISSIONS:
        raise TrackerError(f"permission must be one of {', '.join(PERMISSIONS)}")
    if status is not None:
        row["status"] = status
    if permission is not None:
        row["permission"] = permission
    if note is not None:
        row["note"] = note
    row["updated_at"] = now
    return row


def rejected_ids(state: Dict[str, Any]) -> Set[str]:
    return {vid for vid, row in state["sources"].items() if row.get("status") == "rejected"}


def set_clip(state: Dict[str, Any], job: str, number: int, *, mark: Optional[str] = None,
             note: Optional[str] = None, posted: Optional[Dict[str, str]] = None, now: str) -> Dict[str, Any]:
    if mark is not None and mark not in CLIP_MARKS:
        raise TrackerError(f"mark must be one of {', '.join(CLIP_MARKS)}")
    row = state["clips"].setdefault(f"{job}/{number:02d}", {})
    if mark is not None:
        row["mark"] = mark
    if note is not None:
        row["note"] = note
    if posted is not None:
        row["posted"] = {"platform": posted.get("platform", ""), "url": posted.get("url", ""), "at": now}
    row["updated_at"] = now
    return row


def sync_statuses(state: Dict[str, Any], jobs: Dict[str, Dict[str, Any]]) -> None:
    """Move each source forward to what the files on disk show. Never backwards, never touches ``rejected``.

    ``jobs[video_id] = {"fetched": bool, "clips": int, "verified": bool}``.
    """
    order = {name: i for i, name in enumerate(SOURCE_STATUSES)}
    for video_id, facts in jobs.items():
        row = state["sources"].get(video_id)
        if row is None or row.get("status") == "rejected":
            continue
        if facts.get("verified"):
            target = "verified"
        elif facts.get("clips", 0) > 0:
            target = "clipped"
        elif facts.get("fetched"):
            target = "fetched"
        else:
            continue
        if order[target] > order.get(row.get("status"), 0):
            row["status"] = target
