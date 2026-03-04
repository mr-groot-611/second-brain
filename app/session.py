from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionStore:
    """
    Simple in-memory store for the last saved entry per user.
    Lost on server restart — acceptable failure mode (next message becomes NEW).
    """
    _store: dict = field(default_factory=dict)

    def set(self, user_id: int, entry: dict):
        self._store[user_id] = entry

    def get(self, user_id: int) -> Optional[dict]:
        return self._store.get(user_id)

    def clear(self, user_id: int):
        self._store.pop(user_id, None)


# Singleton — shared across all requests in the same process
session_store = SessionStore()
