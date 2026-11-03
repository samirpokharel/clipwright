"""Upload whatever in queue.db is due, through the platform adapters."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import brands, postqueue as pq, postspec
from .auth import AuthError, TokenStore
from .base import PublishError, Result
from .http import Transport, urllib_transport
from .meta import Facebook, Instagram
from .tiktok import TikTok
from .youtube import YouTube

ADAPTERS = {"youtube": YouTube, "tiktok": TikTok, "facebook": Facebook, "instagram": Instagram}


def _context(work: Path, row: Dict[str, Any]):
    post = postspec.load(work / row["post_json"])
    accounts = brands.load_accounts(work / "brands" / row["brand"] / "accounts.json")
    cfg = accounts["platforms"].get(row["platform"])
    if cfg is None:
        raise PublishError(f"{row['platform']} was removed from {row['brand']}'s accounts.json", retry=False)
    return post, cfg


def run_due(work: Path, db, transport: Transport = urllib_transport, dry_run: bool = False,
            log: Callable[[str], Any] = print, adapters: Optional[Dict[str, Any]] = None,
            sleep=None) -> List[Dict[str, Any]]:
    """One publisher pass. Returns a line per row it touched, for logs and notifications."""
    adapters = adapters or ADAPTERS
    report: List[Dict[str, Any]] = []

    def adapter_for(row):
        return adapters[row["platform"]](transport, TokenStore(work / "secrets", row["brand"], transport), db, sleep)

    for row in pq.recover_stale(db):
        report.append(dict(row, outcome="failed", error="interrupted during upload"))

    for row in pq.rows(db, "status = 'processing'"):
        if dry_run:
            log(f"would check   #{row['id']} {row['brand']}/{row['platform']} {row['remote_id']}")
            continue
        try:
            _, cfg = _context(work, row)
            res = adapter_for(row).check(row["remote_id"], cfg)
            if res.status != "processing":
                pq.finish(db, row["id"], res.status, res.remote_id, res.url)
                report.append(dict(row, outcome=res.status, url=res.url))
        except (PublishError, AuthError, brands.BrandError, postspec.PostError) as exc:
            pq.fail(db, row["id"], str(exc), retry=False)
            report.append(dict(row, outcome="failed", error=str(exc)))

    for row in pq.due(db):
        label = f"#{row['id']} {row['brand']}/{row['platform']} {Path(row['post_json']).parent.name} @ {row['slot_at']}"
        if dry_run:
            log(f"would upload  {label}")
            continue
        if not pq.claim(db, row["id"]):
            continue
        try:
            post, cfg = _context(work, row)
            video = work / post["file"]
            if not video.is_file():
                raise PublishError(f"video file missing: {video}", retry=False)
            res: Result = adapter_for(row).publish(post, video, pq.parse_iso(row["slot_at"]), cfg)
            pq.finish(db, row["id"], res.status, res.remote_id, res.url)
            log(f"{res.status:<11} {label} {res.url or ''}")
            report.append(dict(row, outcome=res.status, url=res.url))
        except PublishError as exc:
            outcome = pq.fail(db, row["id"], str(exc), retry=exc.retry)
            log(f"{outcome:<11} {label}: {exc}")
            report.append(dict(row, outcome=outcome, error=str(exc)))
        except (AuthError, brands.BrandError, postspec.PostError) as exc:
            pq.fail(db, row["id"], str(exc), retry=False)
            log(f"failed      {label}: {exc}")
            report.append(dict(row, outcome="failed", error=str(exc)))
        except Exception as exc:  # unknown state: the upload may have gone through, so never auto-retry
            pq.fail(db, row["id"], f"unexpected {type(exc).__name__}: {exc}; check the platform before retrying",
                    retry=False)
            log(f"failed      {label}: {exc!r}")
            report.append(dict(row, outcome="failed", error=repr(exc)))
    return report
