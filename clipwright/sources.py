"""Find candidate videos for a domain: filter, enrich with licence and age, rank, write a checklist.

The search itself (yt-dlp, which needs the container) lives in clip.py; everything here is pure and
stdlib only. yt-dlp's flat search entries carry the id, title, channel, duration and view count but
no licence or upload date: those come from a second, slower lookup per video (``enrich``), so only
the most promising candidates are enriched. Verified against yt-dlp on 2026-11-02.
"""

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Set

from . import licence


def candidate_from_flat(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The fields we keep from a yt-dlp flat search entry, or None when it has no video id."""
    video_id = entry.get("id")
    if not video_id:
        return None
    duration, views = entry.get("duration"), entry.get("view_count")
    return {
        "id": video_id,
        "title": (entry.get("title") or "").strip(),
        "channel": (entry.get("channel") or entry.get("uploader") or "").strip(),
        "channel_id": entry.get("channel_id") or "",
        "duration": int(duration) if isinstance(duration, (int, float)) else None,
        "views": int(views) if isinstance(views, (int, float)) else None,
        "url": entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
    }


def _on_watchlist(cand: Dict[str, Any], watchlist: Sequence[str]) -> bool:
    channel, channel_id = cand.get("channel", "").lower(), cand.get("channel_id", "")
    for entry in watchlist:
        entry = entry.strip()
        if entry.lower() == channel or (channel_id and channel_id in entry):
            return True
    return False


def prefilter(cands: Sequence[Dict[str, Any]], rules: Dict[str, Any], seen: Set[str],
              watchlist: Sequence[str]) -> List[Dict[str, Any]]:
    """Dedupe by id, drop seen, short and unpopular videos. A watchlist channel keeps unknown view counts."""
    out: List[Dict[str, Any]] = []
    ids: Set[str] = set()
    for cand in cands:
        if cand["id"] in ids or cand["id"] in seen:
            continue
        ids.add(cand["id"])
        if cand.get("duration") is None or cand["duration"] < rules["min_minutes"] * 60:
            continue
        listed = _on_watchlist(cand, watchlist)
        views = cand.get("views")
        if not listed and (views is None or views < rules["min_views"]):
            continue
        out.append(dict(cand, watchlist=listed))
    return out


def select_for_enrichment(cands: Sequence[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """The candidates worth a slow lookup: watchlist channels first, then by views."""
    ordered = sorted(cands, key=lambda c: (not c.get("watchlist"), -(c.get("views") or 0)))
    return ordered[:limit]


def enrich(cand: Dict[str, Any], info: Optional[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """Add licence, upload date and age from a full yt-dlp lookup. ``info=None`` means the lookup failed."""
    out = dict(cand)
    if info is None:
        out.update(license_kind="unchecked", license_label="Licence not checked", reuse_ok=False,
                   upload_date=None, age_days=None, followers=None)
        return out
    lic = licence.classify(info.get("license"))
    upload = None
    age = None
    raw = info.get("upload_date")
    try:
        parsed = datetime.strptime(str(raw), "%Y%m%d").date()
        upload, age = parsed.isoformat(), (today - parsed).days
    except ValueError:
        pass
    out.update(license_kind=lic["kind"], license_label=lic["label"], reuse_ok=lic["reuse_ok"],
               upload_date=upload, age_days=age, followers=info.get("channel_follower_count"))
    return out


def postfilter(cands: Sequence[Dict[str, Any]], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Drop videos older than the pack allows. A video of unknown age is kept."""
    limit = rules.get("max_age_days")
    return [c for c in cands if limit is None or c.get("age_days") is None or c["age_days"] <= limit]


def rank(cands: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """CC BY first, then watchlist channels, then everything else; each group by views."""
    def key(c: Dict[str, Any]):
        tier = 0 if c.get("license_kind") == "cc-by" else (1 if c.get("watchlist") else 2)
        return tier, -(c.get("views") or 0)
    return sorted(cands, key=key)


def _duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "?"
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}"


def to_markdown(domain: str, cands: Sequence[Dict[str, Any]], generated: str) -> str:
    lines = [f"# Sources: {domain}", "",
             f"Generated {generated}. {len(cands)} videos, best candidates first (CC BY, then watchlist, then views).",
             "Nothing here is cleared: check the creator's permission yourself before you clip.", ""]
    if domain == "health":
        lines += ["Health: check each speaker's credentials and read the surrounding context before clipping.", ""]
    if not cands:
        lines.append("No videos matched. Loosen the pack's filters or add queries.")
    for c in cands:
        views = f"{c['views']:,} views" if c.get("views") is not None else "views unknown"
        age = f"{c['age_days']} days old" if c.get("age_days") is not None else "age unknown"
        mark = " (watchlist)" if c.get("watchlist") else ""
        lines += [f"- [ ] **{c['title']}** | {c['channel']}{mark}",
                  f"  - {_duration(c.get('duration'))} h, {views}, {age}",
                  f"  - licence: {c.get('license_label', 'Licence not checked')}",
                  f"  - {c['url']}",
                  "  - permission: unchecked"]
    return "\n".join(lines) + "\n"


def to_json(cands: Sequence[Dict[str, Any]]) -> str:
    return json.dumps(list(cands), indent=2, ensure_ascii=False)
