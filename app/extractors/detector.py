from app.models import InputType


def detect_input_type(message) -> InputType:
    if message.photo:
        return InputType.IMAGE
    if message.document and message.document.mime_type == "application/pdf":
        return InputType.PDF
    if getattr(message, "voice", None):
        return InputType.VOICE
    if message.text and message.text.startswith(("http://", "https://")):
        return InputType.URL
    return InputType.TEXT
