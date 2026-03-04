import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

from app.extractors.detector import detect_input_type, extract_url_from_message
from app.extractors.url import extract_url
from app.extractors.pdf import extract_pdf
from app.extractors.image import prepare_image
from app.extractors.voice import transcribe_voice
from app.models import InputType, RawInput
from app.processors.ai import process_with_ai
from app.processors.intent import classify_intent, Intent
from app.session import session_store
from app.storage.notion import write_to_notion, update_notion_entry


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = message.from_user.id

    try:
        # Step 0: Check if this is a follow-up to a previous save
        last_entry = session_store.get(user_id)
        if last_entry and message.text and not message.photo and not getattr(message, "voice", None):
            intent = classify_intent(last_entry, message.text)

            if intent == Intent.CONTEXT:
                update_notion_entry(last_entry["page_id"], message.text)
                await message.reply_text(
                    f"Updated ✏️ — added context to _{last_entry['title']}_.\nAnything else to add?",
                    parse_mode="Markdown"
                )
                return

            elif intent == Intent.DONE:
                session_store.clear(user_id)
                await message.reply_text("All saved 👍")
                return
            # Intent.NEW falls through to the full pipeline below

        # Step 1–4: Full save pipeline
        await message.reply_text("⏳ Saving to your second brain...")

        input_type = detect_input_type(message)
        raw = await _extract_content(message, input_type, context)

        # Warn user if content extraction returned nothing
        if not raw.content and input_type == InputType.URL:
            await message.reply_text(
                "⚠️ Saved the link but couldn't fetch the content — the site may be unavailable or access-restricted. "
                "You can add context by replying to this message."
            )

        entry = process_with_ai(raw)
        page_id = write_to_notion(entry)

        # Store in session for potential follow-up
        session_store.set(user_id, {
            "page_id": page_id,
            "title": entry.title,
            "type": entry.content_type,
            "headline": entry.headline,
        })

        # Conversational reply
        tags_str = " ".join(f"#{t}" for t in entry.tags) if entry.tags else ""
        reply = (
            f"✅ Saved as *{entry.content_type}* — _{entry.title}_\n"
            f"{entry.headline}\n"
            f"{tags_str}\n\n"
            f"Anything to add? Or just send your next item."
        )
        await message.reply_text(reply, parse_mode="Markdown")

    except Exception as exc:
        logger.exception("Error processing message: %s", exc)
        await message.reply_text(
            "Sorry, something went wrong saving that. Please try again."
        )


async def _extract_content(message, input_type: InputType, context) -> RawInput:
    if input_type == InputType.URL:
        url = extract_url_from_message(message)
        content = extract_url(url)
        # Preserve the full original message as annotation (may include text beyond the URL)
        original = message.text if message.text and message.text.strip() != url else None
        return RawInput(
            input_type=input_type,
            content=content,
            source_url=url,
            original_message=original,
        )

    elif input_type == InputType.TEXT:
        # Extract URL from message if present (text+URL case)
        url = extract_url_from_message(message)
        if url:
            # Fetch the URL content AND preserve the user's annotation
            content = extract_url(url)
            return RawInput(
                input_type=InputType.URL,
                content=content,
                source_url=url,
                original_message=message.text,
            )
        return RawInput(
            input_type=input_type,
            content=message.text,
            original_message=message.text,
        )

    elif input_type == InputType.IMAGE:
        photo = message.photo[-1]  # highest resolution
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        caption = getattr(message, "caption", None)
        return RawInput(
            input_type=input_type,
            content=prepare_image(bytes(image_bytes)),
            original_message=caption,
        )

    elif input_type == InputType.PDF:
        file = await context.bot.get_file(message.document.file_id)
        pdf_bytes = await file.download_as_bytearray()
        caption = getattr(message, "caption", None)
        return RawInput(
            input_type=input_type,
            content=extract_pdf(bytes(pdf_bytes)),
            file_name=message.document.file_name,
            original_message=caption,
        )

    elif input_type == InputType.VOICE:
        file = await context.bot.get_file(message.voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        transcript = transcribe_voice(bytes(audio_bytes))
        return RawInput(
            input_type=InputType.TEXT,
            content=transcript,
            original_message=transcript,  # transcription is the original message for voice
        )
