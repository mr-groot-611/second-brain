from unittest.mock import MagicMock
from app.extractors.detector import detect_input_type
from app.models import InputType


def make_message(text=None, photo=None, document=None, voice=None):
    msg = MagicMock()
    msg.text = text
    msg.photo = photo
    msg.document = document
    msg.voice = voice
    return msg


def test_detects_url():
    msg = make_message(text="https://reddit.com/r/productivity/comments/abc")
    assert detect_input_type(msg) == InputType.URL


def test_detects_plain_text():
    msg = make_message(text="Just a random thought I want to save")
    assert detect_input_type(msg) == InputType.TEXT


def test_detects_image():
    msg = make_message(photo=[MagicMock()])
    assert detect_input_type(msg) == InputType.IMAGE


def test_detects_pdf():
    doc = MagicMock()
    doc.mime_type = "application/pdf"
    msg = make_message(document=doc)
    assert detect_input_type(msg) == InputType.PDF


def test_detects_voice():
    msg = make_message(voice=MagicMock())
    assert detect_input_type(msg) == InputType.VOICE
