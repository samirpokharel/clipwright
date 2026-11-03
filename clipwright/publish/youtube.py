"""YouTube uploads through the Data API v3 resumable protocol.

The video goes up private with ``publishAt`` set to the slot, so YouTube itself publishes it
on time even if the laptop is off then. ``videos.insert`` has its own daily bucket (100 calls
by default, 1 unit each, separate from the 10,000 units for other methods); the count is kept
in queue.db so a run stops before YouTube would refuse. Until the API project passes Google's compliance audit, YouTube keeps
API uploads private whatever we ask for.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from .. import postqueue
from .base import Adapter, PublishError, Result
from .http import HttpError, call

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
UPLOAD_COST = 1
DEFAULT_DAILY_QUOTA = 100         # videos.insert calls per day, per Google Cloud project
QUOTA_BUCKET = "youtube_insert"
CHUNK = 8 * 1024 * 1024           # a multiple of 256 KiB, as the resumable protocol requires
MIN_SCHEDULE_LEAD = timedelta(minutes=10)


def video_body(post: Dict[str, Any], slot_at: datetime, cfg: Dict[str, Any]) -> Dict[str, Any]:
    copy = post["platforms"]["youtube"]
    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "embeddable": True}
    if slot_at - datetime.now(timezone.utc) >= MIN_SCHEDULE_LEAD:
        status["publishAt"] = postqueue.iso(slot_at)
    else:
        status["privacyStatus"] = "public"
    return {"snippet": {"title": copy["title"], "description": copy.get("description", ""),
                        "tags": copy.get("tags", []), "categoryId": str(cfg.get("category_id", "27"))},
            "status": status}


class YouTube(Adapter):
    platform = "youtube"

    def publish(self, post: Dict[str, Any], video: Path, slot_at: datetime, cfg: Dict[str, Any]) -> Result:
        limit = int(cfg.get("daily_quota", DEFAULT_DAILY_QUOTA))
        if self.db is not None and postqueue.used_quota(self.db, QUOTA_BUCKET) + UPLOAD_COST > limit:
            raise PublishError("YouTube daily quota would be exceeded; it resets at midnight Pacific", retry=True)
        token = self.tokens.access("google")
        body = video_body(post, slot_at, cfg)
        data = video.read_bytes()
        try:
            _, headers, _ = call(self.transport, "POST", UPLOAD_URL,
                                 params={"uploadType": "resumable", "part": "snippet,status"},
                                 json_body=body, raw=True, headers={
                                     "Authorization": f"Bearer {token}",
                                     "X-Upload-Content-Type": "video/mp4",
                                     "X-Upload-Content-Length": str(len(data))})
            session = headers.get("location")
            if not session:
                raise PublishError("YouTube did not return an upload session URL")
            if self.db is not None:
                postqueue.add_quota(self.db, QUOTA_BUCKET, UPLOAD_COST)
            resource = self._send(session, token, data)
        except HttpError as exc:
            if exc.status == 403 and "quotaExceeded" in exc.body:
                raise PublishError(str(exc), retry=True) from None
            raise PublishError(str(exc), retry=exc.retryable) from None
        vid = resource["id"]
        scheduled = "publishAt" in body["status"]
        return Result("scheduled" if scheduled else "posted", vid, f"https://youtube.com/shorts/{vid}")

    def _send(self, session: str, token: str, data: bytes) -> Dict[str, Any]:
        import json
        total, offset = len(data), 0
        while offset < total:
            end = min(offset + CHUNK, total)
            status, headers, body = call(self.transport, "PUT", session, body=data[offset:end], raw=True,
                                         ok=(200, 201, 308), timeout=600, headers={
                                             "Authorization": f"Bearer {token}",
                                             "Content-Length": str(end - offset),
                                             "Content-Range": f"bytes {offset}-{end - 1}/{total}"})
            if status in (200, 201):
                return json.loads(body)
            # 308: resume from what YouTube says it has ("bytes=0-N")
            got = headers.get("range")
            offset = int(got.rsplit("-", 1)[1]) + 1 if got else offset
        raise PublishError("YouTube upload ended without a video resource")
