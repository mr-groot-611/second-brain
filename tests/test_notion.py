from unittest.mock import MagicMock, patch
from app.storage.notion import write_to_notion, update_notion_entry
from app.models import ProcessedEntry


def make_entry(**kwargs):
    defaults = dict(
        title="Test Entry",
        content_type="Article",
        summary="A test summary.",
        tags=["test"],
        entities=["Test Author"],
        source_url="https://example.com",
        raw_content="Full content here.",
        metadata={}
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


def test_contact_metadata_maps_to_notion_properties():
    entry = make_entry(
        content_type="Contact",
        metadata={
            "contact_name": "John Smith",
            "company": "Verdant",
            "role": "Founder",
            "where_met": "Startup Grind March 2026"
        }
    )
    with patch("app.storage.notion.Client") as MockClient:
        mock_pages = MagicMock()
        MockClient.return_value.pages = mock_pages
        mock_pages.create.return_value = {"id": "page-123"}
        write_to_notion(entry)
        props = mock_pages.create.call_args[1]["properties"]
        assert "Contact Name" in props
        assert props["Contact Name"]["rich_text"][0]["text"]["content"] == "John Smith"
        assert "Where Met" in props


def test_book_metadata_maps_page_count():
    entry = make_entry(
        content_type="Book",
        metadata={"author": "James Clear", "genre": "Self-improvement", "page_count": 320}
    )
    with patch("app.storage.notion.Client") as MockClient:
        mock_pages = MagicMock()
        MockClient.return_value.pages = mock_pages
        mock_pages.create.return_value = {"id": "page-123"}
        write_to_notion(entry)
        props = mock_pages.create.call_args[1]["properties"]
        assert props["Page Count"]["number"] == 320
        assert props["Genre"]["select"]["name"] == "Self-improvement"
