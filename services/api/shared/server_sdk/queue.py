"""Bounded in-process event queue with exponential-backoff retry."""

from __future__ import annotations

import time
import random
from dataclasses import dataclass, field


@dataclass
class QueuedBatch:
    events: list[dict]
    attempt: int = 0
    next_retry_at: float = field(default_factory=time.time)


class EventQueue:
    def __init__(self, max_size: int = 1000, max_retries: int = 5, base_retry_s: float = 2.0) -> None:
        self._queue: list[QueuedBatch] = []
        self._max_size = max_size
        self._max_retries = max_retries
        self._base_retry_s = base_retry_s

    def enqueue(self, events: list[dict]) -> bool:
        if len(self._queue) >= self._max_size:
            return False
        self._queue.append(QueuedBatch(events=events))
        return True

    def dequeue_ready(self) -> QueuedBatch | None:
        now = time.time()
        for i, item in enumerate(self._queue):
            if item.next_retry_at <= now:
                return self._queue.pop(i)
        return None

    def requeue(self, item: QueuedBatch) -> None:
        if item.attempt >= self._max_retries:
            return
        jitter = random.random()
        delay = self._base_retry_s * (2 ** item.attempt) + jitter
        self._queue.append(QueuedBatch(
            events=item.events,
            attempt=item.attempt + 1,
            next_retry_at=time.time() + delay,
        ))

    @property
    def size(self) -> int:
        return len(self._queue)

    def drain(self) -> None:
        self._queue.clear()
