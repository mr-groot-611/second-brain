import json
from openai import OpenAI
from app.models import RawInput, InputType, ProcessedEntry
from app.config import settings

client = OpenAI(
    api_key=settings.groq_api_key,
    base_url="https://api.groq.com/openai/v1",
)

SYSTEM_PROMPT = """
You are a personal knowledge assistant. The user has shared content they want to save to their second brain.
Analyse the content and return ONLY a valid JSON object (no markdown, no explanation) with this structure:

{
  "title": "descriptive title (max 10 words)",
  "content_type": "prefer from: Article / Reddit / Recipe / Contact / Book / Note / Product / Place / Video / Lead / Idea — but invent a new precise type name if none fit",
  "headline": "one sentence capturing the single most useful thing to remember — optimised for future scanning and reference",
  "tags": ["2-5 relevant lowercase tags"],
  "metadata": {}
}

The metadata field should be a JSON object with fields relevant to the content_type. Be dynamic — choose the most useful fields for the specific content. Do not use a fixed schema.

Examples:
Contact     → {"contact_name": "...", "company": "...", "role": "...", "where_met": "..."}
Book        → {"author": "...", "genre": "...", "page_count": 320, "recommended_by": "..."}
Recipe      → {"cuisine": "...", "cook_time": "...", "dietary": ["vegan"]}
Product     → {"product_name": "...", "category": "...", "price_range": "..."}
Article     → {"key_takeaway": "one sentence — the single most useful thing to remember"}
Reddit      → {"key_takeaway": "...", "subreddit": "..."}
Place       → {"place_name": "...", "location": "...", "category": "restaurant/cafe/venue/etc."}
Lead        → {"mentioned_by": "...", "use_case": "..."}
Idea        → {"problem": "...", "hypothesis": "...", "next_step": "..."}
Event       → {"event_name": "...", "date": "...", "speaker": "...", "topic": "..."}
Dynamic     → choose the most relevant fields, or leave metadata as {}

Be specific and accurate. Extract only what is clearly present — do not invent information.
"""


def process_with_ai(raw: RawInput) -> ProcessedEntry:
    if raw.input_type == InputType.IMAGE:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"{SYSTEM_PROMPT}\n\nAnalyse this image the user saved."
                        + (f"\n\nUser's caption: {raw.original_message}" if raw.original_message else ""),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{raw.content}"},
                    },
                ],
            }
        ]
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=messages,
            max_tokens=1024,
        )
    else:
        user_content = f"Content to analyse:\n\n{raw.content}"
        if raw.original_message and raw.original_message != raw.content:
            user_content += f"\n\nUser's original message: {raw.original_message}"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=1024,
        )

    try:
        text = response.choices[0].message.content.strip()
        # Strip markdown code fences if model adds them
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(text)
        return ProcessedEntry(
            title=data.get("title", "Saved Item"),
            content_type=data.get("content_type", "Note"),
            headline=data.get("headline", ""),
            tags=data.get("tags", []),
            source_url=raw.source_url,
            raw_content=raw.content,
            original_message=raw.original_message,
            metadata=data.get("metadata", {}),
        )
    except (json.JSONDecodeError, KeyError):
        return ProcessedEntry(
            title="Saved Item",
            content_type="Note",
            headline="Could not process automatically.",
            tags=[],
            source_url=raw.source_url,
            raw_content=raw.content,
            original_message=raw.original_message,
            metadata={},
        )
