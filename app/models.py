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
    content: str                        # text content or base64 image
    source_url: Optional[str] = None
    file_name: Optional[str] = None     # for PDFs


class ProcessedEntry(BaseModel):
    title: str
    content_type: str                   # Article / Reddit / Recipe / Contact / Book / Lead / Idea / etc.
    summary: str
    tags: list[str]
    entities: list[str]
    source_url: Optional[str] = None
    raw_content: str                    # always stored in full for future vector search
    metadata: dict = {}                 # type-specific structured fields
