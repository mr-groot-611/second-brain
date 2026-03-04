from unittest.mock import MagicMock, patch
from app.processors.intent import classify_intent, Intent


def test_classifies_context():
    mock_response = MagicMock()
    mock_response.text = "CONTEXT"
    with patch("google.generativeai.GenerativeModel") as MockModel:
        MockModel.return_value.generate_content.return_value = mock_response
        result = classify_intent(
            last_entry={"title": "ElevenLabs Lead", "summary": "AI customer support tool."},
            new_message="Came up in a sales call with Ravi from Accenture"
        )
    assert result == Intent.CONTEXT


def test_classifies_done():
    mock_response = MagicMock()
    mock_response.text = "DONE"
    with patch("google.generativeai.GenerativeModel") as MockModel:
        MockModel.return_value.generate_content.return_value = mock_response
        result = classify_intent(
            last_entry={"title": "ElevenLabs Lead", "summary": "AI customer support tool."},
            new_message="nope all good"
        )
    assert result == Intent.DONE


def test_classifies_new():
    mock_response = MagicMock()
    mock_response.text = "NEW"
    with patch("google.generativeai.GenerativeModel") as MockModel:
        MockModel.return_value.generate_content.return_value = mock_response
        result = classify_intent(
            last_entry={"title": "ElevenLabs Lead", "summary": "AI customer support tool."},
            new_message="https://python.org/docs/fastapi"
        )
    assert result == Intent.NEW


def test_defaults_to_new_on_bad_response():
    mock_response = MagicMock()
    mock_response.text = "something unexpected"
    with patch("google.generativeai.GenerativeModel") as MockModel:
        MockModel.return_value.generate_content.return_value = mock_response
        result = classify_intent(
            last_entry={"title": "Test", "summary": "Test summary."},
            new_message="random message"
        )
    assert result == Intent.NEW
