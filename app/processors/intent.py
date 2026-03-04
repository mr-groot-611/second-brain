from enum import Enum
from openai import OpenAI
from app.config import settings


class Intent(str, Enum):
    CONTEXT = "CONTEXT"   # adds info to previous entry
    DONE    = "DONE"      # acknowledgement, user is finished
    NEW     = "NEW"       # unrelated new item to save


INTENT_PROMPT = """A user is chatting with a personal knowledge assistant.
They previously saved an entry:
  Title: {title}
  Headline: {headline}

They have now sent this new message: "{message}"

Classify their intent as exactly one of:
- CONTEXT: this message adds information to the previously saved entry
- DONE: this is an acknowledgement (e.g. "ok", "thanks", "nope", "all good", a thumbs up emoji) — they are finished with the previous entry
- NEW: this is a completely unrelated new item they want to save

Reply with only one word: CONTEXT, DONE, or NEW."""


def classify_intent(last_entry: dict, new_message: str) -> Intent:
    client = OpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    prompt = INTENT_PROMPT.format(
        title=last_entry.get("title", ""),
        headline=last_entry.get("headline", last_entry.get("summary", "")),
        message=new_message,
    )
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",  # lightweight model — simple classification task
        messages=[{"role": "user", "content": prompt}],
        max_tokens=5,
        temperature=0,
    )
    raw = response.choices[0].message.content.strip().upper()
    try:
        return Intent(raw)
    except ValueError:
        return Intent.NEW  # safe default
