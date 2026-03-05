from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.handlers.message import handle_message
from app.processors.intent import Intent


def make_update(text=None, photo=None, document=None, voice=None, user_id=123):
    update = MagicMock()
    update.message.from_user.id = user_id
    update.message.text = text
    update.message.photo = photo
    update.message.document = document
    update.message.voice = voice
    update.message.reply_text = AsyncMock()
    return update


def make_context():
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.get_file = AsyncMock(return_value=MagicMock(
        download_as_bytearray=AsyncMock(return_value=bytearray(b"fake_data"))
    ))
    return context


@pytest.mark.asyncio
async def test_new_url_message_saves_and_replies():
    update = make_update(text="https://example.com/article")
    context = make_context()

    with patch("app.handlers.message.detect_input_type") as mock_detect, \
         patch("app.handlers.message.extract_url_from_message") as mock_extract_url, \
         patch("app.handlers.message.extract_url") as mock_extract, \
         patch("app.handlers.message.process_with_ai") as mock_ai, \
         patch("app.handlers.message.write_to_notion") as mock_notion, \
         patch("app.handlers.message.append_to_conversation_log"), \
         patch("app.handlers.message.session_store") as mock_store:

        from app.models import InputType
        mock_store.get.return_value = None
        mock_store.is_expired.return_value = True
        mock_detect.return_value = InputType.URL
        mock_extract_url.return_value = "https://example.com/article"
        mock_extract.return_value = "Article content here"
        mock_ai.return_value = MagicMock(
            title="Test Article",
            content_type="Article",
            headline="A test article summary.",
            tags=["test", "example"],
            source_url="https://example.com/article",
            raw_content="Article content here",
            original_message=None,
            metadata={},
            ai_summary="AI summary here.",
            file_bytes=None,
            file_mime_type=None,
        )
        mock_ai.return_value.input_type = InputType.URL
        mock_notion.return_value = "page-abc"

        await handle_message(update, context)

        mock_notion.assert_called_once()
        assert update.message.reply_text.call_count == 2  # "⏳ Saving..." + final reply
        final_reply = update.message.reply_text.call_args_list[-1][0][0]
        assert "Test Article" in final_reply
        assert "Article" in final_reply


@pytest.mark.asyncio
async def test_context_followup_uses_smart_update():
    """CONTEXT intent triggers smart re-processing, not just raw text append."""
    update = make_update(text="She's at Stripe, ML team")
    context = make_context()

    last_entry = {
        "page_id": "page-abc",
        "title": "Sarah Chen Contact",
        "type": "Contact",
        "headline": "Met at YC Demo Day.",
        "tags": ["contact"],
        "metadata": {"contact_name": "Sarah Chen"},
        "bot_last_message": "✅ Saved as Contact — Sarah Chen",
        "last_interaction_at": 1000000000,
    }

    with patch("app.handlers.message.session_store") as mock_store, \
         patch("app.handlers.message.classify_intent") as mock_intent, \
         patch("app.handlers.message.process_context_update") as mock_context_ai, \
         patch("app.handlers.message.update_notion_properties") as mock_update_props, \
         patch("app.handlers.message.append_to_conversation_log") as mock_log:

        mock_store.get.return_value = last_entry
        mock_store.is_expired.return_value = False
        mock_intent.return_value = Intent.CONTEXT
        mock_context_ai.return_value = {
            "metadata": {"contact_name": "Sarah Chen", "company": "Stripe", "role": "ML team"},
            "tags": ["contact", "stripe", "ml"],
        }

        await handle_message(update, context)

        # Smart update should be called
        mock_context_ai.assert_called_once_with(last_entry, "She's at Stripe, ML team")
        mock_update_props.assert_called_once_with("page-abc", mock_context_ai.return_value)

        # Conversation log should be updated
        assert mock_log.call_count == 2  # user message + bot reply

        # Reply should mention the update
        reply = update.message.reply_text.call_args[0][0]
        assert "Updated" in reply


@pytest.mark.asyncio
async def test_done_followup_clears_session():
    update = make_update(text="done")
    context = make_context()

    last_entry = {
        "page_id": "page-abc",
        "title": "Test Article",
        "type": "Article",
        "headline": "A test article summary.",
        "last_interaction_at": 1000000000,
    }

    with patch("app.handlers.message.session_store") as mock_store, \
         patch("app.handlers.message.classify_intent") as mock_intent, \
         patch("app.handlers.message.append_to_conversation_log"):

        mock_store.get.return_value = last_entry
        mock_store.is_expired.return_value = False
        mock_intent.return_value = Intent.DONE

        await handle_message(update, context)

        mock_store.clear.assert_called_once_with(123)
        update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_error_during_processing_sends_error_message():
    update = make_update(text="https://example.com/article")
    context = make_context()

    with patch("app.handlers.message.detect_input_type") as mock_detect, \
         patch("app.handlers.message.extract_url_from_message", side_effect=Exception("network error")), \
         patch("app.handlers.message.session_store") as mock_store:

        from app.models import InputType
        mock_store.get.return_value = None
        mock_store.is_expired.return_value = True
        mock_detect.return_value = InputType.URL

        await handle_message(update, context)

        assert update.message.reply_text.call_count >= 1
        all_replies = " ".join(
            call[0][0] for call in update.message.reply_text.call_args_list
        )
        assert any(word in all_replies.lower() for word in ["sorry", "wrong", "error", "failed", "unexpected"])


@pytest.mark.asyncio
async def test_expired_session_treated_as_new():
    """If session is expired, message goes through the save pipeline."""
    update = make_update(text="New thing to save")
    context = make_context()

    with patch("app.handlers.message.session_store") as mock_store, \
         patch("app.handlers.message.detect_input_type") as mock_detect, \
         patch("app.handlers.message.process_with_ai") as mock_ai, \
         patch("app.handlers.message.write_to_notion") as mock_notion, \
         patch("app.handlers.message.append_to_conversation_log"):

        from app.models import InputType
        # Session exists but is expired
        mock_store.get.return_value = {"page_id": "old", "title": "Old"}
        mock_store.is_expired.return_value = True  # expired!
        mock_detect.return_value = InputType.TEXT
        mock_ai.return_value = MagicMock(
            title="New Thing",
            content_type="Note",
            headline="A new item.",
            tags=["new"],
            source_url=None,
            raw_content="New thing to save",
            original_message="New thing to save",
            metadata={},
            ai_summary="",
            file_bytes=None,
            file_mime_type=None,
        )
        mock_notion.return_value = "page-new"

        await handle_message(update, context)

        # Should go through save pipeline, not intent classification
        mock_notion.assert_called_once()
