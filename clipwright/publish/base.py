"""What every platform adapter provides, and the errors the publisher understands."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class Result:
    status: str                      # "posted", "scheduled" or "processing"
    remote_id: Optional[str] = None
    url: Optional[str] = None


class PublishError(Exception):
    """An upload failed. ``retry`` says whether trying again later can help."""

    def __init__(self, message: str, retry: bool = True):
        super().__init__(message)
        self.retry = retry


class Adapter:
    platform = ""

    def __init__(self, transport, tokens, db=None, sleep=None):
        import time
        self.transport = transport
        self.tokens = tokens          # auth.TokenStore for this brand
        self.db = db
        self.sleep = sleep or time.sleep

    def publish(self, post: Dict[str, Any], video: Path, slot_at: datetime, cfg: Dict[str, Any]) -> Result:
        raise NotImplementedError

    def check(self, remote_id: str, cfg: Dict[str, Any]) -> Result:
        """Follow up on a "processing" upload."""
        raise NotImplementedError
