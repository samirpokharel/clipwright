"""The post queue: one row per (clip, platform), in queue.db (stdlib sqlite3).

A row only exists once the user approved the clip on the review page, and the unique key
(post_json, platform) means a clip can never be queued, and so never posted, twice.

    pending ──▶ uploading ──▶ scheduled   (platform holds it and publishes at slot_at)
                    │     ├──▶ processing (uploaded, platform still encoding; polled next run)
                    │     └──▶ posted
                    └──▶ pending again with a backoff, then failed after MAX_ATTEMPTS
A row left in "uploading" by a crash is never retried automatically: the upload may have
gone through, so it becomes failed and says so, and the user checks the platform first.
"""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

STATUSES = ("pending", "uploading", "processing", "scheduled", "posted", "failed")
MAX_ATTEMPTS = 3
BACKOFF_MINUTES = (15, 60)                 # after attempt 1 and 2; attempt 3 failing is final
STALE_UPLOAD = timedelta(hours=1)
MIN_LEAD = timedelta(minutes=15)           # never assign a slot closer than this to now
# platforms that publish at a set time themselves, and how early we may hand them the video
NATIVE_SCHEDULE_AHEAD = {"youtube": timedelta(hours=48), "facebook": timedelta(hours=48)}

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    brand TEXT NOT NULL,
    post_json TEXT NOT NULL,
    platform TEXT NOT NULL,
    slot_base TEXT NOT NULL,
    slot_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    remote_id TEXT,
    url TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_try_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (post_json, platform)
);
CREATE TABLE IF NOT EXISTS quota (platform TEXT, day TEXT, units INTEGER, PRIMARY KEY (platform, day));
"""


class QueueError(ValueError):
    pass


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), isolation_level=None, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def rows(db: sqlite3.Connection, where: str = "1", params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    return [dict(r) for r in db.execute(f"SELECT * FROM posts WHERE {where} ORDER BY slot_at, id", params)]


def queued_post_jsons(db: sqlite3.Connection) -> set:
    return {r[0] for r in db.execute("SELECT DISTINCT post_json FROM posts")}


def next_slots(accounts: Dict[str, Any], platforms: Sequence[str], taken: Iterable[str],
               now: Optional[datetime] = None, days: int = 60) -> Dict[str, Any]:
    """The earliest daily slot with none of ``platforms`` booked, as {base, at: {platform: utc}}.

    ``taken`` holds slot_base values already used by this brand on any of these platforms.
    Platforms post ``stagger_minutes`` apart in the order given, so one clip does not land
    everywhere in the same minute.
    """
    now = now or now_utc()
    tz = ZoneInfo(accounts["timezone"])
    taken = set(taken)
    stagger = timedelta(minutes=accounts.get("stagger_minutes", 20))
    start = now.astimezone(tz).date()
    for offset in range(days):
        day = start + timedelta(days=offset)
        for slot in accounts["slots"]:
            hh, mm = map(int, slot.split(":"))
            base = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
            if base < now + MIN_LEAD or iso(base) in taken:
                continue
            return {"base": iso(base), "at": {p: iso(base + stagger * i) for i, p in enumerate(platforms)}}
    raise QueueError(f"no free slot in the next {days} days")


def enqueue(db: sqlite3.Connection, brand: str, post_json: str, accounts: Dict[str, Any],
            platforms: Sequence[str], now: Optional[datetime] = None) -> Dict[str, str]:
    """Book the next free slot for this clip on ``platforms``. Refuses a clip already queued."""
    if not platforms:
        raise QueueError("choose at least one platform")
    if post_json in queued_post_jsons(db):
        raise QueueError(f"{post_json} is already queued")
    marks = ",".join("?" * len(platforms))
    taken = [r[0] for r in db.execute(
        f"SELECT slot_base FROM posts WHERE brand = ? AND platform IN ({marks})", (brand, *platforms))]
    slots = next_slots(accounts, platforms, taken, now)
    stamp = iso(now or now_utc())
    with db:
        db.execute("BEGIN")
        for p in platforms:
            db.execute("INSERT INTO posts (brand, post_json, platform, slot_base, slot_at, created_at, updated_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)", (brand, post_json, p, slots["base"], slots["at"][p], stamp, stamp))
    return slots["at"]


def due(db: sqlite3.Connection, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Pending rows to upload now: past their slot, or inside the platform's native schedule window."""
    now = now or now_utc()
    out = []
    for r in rows(db, "status = 'pending'"):
        if r["next_try_at"] and parse_iso(r["next_try_at"]) > now:
            continue
        ahead = NATIVE_SCHEDULE_AHEAD.get(r["platform"], timedelta(0))
        if parse_iso(r["slot_at"]) <= now + ahead:
            out.append(r)
    return out


def _update(db: sqlite3.Connection, row_id: int, **fields: Any) -> None:
    fields["updated_at"] = iso(now_utc())
    cols = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE posts SET {cols} WHERE id = ?", (*fields.values(), row_id))


def claim(db: sqlite3.Connection, row_id: int) -> bool:
    """Move pending -> uploading atomically; False if another run took it first."""
    cur = db.execute("UPDATE posts SET status = 'uploading', attempts = attempts + 1, updated_at = ? "
                     "WHERE id = ? AND status = 'pending'", (iso(now_utc()), row_id))
    return cur.rowcount == 1


def finish(db: sqlite3.Connection, row_id: int, status: str, remote_id: Optional[str] = None,
           url: Optional[str] = None) -> None:
    if status not in ("processing", "scheduled", "posted"):
        raise QueueError(f"bad final status {status!r}")
    _update(db, row_id, status=status, remote_id=remote_id, url=url, last_error=None, next_try_at=None)


def fail(db: sqlite3.Connection, row_id: int, error: str, retry: bool = True,
         now: Optional[datetime] = None) -> str:
    """Record a failed attempt. Retries with backoff unless ``retry`` is False or attempts ran out."""
    row = rows(db, "id = ?", (row_id,))[0]
    attempts = row["attempts"]
    if retry and attempts < MAX_ATTEMPTS:
        wait = timedelta(minutes=BACKOFF_MINUTES[min(attempts, len(BACKOFF_MINUTES)) - 1])
        _update(db, row_id, status="pending", last_error=error[:2000], next_try_at=iso((now or now_utc()) + wait))
        return "pending"
    _update(db, row_id, status="failed", last_error=error[:2000], next_try_at=None)
    return "failed"


def recover_stale(db: sqlite3.Connection, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Rows stuck in uploading (a crash mid-upload) become failed, never silently retried."""
    now = now or now_utc()
    stale = [r for r in rows(db, "status = 'uploading'") if parse_iso(r["updated_at"]) < now - STALE_UPLOAD]
    for r in stale:
        _update(db, r["id"], status="failed",
                last_error="interrupted during upload; check the platform for a duplicate, then `./post retry`")
    return stale


def retry(db: sqlite3.Connection, row_id: int) -> None:
    cur = db.execute("UPDATE posts SET status = 'pending', attempts = 0, next_try_at = NULL, updated_at = ? "
                     "WHERE id = ? AND status = 'failed'", (iso(now_utc()), row_id))
    if cur.rowcount != 1:
        raise QueueError(f"post {row_id} is not failed")


def cancel(db: sqlite3.Connection, row_id: int) -> None:
    cur = db.execute("DELETE FROM posts WHERE id = ? AND status IN ('pending', 'failed')", (row_id,))
    if cur.rowcount != 1:
        raise QueueError(f"post {row_id} is not pending or failed (already on the platform?)")


def add_quota(db: sqlite3.Connection, platform: str, units: int, day: Optional[date] = None) -> int:
    day_s = (day or quota_day()).isoformat()
    db.execute("INSERT INTO quota (platform, day, units) VALUES (?, ?, ?) "
               "ON CONFLICT (platform, day) DO UPDATE SET units = units + excluded.units", (platform, day_s, units))
    return used_quota(db, platform, day)


def used_quota(db: sqlite3.Connection, platform: str, day: Optional[date] = None) -> int:
    row = db.execute("SELECT units FROM quota WHERE platform = ? AND day = ?",
                     (platform, (day or quota_day()).isoformat())).fetchone()
    return row[0] if row else 0


def quota_day() -> date:
    """YouTube quota resets at midnight Pacific time."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()
