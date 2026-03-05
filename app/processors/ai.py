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
  "metadata": {},
  "ai_summary": "2-4 paragraph interpretive analysis (see guidelines below)"
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

AI Summary guidelines — adapt the summary style to the content type:
  Article / URL  → Key takeaways, why it matters, what to remember when scanning later
  Image          → Detailed description of what's visible in the image, context, and relevance
  PDF            → What the document covers, key sections, why it was saved
  Voice note     → Cleaned-up, structured version of what the user said — remove filler, organize the thought
  Bare idea/text → Structured framing: problem statement, hypothesis, what's actionable
  Contact        → Who this person is, context on why they're relevant, any notable details
  Recipe         → Brief overview of the dish, key techniques, what makes it interesting
  Book/media     → What it's about, key themes, why it might be worth reading/watching
Keep the summary between 100-500 words. Be specific and useful, not generic.

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
                max_tokens=2048,
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
                max_tokens=2048,
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
            ai_summary=data.get("ai_summary", ""),
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
            ai_summary="",
        )


CONTEXT_UPDATE_PROMPT = """The user previously saved this entry to their personal knowledge base:
  Title: {title}
  Type: {type}
  Headline: {headline}
  Tags: {tags}
  Metadata: {metadata}

They've now added this additional context: "{new_message}"

Return ONLY a valid JSON object with any fields that should be updated based on the new information.
Only include fields that need changing. Available fields: "headline", "tags", "metadata".
Keep the title unless the new info fundamentally changes what the entry is about — in that case include "title".

For metadata: merge the new info into the existing metadata object. Return the FULL updated metadata, not just the additions.
For tags: return the FULL updated tag list (add new tags as needed, keep relevant existing ones).
For headline: update ONLY if the new information meaningfully changes the key insight.

Example:
  Existing: Title="Sarah Chen Contact", Metadata={{"contact_name": "Sarah Chen"}}
  New context: "She's at Stripe, ML team"
  Output: {{"metadata": {{"contact_name": "Sarah Chen", "company": "Stripe", "role": "ML team"}}, "tags": ["contact", "stripe", "ml"]}}
"""


def process_context_update(existing_entry: dict, new_message: str) -> dict:
    """Re-process a CONTEXT message to produce updated entry properties.

    Args:
        existing_entry: dict with title, type, headline, tags, metadata
        new_message: the user's follow-up message

    Returns:
        dict of updated fields (only fields that changed)
    """
    tags = existing_entry.get("tags", [])
    tags_str = ", ".join(tags) if tags else "none"
    metadata = existing_entry.get("metadata", {})
    metadata_str = json.dumps(metadata, ensure_ascii=False) if metadata else "{}"

    prompt = CONTEXT_UPDATE_PROMPT.format(
        title=existing_entry.get("title", ""),
        type=existing_entry.get("type", ""),
        headline=existing_entry.get("headline", ""),
        tags=tags_str,
        metadata=metadata_str,
        new_message=new_message,
    )

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0,
        )
    except RateLimitError as e:
        logger.warning("Groq rate limit hit during context update: %s", e)
        raise GroqError("rate limit", is_rate_limit=True) from e
    except APIError as e:
        logger.exception("Groq API error during context update: %s", e)
        raise GroqError(str(e)) from e

    try:
        text = response.choices[0].message.content.strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except (json.JSONDecodeError, KeyError):
        logger.warning("Failed to parse context update response: %s", text[:200])
        return {}
