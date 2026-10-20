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

class RedisStreamsBus(Bus):
    """Real Redis Streams adapter (redis-py). Optional: used only when REDIS_URL is set; InProcessBus is the default.
    Idempotency via SET NX, consumer groups for leases, XAUTOCLAIM for lease timeouts, a '<topic>:dlq' stream after
    max_attempts, and backpressure via XLEN >= max_depth."""
    def __init__(self, client=None, url: str | None = None, group="crew", max_depth=1000, max_attempts=3, idem_ttl_s=86400):
        if client is None:
            import redis
            client = redis.Redis.from_url(url)
        self.r, self.group, self.max_depth, self.max_attempts, self.idem_ttl_s = client, group, max_depth, max_attempts, idem_ttl_s
        self.stats = {"published":0,"duplicates":0,"dead":0,"rejected_backpressure":0,"acked":0}
        self._groups: set[str] = set()
    def _g(self, topic):
        if topic in self._groups: return
        try: self.r.xgroup_create(topic, self.group, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e): raise
        self._groups.add(topic)
    async def publish(self, topic, ev):
        self._g(topic)
        if self.r.xlen(topic) >= self.max_depth:
            self.stats["rejected_backpressure"] += 1; raise Backpressure(f"{topic} depth >= {self.max_depth}")
        if not self.r.set(f"idem:{ev.idempotency_key}", 1, nx=True, ex=self.idem_ttl_s):
            self.stats["duplicates"] += 1; return False
        self.r.xadd(topic, {"event": _dump(ev)}); self.stats["published"] += 1; return True
    async def lease(self, topic, consumer, timeout_s):
        self._g(topic)
        claimed = self.r.xautoclaim(topic, self.group, consumer, min_idle_time=int(timeout_s*1000), start_id="0-0", count=1)
        msgs = claimed[1] if claimed and claimed[1] else []
        if not msgs:
            got = self.r.xreadgroup(self.group, consumer, {topic: ">"}, count=1)
            msgs = got[0][1] if got else []
        if not msgs: return None
        mid, fields = msgs[0]
        info = self.r.xpending_range(topic, self.group, min=mid, max=mid, count=1)
        attempts = info[0]["times_delivered"] if info else 1
        ev = _load(fields[b"event"] if b"event" in fields else fields["event"])
        if attempts > self.max_attempts:
            self.r.xadd(f"{topic}:dlq", {"event": _dump(ev), "reason": "max attempts"}); self.r.xack(topic, self.group, mid)
            self.stats["dead"] += 1; return None
        l = Lease(ev, consumer, time.monotonic()+timeout_s, attempts); l.msg_id = mid; return l
    async def ack(self, topic, lease):
        if self.r.xack(topic, self.group, lease.msg_id): self.stats["acked"] += 1
    async def nack(self, topic, lease, reason):
        self.r.xack(topic, self.group, lease.msg_id)
        if lease.attempts >= self.max_attempts:
            self.r.xadd(f"{topic}:dlq", {"event": _dump(lease.event), "reason": reason}); self.stats["dead"] += 1
        else:
            self.r.xadd(topic, {"event": _dump(lease.event)})
    def dlq(self, topic): return [_load(f.get(b"event", f.get("event"))) for _, f in self.r.xrange(f"{topic}:dlq")]

def _dump(ev: Event) -> str:
    import json, dataclasses
    d = dataclasses.asdict(ev); return json.dumps(d, default=lambda x: x.isoformat() if hasattr(x, "isoformat") else str(x))
def _load(raw) -> Event:
    import json, dataclasses
    d = json.loads(raw); ts = [f.name for f in dataclasses.fields(Event) if f.name == "ts"]
    if ts: d["ts"] = datetime.fromisoformat(d["ts"])
    return Event(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items()})
