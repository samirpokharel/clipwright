"""TikTok Direct Post through the Content Posting API.

creator_info/query (allowed privacy levels, max duration) -> video/init with FILE_UPLOAD ->
PUT the chunks to upload_url -> poll status/fetch until PUBLISH_COMPLETE.
TikTok has no API scheduling, so the publisher calls this at the slot time.
Until the app passes TikTok's audit, posts can only be SELF_ONLY (private): set
"audited": true under platforms.tiktok in accounts.json once TikTok approves the app.
Flow and field names follow TikTok's Content Posting API docs; not yet run against a live account here.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .base import Adapter, PublishError, Result
from .http import HttpError, call

API = "https://open.tiktokapis.com/v2/post/publish"
MIN_CHUNK = 5 * 1024 * 1024
CHUNK = 10 * 1024 * 1024
POLL_SECONDS = 10
POLL_LIMIT = 30


def chunks(size: int, chunk: int = CHUNK) -> List[Tuple[int, int]]:
    """Byte ranges as TikTok wants them: whole file under 5 MB, else equal chunks with the
    remainder folded into the last one (so total_chunk_count = size // chunk)."""
    if size <= MIN_CHUNK:
        return [(0, size - 1)]
    count = max(1, size // chunk)
    out = [(i * chunk, (i + 1) * chunk - 1) for i in range(count)]
    out[-1] = (out[-1][0], size - 1)
    return out


def _ok(resp: Dict[str, Any]) -> Dict[str, Any]:
    err = resp.get("error") or {}
    if err.get("code") not in (None, "ok"):
        retry = err.get("code") in ("rate_limit_exceeded", "internal_error")
        raise PublishError(f"TikTok: {err.get('code')}: {err.get('message')}", retry=retry)
    return resp.get("data") or {}


class TikTok(Adapter):
    platform = "tiktok"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens.access('tiktok')}"}

    def publish(self, post: Dict[str, Any], video: Path, slot_at: datetime, cfg: Dict[str, Any]) -> Result:
        data = video.read_bytes()
        try:
            info = _ok(call(self.transport, "POST", f"{API}/creator_info/query/", json_body={},
                            headers=self._headers()))
            options = info.get("privacy_level_options") or []
            if cfg.get("audited") and "PUBLIC_TO_EVERYONE" in options:
                privacy = "PUBLIC_TO_EVERYONE"
            elif "SELF_ONLY" in options:
                privacy = "SELF_ONLY"
            else:
                raise PublishError(f"TikTok offers none of the privacy levels we use: {options}", retry=False)
            limit = info.get("max_video_post_duration_sec")
            if limit and post["duration"] > limit:
                raise PublishError(f"clip is {post['duration']}s; this TikTok account allows {limit}s", retry=False)
            ranges = chunks(len(data))
            init = _ok(call(self.transport, "POST", f"{API}/video/init/", headers=self._headers(), json_body={
                "post_info": {"title": post["platforms"]["tiktok"]["caption"], "privacy_level": privacy,
                              "disable_comment": False, "disable_duet": False, "disable_stitch": False,
                              "video_cover_timestamp_ms": 1000},
                "source_info": {"source": "FILE_UPLOAD", "video_size": len(data),
                                "chunk_size": ranges[0][1] + 1 if len(ranges) > 1 else len(data),
                                "total_chunk_count": len(ranges)}}))
            publish_id, upload_url = init["publish_id"], init["upload_url"]
            for a, b in ranges:
                call(self.transport, "PUT", upload_url, body=data[a:b + 1], ok=(200, 201, 206), raw=True,
                     timeout=600, headers={"Content-Type": "video/mp4", "Content-Length": str(b - a + 1),
                                           "Content-Range": f"bytes {a}-{b}/{len(data)}"})
        except HttpError as exc:
            raise PublishError(str(exc), retry=exc.retryable) from None
        return self.check(publish_id, cfg)

    def check(self, remote_id: str, cfg: Dict[str, Any]) -> Result:
        try:
            for _ in range(POLL_LIMIT):
                st = _ok(call(self.transport, "POST", f"{API}/status/fetch/", headers=self._headers(),
                              json_body={"publish_id": remote_id}))
                status = st.get("status")
                if status == "PUBLISH_COMPLETE":
                    ids = st.get("publicaly_available_post_id") or []   # sic, TikTok's spelling
                    url = f"https://www.tiktok.com/video/{ids[0]}" if ids else None
                    return Result("posted", remote_id, url)
                if status == "FAILED":
                    raise PublishError(f"TikTok rejected the post: {st.get('fail_reason')}", retry=False)
                self.sleep(POLL_SECONDS)
        except HttpError as exc:
            raise PublishError(str(exc), retry=exc.retryable) from None
        return Result("processing", remote_id)
