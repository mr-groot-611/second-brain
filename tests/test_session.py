from app.session import SessionStore


def test_stores_and_retrieves_last_entry():
    store = SessionStore()
    store.set(123, {"page_id": "abc", "title": "Test", "type": "Lead", "summary": "A test."})
    entry = store.get(123)
    assert entry["page_id"] == "abc"


def test_returns_none_for_unknown_user():
    store = SessionStore()
    assert store.get(999) is None


def test_clears_entry():
    store = SessionStore()
    store.set(123, {"page_id": "abc", "title": "Test", "type": "Note", "summary": "."})
    store.clear(123)
    assert store.get(123) is None
