import logging
import time
from enum import Enum
from openai import OpenAI, RateLimitError, APIError
from app.config import settings
from app.exceptions import GroqError

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    CONTEXT = "CONTEXT"   # adds info to previous entry
    DONE    = "DONE"      # acknowledgement, user is finished
    NEW     = "NEW"       # unrelated new item to save


INTENT_PROMPT = """A user is chatting with a personal knowledge assistant.

Previously saved entry:
  Title: {title} | Type: {type} | Tags: {tags}
  Headline: {headline}

Bot's last message to user: "{bot_last_message}"
Time since last interaction: {elapsed}

User's new message: "{message}"

Classify their intent as exactly one of:
- CONTEXT: this message adds information or answers the bot's question about the previously saved entry
- DONE: this is an acknowledgement (e.g. "ok", "thanks", "nope", "all good", a thumbs up emoji) — they are finished with the previous entry
- NEW: this is a completely unrelated new item they want to save

Reply with only one word: CONTEXT, DONE, or NEW."""


def _format_elapsed(last_interaction_at: float) -> str:
    """Convert a timestamp to a human-readable elapsed time string."""
    if not last_interaction_at:
        return "unknown"
    elapsed = time.time() - last_interaction_at
    if elapsed < 60:
        return f"{int(elapsed)} seconds ago"
    elif elapsed < 3600:
        return f"{int(elapsed / 60)} minutes ago"
    else:
        return f"{int(elapsed / 3600)} hours ago"


def classify_intent(session: dict, new_message: str) -> Intent:
    """Classify user intent using the full session context.

    Args:
        session: The session dict containing page_id, title, type, headline,
                 tags, bot_last_message, last_interaction_at, etc.
        new_message: The user's new message text.
    """
    client = OpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    tags = session.get("tags", [])
    tags_str = ", ".join(tags) if tags else "none"

    prompt = INTENT_PROMPT.format(
        title=session.get("title", ""),
        type=session.get("type", ""),
        tags=tags_str,
        headline=session.get("headline", ""),
        bot_last_message=session.get("bot_last_message", ""),
        elapsed=_format_elapsed(session.get("last_interaction_at", 0)),
        message=new_message,
    )
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",  # lightweight model — simple classification task
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0,
        )
    except RateLimitError as e:
        logger.warning("Groq rate limit hit during intent classification: %s", e)
        raise GroqError("rate limit", is_rate_limit=True) from e
    except APIError as e:
        logger.exception("Groq API error during intent classification: %s", e)
        raise GroqError(str(e)) from e

    raw = response.choices[0].message.content.strip().upper()
    try:
        return Intent(raw)
    except ValueError:
        return Intent.NEW  # safe default
