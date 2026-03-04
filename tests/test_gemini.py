from unittest.mock import MagicMock, patch
from app.processors.gemini import process_with_gemini
from app.models import RawInput, InputType, ProcessedEntry


def test_processes_text_input():
    raw = RawInput(
        input_type=InputType.TEXT,
        content="I met John Smith at Startup Grind, he runs an AI company called Verdant."
    )
    mock_response = MagicMock()
    mock_response.text = '''{
        "title": "John Smith – Verdant AI",
        "content_type": "Contact",
        "summary": "Met John Smith at Startup Grind. He runs an AI company called Verdant.",
        "tags": ["networking", "AI", "startup"],
        "entities": ["John Smith", "Verdant", "Startup Grind"],
        "metadata": {"contact_name": "John Smith", "company": "Verdant"}
    }'''

    with patch("google.generativeai.GenerativeModel") as MockModel:
        MockModel.return_value.generate_content.return_value = mock_response
        result = process_with_gemini(raw)

    assert isinstance(result, ProcessedEntry)
    assert result.content_type == "Contact"
    assert "John Smith" in result.entities
    assert result.metadata["contact_name"] == "John Smith"


def test_handles_malformed_gemini_response():
    raw = RawInput(input_type=InputType.TEXT, content="some text")
    mock_response = MagicMock()
    mock_response.text = "not valid json"

    with patch("google.generativeai.GenerativeModel") as MockModel:
        MockModel.return_value.generate_content.return_value = mock_response
        result = process_with_gemini(raw)

    assert result.title == "Saved Item"
    assert result.content_type == "Note"
    assert result.metadata == {}
