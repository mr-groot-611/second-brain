import json
from google import genai
from google.genai import types
from app.models import RawInput, InputType, ProcessedEntry
from app.config import settings

SYSTEM_PROMPT = """
You are a personal knowledge assistant. The user has shared content they want to save to their second brain.
Analyse the content and return ONLY a valid JSON object (no markdown, no explanation) with this structure:

{
  "title": "descriptive title (max 10 words)",
  "content_type": "prefer from: Article / Reddit / Recipe / Contact / Book / Note / Product / Place / Video / Lead / Idea — but invent a new precise type name if none fit",
  "summary": "2-3 sentences capturing the core value of this content",
  "tags": ["2-5 relevant lowercase tags"],
  "entities": ["notable people, places, tools, book titles, company names mentioned"],
  "metadata": {}
}

TYPE-SPECIFIC METADATA RULES — populate the metadata object with ONLY the fields relevant to the detected content_type:

Contact → "contact_name", "company", "role", "where_met"
  Example: {"contact_name": "John Smith", "company": "Verdant", "role": "Founder", "where_met": "Startup Grind March 2026"}

Book → "author", "genre", "page_count" (integer or null if unknown), "recommended_by"
  Example: {"author": "James Clear", "genre": "Self-improvement", "page_count": 320, "recommended_by": "colleague"}

Recipe → "cuisine", "cook_time", "dietary" (array, e.g. ["vegan", "gluten-free"])
  Example: {"cuisine": "Thai", "cook_time": "30 minutes", "dietary": ["vegan-adaptable"]}

Product → "product_name", "category", "price_range"
  Example: {"product_name": "Uplift V2 Desk", "category": "Furniture", "price_range": "$500-800"}

Article / Reddit → "key_takeaway" (one sentence — the single most useful thing to remember)
  Example: {"key_takeaway": "Attach new habits to existing anchors rather than fixed times"}

Place → "place_name", "location", "category" (restaurant / cafe / venue / etc.)
  Example: {"place_name": "Barangaroo Reserve", "location": "Sydney, Australia", "category": "Park"}

Lead → "mentioned_by" (who referenced it), "use_case" (why it was mentioned)
  Example: {"mentioned_by": "Ravi from Accenture", "use_case": "AI-powered customer service operations"}

Idea → "problem", "solution", "hypothesis", "next_step"
  Example: {"problem": "Users drop off during onboarding", "solution": "Add social proof layer", "hypothesis": "Seeing others succeed reduces friction", "next_step": "Prototype one screen and test with 5 users"}

Dynamic / invented type → use the most relevant fields from above, or leave metadata as {}

Note / Video / other → metadata can be empty: {}

Be specific and accurate. Extract only what is clearly present in the content — do not invent information.
"""


def process_with_gemini(raw: RawInput) -> ProcessedEntry:
    client = genai.Client(api_key=settings.gemini_api_key)

    if raw.input_type == InputType.IMAGE:
        import base64
        prompt = f"{SYSTEM_PROMPT}\n\nAnalyse this image the user saved."
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_text(prompt),
                types.Part.from_bytes(data=base64.b64decode(raw.content), mime_type="image/jpeg"),
            ],
        )
    else:
        prompt = f"{SYSTEM_PROMPT}\n\nContent to analyse:\n\n{raw.content}"
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

    try:
        # Strip markdown code fences if Gemini adds them
        text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(text)
        return ProcessedEntry(
            title=data.get("title", "Saved Item"),
            content_type=data.get("content_type", "Note"),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            entities=data.get("entities", []),
            source_url=raw.source_url,
            raw_content=raw.content,
            metadata=data.get("metadata", {})
        )
    except (json.JSONDecodeError, KeyError):
        return ProcessedEntry(
            title="Saved Item",
            content_type="Note",
            summary="Could not process automatically.",
            tags=[],
            entities=[],
            source_url=raw.source_url,
            raw_content=raw.content,
            metadata={}
        )
