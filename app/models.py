from enum import Enum
from typing import Optional
from pydantic import BaseModel


class InputType(str, Enum):
    URL = "url"
    IMAGE = "image"
    PDF = "pdf"
    VOICE = "voice"
    TEXT = "text"


class RawInput(BaseModel):
    input_type: InputType
    content: str                            # text content or base64 image
    source_url: Optional[str] = None
    file_name: Optional[str] = None         # original filename (PDFs, images)
    original_message: Optional[str] = None  # verbatim text the user sent
    file_bytes: Optional[bytes] = None      # raw bytes for Notion file upload (IMAGE + PDF only)
    file_mime_type: Optional[str] = None    # MIME type for upload (e.g. image/jpeg, application/pdf)

    class Config:
        arbitrary_types_allowed = True      # needed for bytes field


class ProcessedEntry(BaseModel):
    title: str
    content_type: str                       # Article / Reddit / Recipe / Contact / Book / Lead / Idea / etc.
    headline: str                           # one-sentence summary for scanning (replaces summary)
    tags: list[str]
    source_url: Optional[str] = None
    raw_content: str                        # always stored in full for future vector search
    original_message: Optional[str] = None  # verbatim what the user sent
    metadata: dict = {}                     # dynamic type-specific structured fields (JSON blob)
    ai_summary: str = ""                    # interpretive AI analysis (key takeaways, structured framing, etc.)
