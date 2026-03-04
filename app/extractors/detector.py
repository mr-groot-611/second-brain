from app.models import InputType


def detect_input_type(message) -> InputType:
    if message.photo:
        return InputType.IMAGE
    if message.document and message.document.mime_type == "application/pdf":
        return InputType.PDF
    if getattr(message, "voice", None):
        return InputType.VOICE
    if message.text and extract_url_from_message(message):
        return InputType.URL
    return InputType.TEXT


def extract_url_from_message(message) -> str | None:
    """Extract the first URL from a Telegram message using entity parsing.
    Handles URLs anywhere in the message, not just at the start.
    Returns the URL string or None if no URL found.
    """
    if message.entities:
        for entity in message.entities:
            if entity.type == "text_link":
                # Hyperlinked text — URL is in entity.url
                return entity.url
            if entity.type == "url":
                # Plain URL in message text — extract via offset/length
                return message.text[entity.offset:entity.offset + entity.length]
    # Fallback: bare URL with no entities (edge case)
    if message.text:
        stripped = message.text.strip()
        if stripped.startswith(("http://", "https://")):
            return stripped.split()[0]
    return None
