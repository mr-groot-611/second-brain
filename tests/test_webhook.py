from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.handlers.message import handle_message
from app.processors.intent import Intent


def make_update(text=None, photo=None, document=None, voice=None, user_id=123):
    update = MagicMock()
    # handler uses message.from_user.id
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
         patch("app.handlers.message.extract_url") as mock_extract, \
         patch("app.handlers.message.process_with_gemini") as mock_gemini, \
         patch("app.handlers.message.write_to_notion") as mock_notion, \
         patch("app.handlers.message.session_store") as mock_store:

        mock_store.get.return_value = None
        mock_detect.return_value = "url"
        # extract_url returns a string content (not a MagicMock object)
        mock_extract.return_value = "Article content here"
        mock_gemini.return_value = MagicMock(
            title="Test Article",
            content_type="Article",
            summary="A test article summary.",
            tags=["test", "example"],
            entities=["Author Name"],
            source_url="https://example.com/article",
            raw_content="Article content here",
            metadata={}
        )
        mock_notion.return_value = "page-abc"

        await handle_message(update, context)

        mock_notion.assert_called_once()
        mock_store.set.assert_called_once_with(
            123,
            {
                "page_id": "page-abc",
                "title": "Test Article",
                "type": "Article",
                "summary": "A test article summary."
            }
        )
        assert update.message.reply_text.call_count == 2  # "⏳ Saving..." + final reply
        final_reply = update.message.reply_text.call_args_list[-1][0][0]
        assert "Test Article" in final_reply
        assert "Article" in final_reply


@pytest.mark.asyncio
async def test_context_followup_updates_existing_page():
    update = make_update(text="Also, this was recommended by Sarah")
    context = make_context()

    last_entry = {
        "page_id": "page-abc",
        "title": "Test Article",
        "content_type": "Article",
        "summary": "A test article summary."
    }

    with patch("app.handlers.message.session_store") as mock_store, \
         patch("app.handlers.message.classify_intent") as mock_intent, \
         patch("app.handlers.message.update_notion_entry") as mock_update:

        mock_store.get.return_value = last_entry
        mock_intent.return_value = Intent.CONTEXT

        await handle_message(update, context)

        mock_update.assert_called_once_with(
            "page-abc",
            "Also, this was recommended by Sarah"
        )
        update.message.reply_text.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Test Article" in reply or "added" in reply.lower() or "Updated" in reply


@pytest.mark.asyncio
async def test_done_followup_clears_session():
    update = make_update(text="done")
    context = make_context()

    last_entry = {
        "page_id": "page-abc",
        "title": "Test Article",
        "content_type": "Article",
        "summary": "A test article summary."
    }

    with patch("app.handlers.message.session_store") as mock_store, \
         patch("app.handlers.message.classify_intent") as mock_intent:

        mock_store.get.return_value = last_entry
        mock_intent.return_value = Intent.DONE

        await handle_message(update, context)

        mock_store.clear.assert_called_once_with(123)
        update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_error_during_processing_sends_error_message():
    update = make_update(text="https://example.com/article")
    context = make_context()

    with patch("app.handlers.message.detect_input_type") as mock_detect, \
         patch("app.handlers.message.extract_url", side_effect=Exception("network error")), \
         patch("app.handlers.message.session_store") as mock_store:

        mock_store.get.return_value = None
        mock_detect.return_value = "url"

        # Handler catches exception and sends error reply — should NOT raise
        await handle_message(update, context)

        # At minimum the "⏳ Saving..." message + error message
        assert update.message.reply_text.call_count >= 1
        all_replies = " ".join(
            call[0][0] for call in update.message.reply_text.call_args_list
        )
        assert any(word in all_replies.lower() for word in ["sorry", "wrong", "error", "failed"])
