import json
import logging
from openai import OpenAI, RateLimitError, APIError
from app.models import RawInput, InputType, ProcessedEntry
from app.config import settings
from app.exceptions import GroqError

logger = logging.getLogger(__name__)

client = OpenAI(
    api_key=settings.groq_api_key,
    base_url="https://api.groq.com/openai/v1",
)

SYSTEM_PROMPT = """
You are a personal knowledge assistant. The user has shared content they want to save to their second brain.
Analyse the content and return ONLY a valid JSON object (no markdown, no explanation) with this structure:

{
  "title": "filing label (3-6 words) — like naming a folder, NOT a news headline",
  "content_type": "prefer from: Article / Reddit / Recipe / Contact / Book / Note / Product / Place / Video / Lead / Idea — but invent a new precise type name if none fit",
  "headline": "one sentence capturing WHY the user saved this — the key insight, action item, or takeaway. Must NOT restate the title. Answer: what's useful to know when scanning this entry later?",
  "tags": ["2-5 relevant lowercase tags"],
  "metadata": {}
}

Title examples (filing labels, not headlines):
  Bad:  "Product Designer Creates Claude Skill for UI Design"
  Good: "Claude UI Design Skill"

  Bad:  "Navigate to Jalan Desa Kiara via Route E23"
  Good: "Jalan Desa Kiara Route"

Headline examples (insight, not title restatement):
  Bad:  "A product designer created a Claude skill for UI design"  ← just restates the title
  Good: "Achieves 80% accurate UI on first output; useful for rapid prototyping"

  Bad:  "Navigate to Jalan Desa Kiara"  ← just restates the title
  Good: "4 min / 1.2 km route near Bukit Kiara, left turn in 670 m"

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
    try:
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
    except RateLimitError as e:
        logger.warning("Groq rate limit hit: %s", e)
        raise GroqError("rate limit", is_rate_limit=True) from e
    except APIError as e:
        logger.exception("Groq API error: %s", e)
        raise GroqError(str(e)) from e

    # For IMAGE entries, raw.content is a base64 blob — never write it to Notion page body
    page_raw_content = "" if raw.input_type == InputType.IMAGE else raw.content

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
            raw_content=page_raw_content,
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
            raw_content=page_raw_content,
            original_message=raw.original_message,
            metadata={},
        )
