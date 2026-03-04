from notion_client import Client
from app.models import ProcessedEntry
from app.config import settings


def write_to_notion(entry: ProcessedEntry) -> str:
    """Write a ProcessedEntry to Notion. Returns the created page ID."""
    client = Client(auth=settings.notion_token)

    properties = {
        "Name": {
            "title": [{"text": {"content": entry.title}}]
        },
        "Type": {
            "select": {"name": entry.content_type}
        },
        "Summary": {
            "rich_text": [{"text": {"content": entry.summary[:2000]}}]
        },
        "Tags": {
            "multi_select": [{"name": tag} for tag in entry.tags]
        },
        "Status": {
            "select": {"name": "Unread"}
        }
    }

    if entry.source_url:
        properties["Source URL"] = {"url": entry.source_url}

    if entry.entities:
        entity_text = ", ".join(entry.entities)
        properties["Entities"] = {
            "rich_text": [{"text": {"content": entity_text[:2000]}}]
        }

    # Map type-specific metadata fields to Notion properties
    m = entry.metadata
    _set_text(properties, "Contact Name", m.get("contact_name"))
    _set_text(properties, "Company", m.get("company"))
    _set_text(properties, "Role", m.get("role"))
    _set_text(properties, "Where Met", m.get("where_met"))
    _set_text(properties, "Author", m.get("author"))
    _set_text(properties, "Recommended By", m.get("recommended_by"))
    _set_text(properties, "Cook Time", m.get("cook_time"))
    _set_text(properties, "Product Name", m.get("product_name"))
    _set_text(properties, "Category", m.get("category"))
    _set_text(properties, "Price Range", m.get("price_range"))
    _set_text(properties, "Key Takeaway", m.get("key_takeaway"))
    _set_text(properties, "Mentioned By", m.get("mentioned_by"))
    _set_text(properties, "Use Case", m.get("use_case"))
    _set_text(properties, "Problem", m.get("problem"))
    _set_text(properties, "Solution", m.get("solution"))
    _set_text(properties, "Hypothesis", m.get("hypothesis"))
    _set_text(properties, "Next Step", m.get("next_step"))

    if m.get("genre"):
        properties["Genre"] = {"select": {"name": m["genre"]}}
    if m.get("page_count") and isinstance(m["page_count"], int):
        properties["Page Count"] = {"number": m["page_count"]}
    if m.get("cuisine"):
        properties["Cuisine"] = {"select": {"name": m["cuisine"]}}
    if m.get("dietary") and isinstance(m["dietary"], list):
        properties["Dietary"] = {"multi_select": [{"name": d} for d in m["dietary"]]}

    # Store full content in page body (critical for future vector search)
    content_chunks = _chunk_text(entry.raw_content, 2000)
    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}]
            }
        }
        for chunk in content_chunks
    ]

    response = client.pages.create(
        parent={"database_id": settings.notion_database_id},
        properties=properties,
        children=children[:100]  # Notion API limit: 100 blocks per request
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


def _set_text(properties: dict, field: str, value):
    """Helper: set a rich_text Notion property only if value is present."""
    if value:
        properties[field] = {"rich_text": [{"text": {"content": str(value)[:2000]}}]}


def _chunk_text(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] if text else [""]
