from app.models import InputType, RawInput, ProcessedEntry


def test_input_type_enum():
    assert InputType.URL.value == "url"
    assert InputType.IMAGE.value == "image"
    assert InputType.PDF.value == "pdf"
    assert InputType.VOICE.value == "voice"
    assert InputType.TEXT.value == "text"


def test_raw_input_model():
    raw = RawInput(
        input_type=InputType.URL,
        content="https://example.com",
        source_url="https://example.com"
    )
    assert raw.input_type == InputType.URL


def test_processed_entry_model():
    entry = ProcessedEntry(
        title="Test Article",
        content_type="Article",
        headline="A short summary.",
        tags=["productivity"],
        source_url="https://example.com",
        raw_content="Full article text here...",
        metadata={"key_takeaway": "Do less, better"}
    )
    assert entry.title == "Test Article"
    assert len(entry.tags) == 1
    assert entry.metadata["key_takeaway"] == "Do less, better"


def test_processed_entry_metadata_defaults_empty():
    entry = ProcessedEntry(
        title="Test",
        content_type="Note",
        headline="A note.",
        tags=[],
        raw_content="some text"
    )
    assert entry.metadata == {}
