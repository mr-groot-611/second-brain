from telegram import Update
from telegram.ext import ContextTypes

from app.extractors.detector import detect_input_type
from app.extractors.url import extract_url
from app.extractors.pdf import extract_pdf
from app.extractors.image import prepare_image
from app.extractors.voice import transcribe_voice
from app.models import InputType, RawInput
from app.processors.gemini import process_with_gemini
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
        entry = process_with_gemini(raw)
        page_id = write_to_notion(entry)

        # Step 4: Store in session for potential follow-up
        session_store.set(user_id, {
            "page_id": page_id,
            "title": entry.title,
            "type": entry.content_type,
            "summary": entry.summary
        })

        # Step 5: Conversational reply
        tags_str = " ".join(f"#{t}" for t in entry.tags) if entry.tags else ""
        reply = (
            f"✅ Saved as *{entry.content_type}* — _{entry.title}_\n"
            f"{entry.summary}\n"
            f"{tags_str}\n\n"
            f"Anything to add? Or just send your next item."
        )
        await message.reply_text(reply, parse_mode="Markdown")

    except Exception as exc:
        await message.reply_text(
            "Sorry, something went wrong saving that. Please try again."
        )


async def _extract_content(message, input_type: InputType, context) -> RawInput:
    if input_type == InputType.URL:
        url = message.text.strip()
        return RawInput(input_type=input_type, content=extract_url(url), source_url=url)

    elif input_type == InputType.TEXT:
        return RawInput(input_type=input_type, content=message.text)

    elif input_type == InputType.IMAGE:
        photo = message.photo[-1]  # highest resolution
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        return RawInput(input_type=input_type, content=prepare_image(bytes(image_bytes)))

    elif input_type == InputType.PDF:
        file = await context.bot.get_file(message.document.file_id)
        pdf_bytes = await file.download_as_bytearray()
        return RawInput(
            input_type=input_type,
            content=extract_pdf(bytes(pdf_bytes)),
            file_name=message.document.file_name
        )

    elif input_type == InputType.VOICE:
        file = await context.bot.get_file(message.voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        transcript = transcribe_voice(bytes(audio_bytes))
        return RawInput(input_type=InputType.TEXT, content=transcript)
