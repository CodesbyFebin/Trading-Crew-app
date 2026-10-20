"""Event bus: abstract interface + in-process asyncio implementation."""
from __future__ import annotations
import abc, asyncio, time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from .models import Event

class Backpressure(Exception): pass
class RateLimited(Exception):
    """Simulated upstream 429."""

@dataclass
class Lease:
    event: Event; consumer: str; deadline: float; attempts: int

class Bus(abc.ABC):
    @abc.abstractmethod
    async def publish(self, topic: str, ev: Event) -> bool: ...
    @abc.abstractmethod
    async def lease(self, topic: str, consumer: str, timeout_s: float) -> Lease | None: ...
    @abc.abstractmethod
    async def ack(self, topic: str, lease: Lease) -> None: ...
    @abc.abstractmethod
    async def nack(self, topic: str, lease: Lease, reason: str) -> None: ...

class InProcessBus(Bus):
    def __init__(self, max_depth=1000, max_attempts=3, max_age_s: float | None = 60, clock=time.monotonic):
        self.max_depth, self.max_attempts, self.max_age_s, self.clock = max_depth, max_attempts, max_age_s, clock
        self._q: dict[str, asyncio.Queue] = {}
        self._seen: set[str] = set()
        self._attempts: dict[str,int] = {}
        self._leases: dict[str, Lease] = {}
        self.dlq: list[tuple[str, Event, str]] = []
        self.stats = {"published":0,"duplicates":0,"stale":0,"dead":0,"rejected_backpressure":0,"acked":0}
        self._lock = asyncio.Lock()
    def _queue(self, t):
        return self._q.setdefault(t, asyncio.Queue(maxsize=self.max_depth))
    async def publish(self, topic, ev):
        async with self._lock:
            if ev.idempotency_key in self._seen:
                self.stats["duplicates"] += 1; return False
            q = self._queue(topic)
            if q.full():
                self.stats["rejected_backpressure"] += 1
                raise Backpressure(f"{topic} depth {q.qsize()} >= {self.max_depth}")
            self._seen.add(ev.idempotency_key); q.put_nowait(ev); self.stats["published"] += 1
            return True
    def _reap(self, topic):
        t = self.clock()
        for k, l in list(self._leases.items()):
            if l.deadline <= t:
                del self._leases[k]; self._requeue(topic, l.event, "lease timeout")
    def _requeue(self, topic, ev, reason):
        n = self._attempts.get(ev.event_id, 0)
        if n >= self.max_attempts:
            self.dlq.append((topic, ev, reason)); self.stats["dead"] += 1
        else:
            self._queue(topic).put_nowait(ev)
    async def lease(self, topic, consumer, timeout_s):
        async with self._lock:
            self._reap(topic); q = self._queue(topic)
            while not q.empty():
                ev = q.get_nowait()
                if self.max_age_s is not None and datetime.now(timezone.utc) - ev.ts > timedelta(seconds=self.max_age_s):
                    self.stats["stale"] += 1; self.dlq.append((topic, ev, "stale")); continue
                self._attempts[ev.event_id] = self._attempts.get(ev.event_id, 0) + 1
                l = Lease(ev, consumer, self.clock()+timeout_s, self._attempts[ev.event_id])
                self._leases[ev.event_id] = l; return l
            return None
    async def ack(self, topic, lease):
        async with self._lock:
            if self._leases.pop(lease.event.event_id, None): self.stats["acked"] += 1
    async def nack(self, topic, lease, reason):
        async with self._lock:
            if self._leases.pop(lease.event.event_id, None): self._requeue(topic, lease.event, reason)

class RedisStreamsBus(Bus):  # pragma: no cover - optional adapter, not wired in Phase 1
    def __init__(self, *a, **k): raise NotImplementedError("Redis Streams adapter is a Phase 2+ item")
    async def publish(self, topic, ev): ...
    async def lease(self, topic, consumer, timeout_s): ...
    async def ack(self, topic, lease): ...
    async def nack(self, topic, lease, reason): ...
