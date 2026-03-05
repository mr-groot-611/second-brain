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


def _heading_block(text: str) -> dict:
    """Create a heading_2 block."""
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": text}}]
        },
    }


def _paragraph_block(text: str) -> dict:
    """Create a paragraph block (text truncated to 2000 chars for Notion limit)."""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}]
        },
    }


def _divider_block() -> dict:
    """Create a divider block."""
    return {"object": "block", "type": "divider", "divider": {}}


def _build_page_body(entry: ProcessedEntry) -> list[dict]:
    """Build structured page body: AI Summary → Raw Content → Conversation Log.

    Stays within Notion's 100-block limit per request. AI Summary and
    Conversation Log are prioritised over raw content tail.
    """
    blocks = []

    # --- Section 1: AI Summary ---
    blocks.append(_heading_block("AI Summary"))
    if entry.ai_summary:
        for chunk in _chunk_text(entry.ai_summary, 2000):
            blocks.append(_paragraph_block(chunk))
    else:
        blocks.append(_paragraph_block("(No AI summary generated)"))

    blocks.append(_divider_block())

    # --- Section 2: Raw Content ---
    blocks.append(_heading_block("Raw Content"))
    raw = entry.raw_content or ""
    if raw:
        for chunk in _chunk_text(raw, 2000):
            blocks.append(_paragraph_block(chunk))
    else:
        blocks.append(_paragraph_block("(No raw content)"))

    blocks.append(_divider_block())

    # --- Section 3: Conversation Log ---
    blocks.append(_heading_block("Conversation"))
    # Initial user message
    if entry.original_message:
        blocks.append(_paragraph_block(f"Varun: {entry.original_message}"))
    elif entry.raw_content:
        # For media inputs (image, voice, pdf) where original_message may be None
        label = {
            "image": "[image]",
            "pdf": "[PDF]",
            "voice": "[voice note]",
        }.get(entry.content_type.lower(), "[media]")
        # Don't add a "Varun:" line if we truly have no original message context
    # Bot's save confirmation will be appended after write_to_notion returns

    # Enforce 100-block limit: trim raw content blocks if needed
    if len(blocks) > 100:
        # Count non-raw-content blocks (summary + headings + dividers + conversation)
        # Raw content starts at index after "Raw Content" heading (find it)
        raw_start = None
        raw_end = None
        for i, b in enumerate(blocks):
            if b.get("type") == "heading_2":
                heading_text = b["heading_2"]["rich_text"][0]["text"]["content"]
                if heading_text == "Raw Content":
                    raw_start = i + 1
                elif heading_text == "Conversation" and raw_start is not None:
                    # The divider before Conversation
                    raw_end = i - 1  # divider index
                    break

        if raw_start and raw_end:
            # Keep only enough raw content blocks to stay under 100
            overhead = len(blocks) - (raw_end - raw_start)
            max_raw_blocks = 100 - overhead
            if max_raw_blocks < 1:
                max_raw_blocks = 1
            raw_blocks = blocks[raw_start:raw_end]
            blocks = blocks[:raw_start] + raw_blocks[:max_raw_blocks] + blocks[raw_end:]

    return blocks[:100]


def write_to_notion(entry: ProcessedEntry) -> str:
    """Write a ProcessedEntry to Notion with structured page body.
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

    children = _build_page_body(entry)

    try:
        response = client.pages.create(
            parent={"database_id": settings.notion_database_id},
            properties=properties,
            children=children,
        )
    except APIResponseError as e:
        logger.exception("Notion write failed: %s", e)
        raise NotionError(str(e)) from e
    return response["id"]


def update_notion_entry(page_id: str, additional_context: str):
    """Append additional context to an existing Notion page body (legacy)."""
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


def update_notion_properties(page_id: str, updates: dict):
    """Update specific properties on an existing Notion page.

    Supports: headline, tags, metadata, title.
    Only updates the fields present in `updates`.
    """
    client = Client(auth=settings.notion_token)
    properties = {}

    if "title" in updates:
        properties["Name"] = {
            "title": [{"text": {"content": updates["title"]}}]
        }
    if "headline" in updates:
        properties["Headline"] = {
            "rich_text": [{"text": {"content": str(updates["headline"])[:2000]}}]
        }
    if "tags" in updates:
        properties["Tags"] = {
            "multi_select": [{"name": tag} for tag in updates["tags"]]
        }
    if "metadata" in updates:
        metadata_str = json.dumps(updates["metadata"], ensure_ascii=False)[:2000]
        properties["Metadata"] = {
            "rich_text": [{"text": {"content": metadata_str}}]
        }

    if not properties:
        return  # nothing to update

    try:
        client.pages.update(page_id=page_id, properties=properties)
    except APIResponseError as e:
        logger.exception("Notion property update failed: %s", e)
        raise NotionError(str(e)) from e


def append_to_conversation_log(page_id: str, speaker: str, message: str):
    """Append a line to the Conversation section of an existing Notion page.

    Notion appends blocks at the end of the page, which is where the
    Conversation section lives by design.
    """
    client = Client(auth=settings.notion_token)
    text = f"{speaker}: {message}"[:2000]
    try:
        client.blocks.children.append(
            block_id=page_id,
            children=[_paragraph_block(text)]
        )
    except APIResponseError as e:
        logger.exception("Notion conversation log append failed: %s", e)
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
