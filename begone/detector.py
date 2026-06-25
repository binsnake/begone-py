"""Per-user image-burst tracking.

Spam bots post a small set of images across several public channels in a short
window. We keep a sliding-window deque of each user's image-bearing messages
(timestamp + channel + message reference) and report when the burst thresholds
are crossed. Time is injected so the logic is testable without a real clock.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable

from .config import BurstConfig


@dataclass
class TrackedImage:
    ts: float
    channel_id: int
    message_id: int
    attachment_urls: tuple[str, ...]


@dataclass
class BurstResult:
    triggered: bool
    distinct_channels: int
    image_messages: int
    images: list[TrackedImage] = field(default_factory=list)


class BurstTracker:
    def __init__(self, config: BurstConfig, clock: Callable[[], float] = time.monotonic):
        self.config = config
        self._clock = clock
        self._by_user: dict[int, deque[TrackedImage]] = defaultdict(deque)

    def _prune(self, user_id: int, now: float) -> deque[TrackedImage]:
        dq = self._by_user[user_id]
        cutoff = now - self.config.window_seconds
        while dq and dq[0].ts < cutoff:
            dq.popleft()
        return dq

    def record(
        self,
        user_id: int,
        channel_id: int,
        message_id: int,
        attachment_urls: tuple[str, ...],
    ) -> BurstResult:
        """Record an image message and evaluate the user's current burst."""
        now = self._clock()
        dq = self._prune(user_id, now)
        dq.append(TrackedImage(now, channel_id, message_id, attachment_urls))

        images = list(dq)
        distinct_channels = len({img.channel_id for img in images})
        image_messages = len(images)

        triggered = (
            distinct_channels >= self.config.min_distinct_channels
            or image_messages >= self.config.min_image_messages
        )
        return BurstResult(
            triggered=triggered,
            distinct_channels=distinct_channels,
            image_messages=image_messages,
            images=images,
        )

    def clear_user(self, user_id: int) -> None:
        """Drop a user's history (call after acting, to avoid re-triggering)."""
        self._by_user.pop(user_id, None)
