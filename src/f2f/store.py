from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from f2f.models import F2F, Panelist, utcnow


class Store:
    """Process-local, in-memory F2F store. Nothing here is ever written to disk."""

    def __init__(self, ttl_hours: float, clock: Callable[[], datetime] = utcnow) -> None:
        self._ttl = timedelta(hours=ttl_hours)
        self._clock = clock
        self._items: dict[str, F2F] = {}
        self._lock = threading.RLock()
        self.on_purge: list[Callable[[str], None]] = []

    def add(self, f2f: F2F) -> F2F:
        with self._lock:
            self._items[f2f.id] = f2f
        return f2f

    def get(self, f2f_id: str) -> F2F | None:
        self.purge_expired()
        with self._lock:
            return self._items.get(f2f_id)

    def all(self) -> list[F2F]:
        self.purge_expired()
        with self._lock:
            return sorted(self._items.values(), key=lambda f: f.created_at, reverse=True)

    def by_token(self, token: str) -> tuple[F2F, Panelist] | None:
        for f in self.all():
            p = f.panelist_by_token(token)
            if p is not None:
                return f, p
        return None

    def purge(self, f2f_id: str) -> bool:
        with self._lock:
            removed = self._items.pop(f2f_id, None) is not None
        if removed:
            for cb in self.on_purge:
                cb(f2f_id)
        return removed

    def purge_expired(self) -> int:
        cutoff = self._clock() - self._ttl
        with self._lock:
            expired = [k for k, f in self._items.items() if f.created_at < cutoff]
        for k in expired:
            self.purge(k)
        return len(expired)

    def lock(self) -> threading.RLock:
        return self._lock
