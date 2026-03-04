from openai import OpenAI
from app.config import settings


def transcribe_voice(audio_bytes: bytes) -> str:
    """Transcribe a Telegram voice note (OGG/Opus) using Groq Whisper."""
    client = OpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    response = client.audio.transcriptions.create(
        model="whisper-large-v3-turbo",
        file=("voice.ogg", audio_bytes, "audio/ogg"),
    )
    return response.text.strip()
