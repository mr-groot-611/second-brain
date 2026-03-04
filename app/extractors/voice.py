from google import genai
from google.genai import types
from app.config import settings


def transcribe_voice(audio_bytes: bytes) -> str:
    """Transcribe a Telegram voice note (OGG/Opus) using Gemini Audio."""
    client = genai.Client(api_key=settings.gemini_api_key)

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            types.Part.from_text("Transcribe this voice note accurately. Return only the transcription, no commentary."),
            types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"),
        ],
    )
    return response.text.strip()
