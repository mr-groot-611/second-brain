import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionStore:
    """
    In-memory store for the last saved entry per user, with TTL-based expiry.
    Lost on server restart — acceptable failure mode (next message becomes NEW).

    Session entries include:
      page_id, title, type, headline, tags, metadata,
      bot_last_message, last_interaction_at
    """
    _store: dict = field(default_factory=dict)

    def set(self, user_id: int, entry: dict):
        """Store a session entry with an automatic timestamp."""
        entry.setdefault("last_interaction_at", time.time())
        entry.setdefault("bot_last_message", "")
        self._store[user_id] = entry

    def get(self, user_id: int) -> Optional[dict]:
        return self._store.get(user_id)

    def clear(self, user_id: int):
        self._store.pop(user_id, None)

    def is_expired(self, user_id: int, ttl_seconds: int = 300) -> bool:
        """Check if the user's session is older than ttl_seconds (default 5 min).
        If expired, auto-clears the session and returns True.
        Returns True if no session exists.
        """
        entry = self._store.get(user_id)
        if entry is None:
            return True
        elapsed = time.time() - entry.get("last_interaction_at", 0)
        if elapsed > ttl_seconds:
            self.clear(user_id)
            return True
        return False

    def update_interaction(self, user_id: int, bot_message: str = None):
        """Refresh the session timestamp and optionally update bot_last_message."""
        entry = self._store.get(user_id)
        if entry is None:
            return
        entry["last_interaction_at"] = time.time()
        if bot_message is not None:
            entry["bot_last_message"] = bot_message


# Singleton — shared across all requests in the same process
session_store = SessionStore()
