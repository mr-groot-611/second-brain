import json
from notion_client import Client
from app.models import ProcessedEntry
from app.config import settings


def write_to_notion(entry: ProcessedEntry) -> str:
    """Write a ProcessedEntry to Notion using the new 10-field schema.
    Returns the created page ID.
    """
    client = Client(auth=settings.notion_token)

    properties = {
        "Name": {
            "title": [{"text": {"content": entry.title}}]
        },
        "Type": {
            "select": {"name": entry.content_type}
        },
        "Headline": {
            "rich_text": [{"text": {"content": entry.headline[:2000]}}]
        },
        "Tags": {
            "multi_select": [{"name": tag} for tag in entry.tags]
        },
        "Starred": {
            "checkbox": False
        },
        "Metadata": {
            "rich_text": [{"text": {"content": json.dumps(entry.metadata, ensure_ascii=False)[:2000]}}]
        },
    }

    if entry.source_url:
        properties["Source URL"] = {"url": entry.source_url}

    if entry.original_message:
        properties["Original Message"] = {
            "rich_text": [{"text": {"content": entry.original_message[:2000]}}]
        }

    # Store full content in page body (critical for future vector search)
    page_content = entry.raw_content or ""
    content_chunks = _chunk_text(page_content, 2000)
    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}]
            },
        }
        for chunk in content_chunks
    ]

    response = client.pages.create(
        parent={"database_id": settings.notion_database_id},
        properties=properties,
        children=children[:100],  # Notion API limit: 100 blocks per request
    )
    return response["id"]


def update_notion_entry(page_id: str, additional_context: str):
    """Append additional context to an existing Notion page body."""
    client = Client(auth=settings.notion_token)
    client.blocks.children.append(
        block_id=page_id,
        children=[{
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"[Update] {additional_context[:2000]}"}
                }]
            }
        }]
    )


def _chunk_text(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] if text else [""]
