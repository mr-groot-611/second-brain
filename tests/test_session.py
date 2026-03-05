import time
from unittest.mock import patch
from app.session import SessionStore


def test_stores_and_retrieves_last_entry():
    store = SessionStore()
    store.set(123, {"page_id": "abc", "title": "Test", "type": "Lead", "headline": "A test."})
    entry = store.get(123)
    assert entry["page_id"] == "abc"


def test_returns_none_for_unknown_user():
    store = SessionStore()
    assert store.get(999) is None


def test_clears_entry():
    store = SessionStore()
    store.set(123, {"page_id": "abc", "title": "Test", "type": "Note", "headline": "."})
    store.clear(123)
    assert store.get(123) is None


def test_set_adds_timestamp_automatically():
    store = SessionStore()
    before = time.time()
    store.set(123, {"page_id": "abc", "title": "Test"})
    after = time.time()
    entry = store.get(123)
    assert before <= entry["last_interaction_at"] <= after


def test_set_adds_bot_last_message_default():
    store = SessionStore()
    store.set(123, {"page_id": "abc"})
    entry = store.get(123)
    assert entry["bot_last_message"] == ""


def test_is_expired_returns_true_when_no_session():
    store = SessionStore()
    assert store.is_expired(999) is True


def test_is_expired_returns_false_when_fresh():
    store = SessionStore()
    store.set(123, {"page_id": "abc"})
    assert store.is_expired(123) is False


def test_is_expired_returns_true_and_clears_after_ttl():
    store = SessionStore()
    store.set(123, {"page_id": "abc"})

    # Advance time by 6 minutes (360 seconds > 300 TTL)
    future_time = time.time() + 360
    with patch("app.session.time") as mock_time:
        mock_time.time.return_value = future_time
        assert store.is_expired(123) is True
    assert store.get(123) is None


def test_is_expired_custom_ttl():
    store = SessionStore()
    store.set(123, {"page_id": "abc"})

    # With 1-second TTL, should expire almost immediately after a small delay
    future_time = time.time() + 2
    with patch("app.session.time") as mock_time:
        mock_time.time.return_value = future_time
        assert store.is_expired(123, ttl_seconds=1) is True


def test_update_interaction_refreshes_timestamp():
    store = SessionStore()
    store.set(123, {"page_id": "abc"})
    original_ts = store.get(123)["last_interaction_at"]

    # Small sleep to ensure different timestamp
    future_time = original_ts + 10
    with patch("app.session.time") as mock_time:
        mock_time.time.return_value = future_time
        store.update_interaction(123)
    assert store.get(123)["last_interaction_at"] == future_time


def test_update_interaction_sets_bot_message():
    store = SessionStore()
    store.set(123, {"page_id": "abc"})
    store.update_interaction(123, bot_message="✅ Saved as Contact — Sarah Chen")
    assert store.get(123)["bot_last_message"] == "✅ Saved as Contact — Sarah Chen"


def test_update_interaction_noop_for_missing_session():
    store = SessionStore()
    # Should not raise
    store.update_interaction(999, bot_message="hello")
