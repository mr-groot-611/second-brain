import asyncio
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
from app.processors.ai import process_with_ai, process_context_update
from app.processors.intent import classify_intent, Intent
from app.session import session_store
from app.storage.notion import (
    write_to_notion, update_notion_entry, upload_and_attach_file,
    append_to_conversation_log, update_notion_properties,
)
from app.agents.enrichment import enrich_entry
from app.exceptions import GroqError, NotionError, TelegramFileError


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = message.from_user.id

    try:
        # Step 0: Check session expiry first
        last_entry = session_store.get(user_id)

        if last_entry and session_store.is_expired(user_id):
            # Session expired — treat as new message
            last_entry = None

        # Step 0b: If session active and text-only, classify intent
        if last_entry and message.text and not message.photo and not getattr(message, "voice", None):
            intent = classify_intent(last_entry, message.text)

            if intent == Intent.CONTEXT:
                await _handle_context(message, user_id, last_entry)
                return

            elif intent == Intent.DONE:
                # Log to conversation and clear session
                try:
                    append_to_conversation_log(last_entry["page_id"], "Varun", message.text)
                    append_to_conversation_log(last_entry["page_id"], "Second Brain", "All saved 👍")
                except Exception:
                    logger.exception("Failed to append conversation log on DONE")
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
        elif not raw.content and input_type == InputType.PDF:
            await message.reply_text(
                "⚠️ Couldn't extract text from this PDF — it may be password-protected or use a non-text format (e.g. scanned image). "
                "I'll save it with whatever metadata I can infer. You can add context by replying."
            )

        entry = process_with_ai(raw)
        page_id = write_to_notion(entry)

        # Fire background file upload (non-blocking) for IMAGE and PDF
        if raw.file_bytes and raw.file_mime_type:
            file_name = raw.file_name or (
                "image.jpg" if raw.input_type == InputType.IMAGE else "document.pdf"
            )
            asyncio.create_task(
                _upload_file_background(page_id, raw.file_bytes, file_name, raw.file_mime_type, message)
            )

        # Fire background enrichment agent (non-blocking)
        enrichment_data = {
            "type": entry.content_type,
            "title": entry.title,
            "headline": entry.headline,
            "tags": entry.tags,
            "metadata": entry.metadata,
            "ai_summary": entry.ai_summary,
            "source_url": entry.source_url,
            "raw_content": (entry.raw_content or "")[:4000],  # truncate for context window
        }
        asyncio.create_task(
            enrich_entry(enrichment_data, page_id, context.bot, message.chat_id, user_id)
        )

        # Conversational reply
        tags_str = " ".join(f"#{t}" for t in entry.tags) if entry.tags else ""
        reply = (
            f"✅ Saved as *{entry.content_type}* — _{entry.title}_\n"
            f"{entry.headline}\n"
            f"{tags_str}\n\n"
            f"Anything to add? Or just send your next item."
        )
        await message.reply_text(reply, parse_mode="Markdown")

        # Store in session for potential follow-up (with rich data)
        session_store.set(user_id, {
            "page_id": page_id,
            "title": entry.title,
            "type": entry.content_type,
            "headline": entry.headline,
            "tags": entry.tags,
            "metadata": entry.metadata,
            "bot_last_message": reply,
        })

        # Append bot's save confirmation to conversation log (non-blocking)
        try:
            append_to_conversation_log(
                page_id, "Second Brain",
                f"✅ Saved as {entry.content_type} — {entry.title}"
            )
        except Exception:
            logger.exception("Failed to append save confirmation to conversation log")

    except GroqError as exc:
        session_store.clear(user_id)
        if exc.is_rate_limit:
            await message.reply_text(
                "⚠️ Hit Groq's rate limit — wait a minute and try again.\n"
                "_(Free tier: 30 requests/min, 1K requests/day)_",
                parse_mode="Markdown"
            )
        else:
            logger.exception("Groq API error: %s", exc)
            await message.reply_text(
                "⚠️ The AI service (Groq) had an error — this is usually temporary. "
                "Try again in a moment."
            )

    except NotionError as exc:
        session_store.clear(user_id)
        logger.exception("Notion error: %s", exc)
        await message.reply_text(
            "⚠️ Saved by AI but couldn't write to Notion — "
            "check the integration token in your Render env vars."
        )

    except TelegramFileError as exc:
        session_store.clear(user_id)
        logger.exception("Telegram file download error: %s", exc)
        await message.reply_text(
            "⚠️ Couldn't download your file from Telegram — try resending it."
        )

    except Exception as exc:
        session_store.clear(user_id)
        logger.exception("Unexpected error: %s", exc)
        await message.reply_text(
            "⚠️ Something unexpected went wrong — try again. "
            "If it keeps happening, check the Render logs."
        )


async def _handle_context(message, user_id: int, last_entry: dict):
    """Handle a CONTEXT intent — re-process and update entry properties."""
    page_id = last_entry["page_id"]

    try:
        # Smart re-processing: AI merges new info into existing properties
        updates = process_context_update(last_entry, message.text)

        # Update Notion properties if AI returned any changes
        if updates:
            update_notion_properties(page_id, updates)

            # Update session with new property values
            if "tags" in updates:
                last_entry["tags"] = updates["tags"]
            if "metadata" in updates:
                last_entry["metadata"] = updates["metadata"]
            if "headline" in updates:
                last_entry["headline"] = updates["headline"]
            if "title" in updates:
                last_entry["title"] = updates["title"]

        # Append to conversation log
        append_to_conversation_log(page_id, "Varun", message.text)

        # Build descriptive reply
        if updates:
            changed = ", ".join(updates.keys())
            reply_text = f"Updated ✏️ — _{last_entry['title']}_ ({changed})\nAnything else to add?"
        else:
            reply_text = f"Updated ✏️ — added context to _{last_entry['title']}_.\nAnything else to add?"

        append_to_conversation_log(page_id, "Second Brain", reply_text.split("\n")[0])

        await message.reply_text(reply_text, parse_mode="Markdown")

        # Refresh session timestamp
        session_store.update_interaction(user_id, bot_message=reply_text)

    except GroqError:
        # If AI re-processing fails, fall back to legacy append
        logger.warning("Context update AI failed, falling back to legacy append")
        update_notion_entry(page_id, message.text)
        append_to_conversation_log(page_id, "Varun", message.text)
        reply_text = f"Updated ✏️ — added context to _{last_entry['title']}_.\nAnything else to add?"
        append_to_conversation_log(page_id, "Second Brain", reply_text.split("\n")[0])
        await message.reply_text(reply_text, parse_mode="Markdown")
        session_store.update_interaction(user_id, bot_message=reply_text)


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
        try:
            photo = message.photo[-1]  # highest resolution
            file = await context.bot.get_file(photo.file_id)
            image_bytes = await file.download_as_bytearray()
        except Exception as e:
            raise TelegramFileError("image download failed") from e
        caption = getattr(message, "caption", None)
        image_bytes_final = bytes(image_bytes)
        return RawInput(
            input_type=input_type,
            content=prepare_image(image_bytes_final),
            original_message=caption,
            file_bytes=image_bytes_final,
            file_mime_type="image/jpeg",
        )

    elif input_type == InputType.PDF:
        try:
            file = await context.bot.get_file(message.document.file_id)
            pdf_bytes = await file.download_as_bytearray()
        except Exception as e:
            raise TelegramFileError("PDF download failed") from e
        caption = getattr(message, "caption", None)
        pdf_bytes_final = bytes(pdf_bytes)
        return RawInput(
            input_type=input_type,
            content=extract_pdf(pdf_bytes_final),
            file_name=message.document.file_name,
            original_message=caption,
            file_bytes=pdf_bytes_final,
            file_mime_type="application/pdf",
        )

    elif input_type == InputType.VOICE:
        try:
            file = await context.bot.get_file(message.voice.file_id)
            audio_bytes = await file.download_as_bytearray()
        except Exception as e:
            raise TelegramFileError("voice download failed") from e
        transcript = transcribe_voice(bytes(audio_bytes))
        return RawInput(
            input_type=InputType.TEXT,
            content=transcript,
            original_message=transcript,  # transcription is the original message for voice
        )


async def _upload_file_background(
    page_id: str,
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
    message,
) -> None:
    """Background coroutine: upload file to Notion and notify user."""
    try:
        await upload_and_attach_file(page_id, file_bytes, file_name, mime_type)
        await message.reply_text("📎 File attached to your entry.")
    except Exception as exc:
        logger.exception("Background file upload failed: %s", exc)
        await message.reply_text("⚠️ Entry saved but couldn't attach the file.")
