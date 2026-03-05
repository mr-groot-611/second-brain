"""Tests for app.processors.intent — intent classification with Groq."""

import time
from unittest.mock import MagicMock, patch
from app.processors.intent import classify_intent, Intent, _format_elapsed


def _make_session(**kwargs):
    defaults = {
        "page_id": "page-123",
        "title": "Sarah Chen Contact",
        "type": "Contact",
        "headline": "ML engineer met at YC Demo Day.",
        "tags": ["contact", "ml", "yc"],
        "bot_last_message": "✅ Saved as Contact — Sarah Chen",
        "last_interaction_at": time.time() - 30,  # 30 seconds ago
    }
    defaults.update(kwargs)
    return defaults


def _mock_groq_response(intent_text: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = intent_text
    return response


def test_classifies_context():
    session = _make_session()
    with patch("app.processors.intent.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_groq_response("CONTEXT")
        result = classify_intent(session, "She's at Stripe, ML team")
    assert result == Intent.CONTEXT


def test_classifies_done():
    session = _make_session()
    with patch("app.processors.intent.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_groq_response("DONE")
        result = classify_intent(session, "thanks")
    assert result == Intent.DONE


def test_classifies_new():
    session = _make_session()
    with patch("app.processors.intent.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_groq_response("NEW")
        result = classify_intent(session, "https://example.com/unrelated-article")
    assert result == Intent.NEW


def test_defaults_to_new_on_invalid_response():
    session = _make_session()
    with patch("app.processors.intent.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_groq_response("MAYBE")
        result = classify_intent(session, "something")
    assert result == Intent.NEW


def test_prompt_includes_rich_context():
    """Verify the prompt includes type, tags, bot_last_message, and elapsed time."""
    session = _make_session(
        bot_last_message="What company is Sarah at?",
        tags=["contact", "networking"],
    )
    with patch("app.processors.intent.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_groq_response("CONTEXT")
        classify_intent(session, "Stripe")

        # Check the prompt sent to the model
        call_args = mock_client.chat.completions.create.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "Contact" in prompt  # type
        assert "contact, networking" in prompt  # tags
        assert "What company is Sarah at?" in prompt  # bot_last_message
        assert "seconds ago" in prompt  # elapsed time


def test_handles_missing_optional_fields():
    """Gracefully handles session with missing optional fields."""
    session = {
        "page_id": "page-123",
        "title": "Quick Note",
        "type": "Note",
        "headline": "A note.",
    }
    with patch("app.processors.intent.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_groq_response("CONTEXT")
        result = classify_intent(session, "more details")
    assert result == Intent.CONTEXT


def test_format_elapsed_seconds():
    assert "30 seconds ago" == _format_elapsed(time.time() - 30)


def test_format_elapsed_minutes():
    assert "3 minutes ago" == _format_elapsed(time.time() - 180)


def test_format_elapsed_hours():
    assert "2 hours ago" == _format_elapsed(time.time() - 7200)


def test_format_elapsed_unknown():
    assert "unknown" == _format_elapsed(0)
