import json
import logging
import httpx
from notion_client import Client
from notion_client.errors import APIResponseError
from app.models import ProcessedEntry
from app.config import settings
from app.exceptions import NotionError

NOTION_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"

logger = logging.getLogger(__name__)


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

    try:
        response = client.pages.create(
            parent={"database_id": settings.notion_database_id},
            properties=properties,
            children=children[:100],  # Notion API limit: 100 blocks per request
        )
    except APIResponseError as e:
        logger.exception("Notion write failed: %s", e)
        raise NotionError(str(e)) from e
    return response["id"]


def update_notion_entry(page_id: str, additional_context: str):
    """Append additional context to an existing Notion page body."""
    client = Client(auth=settings.notion_token)
    try:
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
    except APIResponseError as e:
        logger.exception("Notion update failed: %s", e)
        raise NotionError(str(e)) from e


async def upload_and_attach_file(
    page_id: str,
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
) -> None:
    """Upload file bytes directly to Notion and embed as a block in the page body.

    Uses the Notion File Upload API (3 steps):
      1. POST /v1/file_uploads           → get upload ID
      2. POST /v1/file_uploads/{id}/send → upload bytes via multipart/form-data
      3. PATCH /v1/blocks/{page_id}/children → append image or file block

    Images render inline; PDFs appear as embedded viewers.
    Raises NotionError on any failure.
    """
    headers = {
        "Authorization": f"Bearer {settings.notion_token}",
        "Notion-Version": NOTION_VERSION,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            # Step 1: Create the file upload object
            resp = await client.post(
                f"{NOTION_API_BASE}/file_uploads",
                headers={**headers, "Content-Type": "application/json"},
                json={"mode": "single_part"},
            )
            resp.raise_for_status()
            upload_id = resp.json()["id"]

            # Step 2: Send the file bytes
            resp = await client.post(
                f"{NOTION_API_BASE}/file_uploads/{upload_id}/send",
                headers=headers,  # don't set Content-Type — httpx sets it for multipart
                files={"file": (file_name, file_bytes, mime_type)},
            )
            resp.raise_for_status()

            # Step 3: Append as a block in the page body
            if mime_type.startswith("image/"):
                block = {
                    "type": "image",
                    "image": {
                        "type": "file_upload",
                        "file_upload": {"id": upload_id},
                    },
                }
            else:  # PDF or other document
                block = {
                    "type": "file",
                    "file": {
                        "type": "file_upload",
                        "file_upload": {"id": upload_id},
                        "caption": [{"type": "text", "text": {"content": file_name}}],
                    },
                }

            resp = await client.patch(
                f"{NOTION_API_BASE}/blocks/{page_id}/children",
                headers={**headers, "Content-Type": "application/json"},
                json={"children": [block]},
            )
            resp.raise_for_status()

    except httpx.HTTPStatusError as e:
        logger.exception("Notion file upload HTTP error: %s — %s", e.response.status_code, e.response.text)
        raise NotionError(f"File upload failed: HTTP {e.response.status_code}") from e
    except Exception as e:
        logger.exception("Notion file upload failed: %s", e)
        raise NotionError(str(e)) from e


def _chunk_text(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] if text else [""]
