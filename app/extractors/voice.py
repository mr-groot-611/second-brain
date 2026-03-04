import google.generativeai as genai
from app.config import settings


def transcribe_voice(audio_bytes: bytes) -> str:
    """Transcribe a Telegram voice note (OGG/Opus) using Gemini Audio."""
    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    audio_part = {
        "mime_type": "audio/ogg",
        "data": audio_bytes
    }
    response = model.generate_content([
        "Transcribe this voice note accurately. Return only the transcription, no commentary.",
        audio_part
    ])
    return response.text.strip()
