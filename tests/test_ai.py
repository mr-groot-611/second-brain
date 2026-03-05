"""Tests for app.processors.ai — AI processing with Groq."""

import json
from unittest.mock import MagicMock, patch
from app.models import RawInput, InputType
from app.processors.ai import process_with_ai


def _mock_groq_response(data: dict) -> MagicMock:
    """Build a mock Groq chat completion response containing JSON data."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(data)
    return response


def test_ai_summary_extracted_from_response():
    """Verify ai_summary is parsed from the AI JSON output."""
    ai_output = {
        "title": "Claude UI Design Skill",
        "content_type": "Article",
        "headline": "Achieves 80% accurate UI on first output.",
        "tags": ["ai", "design", "claude"],
        "metadata": {"key_takeaway": "Useful for rapid prototyping"},
        "ai_summary": "This article describes a new Claude skill for generating UI designs. The key innovation is achieving 80% accuracy on first output, reducing iteration cycles significantly."
    }
    mock_response = _mock_groq_response(ai_output)

    with patch("app.processors.ai.client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        raw = RawInput(
            input_type=InputType.TEXT,
            content="Article about Claude UI design skill...",
            original_message="Article about Claude UI design skill..."
        )
        result = process_with_ai(raw)

    assert result.ai_summary == ai_output["ai_summary"]
    assert result.title == "Claude UI Design Skill"
    assert result.headline == "Achieves 80% accurate UI on first output."


def test_ai_summary_defaults_empty_when_missing():
    """If the AI response doesn't include ai_summary, it defaults to empty string."""
    ai_output = {
        "title": "Quick Note",
        "content_type": "Note",
        "headline": "A simple note.",
        "tags": ["note"],
        "metadata": {}
        # no ai_summary field
    }
    mock_response = _mock_groq_response(ai_output)

    with patch("app.processors.ai.client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        raw = RawInput(
            input_type=InputType.TEXT,
            content="Just a quick note",
            original_message="Just a quick note"
        )
        result = process_with_ai(raw)

    assert result.ai_summary == ""


def test_ai_summary_empty_on_json_parse_failure():
    """On JSON parse failure, ai_summary defaults to empty string."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "This is not valid JSON at all"

    with patch("app.processors.ai.client") as mock_client:
        mock_client.chat.completions.create.return_value = response
        raw = RawInput(
            input_type=InputType.TEXT,
            content="Some content",
            original_message="Some content"
        )
        result = process_with_ai(raw)

    assert result.ai_summary == ""
    assert result.title == "Saved Item"  # fallback


def test_image_input_uses_vision_model():
    """Image inputs should use the vision model and still parse ai_summary."""
    ai_output = {
        "title": "Business Card — Sarah Chen",
        "content_type": "Contact",
        "headline": "ML engineer at Stripe, met at YC Demo Day.",
        "tags": ["contact", "stripe", "ml"],
        "metadata": {"contact_name": "Sarah Chen", "company": "Stripe"},
        "ai_summary": "Business card for Sarah Chen, a machine learning engineer at Stripe. The card includes her email and was collected at YC Demo Day."
    }
    mock_response = _mock_groq_response(ai_output)

    with patch("app.processors.ai.client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        raw = RawInput(
            input_type=InputType.IMAGE,
            content="base64encodedimagedata",
            original_message="Met this person at YC"
        )
        result = process_with_ai(raw)

    # Verify vision model was used
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert "llama-4-scout" in call_kwargs["model"]
    assert call_kwargs["max_tokens"] == 2048

    assert result.ai_summary == ai_output["ai_summary"]
    assert result.raw_content == ""  # image base64 should not be stored


def test_max_tokens_is_2048():
    """Verify max_tokens was increased to 2048 to accommodate ai_summary."""
    ai_output = {
        "title": "Test",
        "content_type": "Note",
        "headline": "Test.",
        "tags": [],
        "metadata": {},
        "ai_summary": "A summary."
    }
    mock_response = _mock_groq_response(ai_output)

    with patch("app.processors.ai.client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        raw = RawInput(
            input_type=InputType.TEXT,
            content="Test content",
            original_message="Test content"
        )
        process_with_ai(raw)

    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["max_tokens"] == 2048


def test_code_fenced_json_is_stripped():
    """AI sometimes wraps JSON in ```json ... ``` — verify we strip it."""
    ai_output = {
        "title": "Fenced",
        "content_type": "Note",
        "headline": "Test.",
        "tags": [],
        "metadata": {},
        "ai_summary": "A summary."
    }
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = f"```json\n{json.dumps(ai_output)}\n```"

    with patch("app.processors.ai.client") as mock_client:
        mock_client.chat.completions.create.return_value = response
        raw = RawInput(
            input_type=InputType.TEXT,
            content="Test",
            original_message="Test"
        )
        result = process_with_ai(raw)

    assert result.title == "Fenced"
    assert result.ai_summary == "A summary."
