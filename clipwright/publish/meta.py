"""Facebook Reels and Instagram Reels through the Graph API, with local file uploads.

Facebook: POST /{page}/video_reels?upload_phase=start -> upload bytes to rupload.facebook.com
          -> upload_phase=finish with video_state PUBLISHED, or SCHEDULED + scheduled_publish_time.
Instagram: POST /{ig-user}/media (media_type=REELS, upload_type=resumable) -> upload bytes to
          rupload.facebook.com -> poll the container's status_code -> POST /{ig-user}/media_publish.
Instagram has no scheduling in the API, so the publisher calls this at the slot time.
Flow and field names follow Meta's Reels publishing docs; not yet run against a live Page here.
"""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from . import auth
from .base import Adapter, PublishError, Result
from .http import HttpError, call

FB_SCHEDULE_MIN = timedelta(minutes=15)    # Meta needs at least 10 minutes; keep a margin
FB_SCHEDULE_MAX = timedelta(days=29)
IG_POLL_SECONDS = 10
IG_POLL_LIMIT = 30                          # about 5 minutes, then hand back as "processing"


def _rupload(adapter: Adapter, url: str, token: str, video: Path) -> None:
    data = video.read_bytes()
    r = call(adapter.transport, "POST", url, body=data, timeout=600, headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data)),
        "Content-Type": "application/octet-stream"})
    if not r.get("success", True):
        raise PublishError(f"upload to {url.split('/')[2]} was not accepted: {r}")


def _wrap(exc: HttpError) -> PublishError:
    return PublishError(str(exc), retry=exc.retryable)


class Facebook(Adapter):
    platform = "facebook"

    def publish(self, post: Dict[str, Any], video: Path, slot_at: datetime, cfg: Dict[str, Any]) -> Result:
        apps = auth.load_apps(self.tokens.secrets_dir)
        base, version = auth.graph(apps), auth.graph(apps).rsplit("/", 1)[1]
        page_id = str(cfg["page_id"])
        token = self.tokens.page(page_id)["access_token"]
        try:
            start = call(self.transport, "POST", f"{base}/{page_id}/video_reels",
                         form={"upload_phase": "start", "access_token": token})
            video_id = start["video_id"]
            _rupload(self, f"https://rupload.facebook.com/video-upload/{version}/{video_id}", token, video)
            ahead = slot_at - datetime.now(timezone.utc)
            form = {"upload_phase": "finish", "video_id": video_id, "access_token": token,
                    "description": post["platforms"]["facebook"]["caption"]}
            if FB_SCHEDULE_MIN <= ahead <= FB_SCHEDULE_MAX:
                form.update(video_state="SCHEDULED", scheduled_publish_time=str(int(slot_at.timestamp())))
                status = "scheduled"
            else:
                form["video_state"] = "PUBLISHED"
                status = "posted"
            done = call(self.transport, "POST", f"{base}/{page_id}/video_reels", form=form)
        except HttpError as exc:
            raise _wrap(exc) from None
        if not done.get("success", False):
            raise PublishError(f"Facebook did not accept the Reel: {done}")
        return Result(status, video_id, f"https://www.facebook.com/reel/{video_id}")


class Instagram(Adapter):
    platform = "instagram"

    def publish(self, post: Dict[str, Any], video: Path, slot_at: datetime, cfg: Dict[str, Any]) -> Result:
        apps = auth.load_apps(self.tokens.secrets_dir)
        base, version = auth.graph(apps), auth.graph(apps).rsplit("/", 1)[1]
        ig = str(cfg["ig_user_id"])
        token = self.tokens.page_for_ig(ig)["access_token"]
        try:
            container = call(self.transport, "POST", f"{base}/{ig}/media", form={
                "media_type": "REELS", "upload_type": "resumable", "share_to_feed": "true",
                "caption": post["platforms"]["instagram"]["caption"], "access_token": token})
            cid = container["id"]
            _rupload(self, f"https://rupload.facebook.com/ig-api-upload/{version}/{cid}", token, video)
        except HttpError as exc:
            raise _wrap(exc) from None
        return self.check(cid, cfg)

    def check(self, remote_id: str, cfg: Dict[str, Any]) -> Result:
        """Wait for the container to finish encoding, then publish it."""
        apps = auth.load_apps(self.tokens.secrets_dir)
        base = auth.graph(apps)
        ig = str(cfg["ig_user_id"])
        token = self.tokens.page_for_ig(ig)["access_token"]
        try:
            for _ in range(IG_POLL_LIMIT):
                st = call(self.transport, "GET", f"{base}/{remote_id}",
                          params={"fields": "status_code,status", "access_token": token})
                code = st.get("status_code")
                if code == "FINISHED":
                    break
                if code in ("ERROR", "EXPIRED"):
                    raise PublishError(f"Instagram could not process the video: {st.get('status') or code}",
                                       retry=False)
                self.sleep(IG_POLL_SECONDS)
            else:
                return Result("processing", remote_id)
            pub = call(self.transport, "POST", f"{base}/{ig}/media_publish",
                       form={"creation_id": remote_id, "access_token": token})
            media_id = pub["id"]
            link = call(self.transport, "GET", f"{base}/{media_id}",
                        params={"fields": "permalink", "access_token": token}).get("permalink")
        except HttpError as exc:
            raise _wrap(exc) from None
        return Result("posted", media_id, link)
