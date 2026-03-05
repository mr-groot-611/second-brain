from unittest.mock import MagicMock, patch
from app.storage.notion import write_to_notion, update_notion_entry, append_to_conversation_log, _build_page_body
from app.models import ProcessedEntry


def make_entry(**kwargs):
    defaults = dict(
        title="Test Entry",
        content_type="Article",
        headline="A test summary.",
        tags=["test"],
        source_url="https://example.com",
        raw_content="Full content here.",
        metadata={},
        ai_summary="This article covers important topics.",
    )
    return ProcessedEntry(**{**defaults, **kwargs})


def test_creates_notion_page():
    entry = make_entry()
    with patch("app.storage.notion.Client") as MockClient:
        mock_pages = MagicMock()
        MockClient.return_value.pages = mock_pages
        mock_pages.create.return_value = {"id": "page-123"}
        write_to_notion(entry)
        mock_pages.create.assert_called_once()
        call_kwargs = mock_pages.create.call_args[1]
        props = call_kwargs["properties"]
        assert props["Name"]["title"][0]["text"]["content"] == "Test Entry"


def test_page_body_contains_raw_content():
    entry = make_entry(raw_content="This is the full article text.")
    with patch("app.storage.notion.Client") as MockClient:
        mock_pages = MagicMock()
        MockClient.return_value.pages = mock_pages
        mock_pages.create.return_value = {"id": "page-123"}
        write_to_notion(entry)
        call_kwargs = mock_pages.create.call_args[1]
        children = call_kwargs["children"]
        assert any("This is the full article text." in str(block) for block in children)


def test_updates_existing_notion_page():
    with patch("app.storage.notion.Client") as MockClient:
        mock_blocks = MagicMock()
        MockClient.return_value.blocks = MagicMock()
        MockClient.return_value.blocks.children = mock_blocks
        update_notion_entry("page-123", "Additional context: Ravi from Accenture mentioned this.")
        mock_blocks.append.assert_called_once()


def test_metadata_stored_as_json_blob():
    entry = make_entry(
        content_type="Contact",
        metadata={
            "contact_name": "John Smith",
            "company": "Verdant",
        }
    )
    with patch("app.storage.notion.Client") as MockClient:
        mock_pages = MagicMock()
        MockClient.return_value.pages = mock_pages
        mock_pages.create.return_value = {"id": "page-123"}
        write_to_notion(entry)
        props = mock_pages.create.call_args[1]["properties"]
        metadata_text = props["Metadata"]["rich_text"][0]["text"]["content"]
        assert "John Smith" in metadata_text
        assert "Verdant" in metadata_text


def test_headline_stored_in_notion():
    entry = make_entry(headline="Key insight for scanning later.")
    with patch("app.storage.notion.Client") as MockClient:
        mock_pages = MagicMock()
        MockClient.return_value.pages = mock_pages
        mock_pages.create.return_value = {"id": "page-123"}
        write_to_notion(entry)
        props = mock_pages.create.call_args[1]["properties"]
        assert props["Headline"]["rich_text"][0]["text"]["content"] == "Key insight for scanning later."


# --- Structured page body tests (Task 2) ---

def test_page_body_has_ai_summary_section():
    """AI Summary heading + content appears first in page body."""
    entry = make_entry(ai_summary="This is the AI analysis of the content.")
    blocks = _build_page_body(entry)

    # First block is AI Summary heading
    assert blocks[0]["type"] == "heading_2"
    assert blocks[0]["heading_2"]["rich_text"][0]["text"]["content"] == "AI Summary"

    # Second block is the summary content
    assert blocks[1]["type"] == "paragraph"
    assert "AI analysis" in blocks[1]["paragraph"]["rich_text"][0]["text"]["content"]


def test_page_body_has_raw_content_section():
    """Raw Content heading + content appears after AI Summary."""
    entry = make_entry(raw_content="The raw scraped article text.")
    blocks = _build_page_body(entry)

    # Find the Raw Content heading
    raw_heading_idx = None
    for i, b in enumerate(blocks):
        if b.get("type") == "heading_2":
            text = b["heading_2"]["rich_text"][0]["text"]["content"]
            if text == "Raw Content":
                raw_heading_idx = i
                break

    assert raw_heading_idx is not None
    # Next block after heading is the raw content
    assert "raw scraped article" in blocks[raw_heading_idx + 1]["paragraph"]["rich_text"][0]["text"]["content"]


def test_page_body_has_conversation_section():
    """Conversation heading appears last, with initial user message."""
    entry = make_entry(original_message="Check out this article")
    blocks = _build_page_body(entry)

    # Find Conversation heading
    conv_heading_idx = None
    for i, b in enumerate(blocks):
        if b.get("type") == "heading_2":
            text = b["heading_2"]["rich_text"][0]["text"]["content"]
            if text == "Conversation":
                conv_heading_idx = i
                break

    assert conv_heading_idx is not None
    # Next block should have the user's message
    conv_block = blocks[conv_heading_idx + 1]
    assert "Varun: Check out this article" in conv_block["paragraph"]["rich_text"][0]["text"]["content"]


def test_page_body_section_order():
    """Verify sections appear in order: AI Summary → Raw Content → Conversation."""
    entry = make_entry(
        ai_summary="Summary here.",
        raw_content="Raw content here.",
        original_message="User message."
    )
    blocks = _build_page_body(entry)

    headings = [
        b["heading_2"]["rich_text"][0]["text"]["content"]
        for b in blocks if b.get("type") == "heading_2"
    ]
    assert headings == ["AI Summary", "Raw Content", "Conversation"]


def test_page_body_dividers_between_sections():
    """Divider blocks separate the three sections."""
    entry = make_entry()
    blocks = _build_page_body(entry)
    divider_count = sum(1 for b in blocks if b.get("type") == "divider")
    assert divider_count == 2  # between Summary/Raw and Raw/Conversation


def test_page_body_empty_ai_summary():
    """When ai_summary is empty, show placeholder text."""
    entry = make_entry(ai_summary="")
    blocks = _build_page_body(entry)

    # First heading is AI Summary, second block should be placeholder
    assert blocks[1]["type"] == "paragraph"
    assert "No AI summary" in blocks[1]["paragraph"]["rich_text"][0]["text"]["content"]


def test_page_body_stays_under_100_blocks():
    """Very long raw content should be truncated to stay under 100 blocks."""
    # Create entry with raw content that would produce ~120 paragraph blocks
    long_content = "x" * 2000 * 120  # 120 chunks of 2000 chars
    entry = make_entry(raw_content=long_content, ai_summary="Short summary.")
    blocks = _build_page_body(entry)
    assert len(blocks) <= 100


# --- Conversation log append tests (Task 3) ---

def test_append_to_conversation_log():
    """append_to_conversation_log appends a paragraph block with speaker prefix."""
    with patch("app.storage.notion.Client") as MockClient:
        mock_blocks = MagicMock()
        MockClient.return_value.blocks = MagicMock()
        MockClient.return_value.blocks.children = mock_blocks

        append_to_conversation_log("page-123", "Second Brain", "✅ Saved as Article — Test Entry")

        mock_blocks.append.assert_called_once()
        call_kwargs = mock_blocks.append.call_args[1]
        block_text = call_kwargs["children"][0]["paragraph"]["rich_text"][0]["text"]["content"]
        assert block_text == "Second Brain: ✅ Saved as Article — Test Entry"


def test_append_to_conversation_log_truncates():
    """Long messages are truncated to 2000 chars."""
    with patch("app.storage.notion.Client") as MockClient:
        mock_blocks = MagicMock()
        MockClient.return_value.blocks = MagicMock()
        MockClient.return_value.blocks.children = mock_blocks

        long_msg = "x" * 3000
        append_to_conversation_log("page-123", "Varun", long_msg)

        call_kwargs = mock_blocks.append.call_args[1]
        block_text = call_kwargs["children"][0]["paragraph"]["rich_text"][0]["text"]["content"]
        assert len(block_text) <= 2000
