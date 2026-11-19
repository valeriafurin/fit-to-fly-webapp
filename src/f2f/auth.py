from __future__ import annotations

import secrets
import time

ADMIN_COOKIE = "f2f_admin"


class AdminSessions:
    """TL sessions held in memory; restarting the server signs everyone out."""

    def __init__(self, passcode: str | None, ttl_hours: float) -> None:
        self.passcode = passcode or secrets.token_urlsafe(9)
        self._ttl = ttl_hours * 3600
        self._sessions: dict[str, tuple[float, str]] = {}
        self.oauth_states: dict[str, float] = {}

    def check_passcode(self, attempt: str) -> bool:
        return secrets.compare_digest(attempt.strip().encode(), self.passcode.encode())

    def create(self, identity: str) -> str:
        sid = secrets.token_urlsafe(32)
        self._sessions[sid] = (time.time() + self._ttl, identity)
        return sid

    def identity(self, sid: str | None) -> str | None:
        if not sid:
            return None
        entry = self._sessions.get(sid)
        if entry is None:
            return None
        expires, who = entry
        if expires < time.time():
            self._sessions.pop(sid, None)
            return None
        return who

    def destroy(self, sid: str | None) -> None:
        if sid:
            self._sessions.pop(sid, None)

    def new_state(self) -> str:
        state = secrets.token_urlsafe(24)
        self.oauth_states[state] = time.time() + 600
        return state

    def consume_state(self, state: str) -> bool:
        expires = self.oauth_states.pop(state, 0.0)
        return expires > time.time()
