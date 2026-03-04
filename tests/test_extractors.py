import base64
from unittest.mock import patch, MagicMock
from app.extractors.url import extract_url
from app.extractors.image import prepare_image
from app.extractors.voice import transcribe_voice


def test_extracts_article_text():
    with patch("trafilatura.fetch_url") as mock_fetch, \
         patch("trafilatura.extract") as mock_extract:
        mock_fetch.return_value = "<html>...</html>"
        mock_extract.return_value = "This is the article text."
        result = extract_url("https://example.com/article")
    assert result == "This is the article text."


def test_handles_reddit_url():
    with patch("httpx.get") as mock_get:
        mock_get.return_value.json.return_value = [{
            "data": {
                "children": [{
                    "data": {
                        "title": "Great post",
                        "selftext": "Post body here",
                        "url": "https://reddit.com/..."
                    }
                }]
            }
        }, {
            "data": {
                "children": [
                    {"data": {"body": "Top comment here", "score": 500}}
                ]
            }
        }]
        result = extract_url("https://reddit.com/r/productivity/comments/abc/great_post/")
    assert "Great post" in result
    assert "Top comment here" in result


def test_returns_fallback_on_failure():
    with patch("trafilatura.fetch_url") as mock_fetch:
        mock_fetch.return_value = None
        result = extract_url("https://example.com/broken")
    assert result == ""


def test_extracts_pdf_text(tmp_path):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello from PDF")
    pdf_bytes = doc.tobytes()
    from app.extractors.pdf import extract_pdf
    result = extract_pdf(pdf_bytes)
    assert "Hello from PDF" in result


def test_prepare_image_returns_base64():
    fake_bytes = b"fake image data"
    result = prepare_image(fake_bytes)
    assert result == base64.b64encode(fake_bytes).decode()


def test_transcribes_voice_note():
    fake_audio_bytes = b"fake ogg audio data"
    mock_response = MagicMock()
    mock_response.text = "I had an idea about improving the onboarding flow"

    with patch("google.generativeai.GenerativeModel") as MockModel:
        MockModel.return_value.generate_content.return_value = mock_response
        result = transcribe_voice(fake_audio_bytes)

    assert "onboarding" in result
