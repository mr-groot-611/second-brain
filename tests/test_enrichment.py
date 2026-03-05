"""Tests for the enrichment agent and tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.agents.tools import web_search, update_entry, ask_user, get_daily_search_count
from app.agents.enrichment import enrich_entry


# --- web_search tests ---

@pytest.mark.asyncio
async def test_web_search_returns_results():
    """Verify web_search parses Brave's response format."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "web": {
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "description": "Snippet 1"},
                {"title": "Result 2", "url": "https://example.com/2", "description": "Snippet 2"},
            ]
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch("app.agents.tools.settings") as mock_settings, \
         patch("app.agents.tools.httpx.AsyncClient") as MockClient:
        mock_settings.brave_api_key = "test-key"
        mock_client = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.return_value = mock_response

        results = await web_search("test query")

    assert len(results) == 2
    assert results[0]["title"] == "Result 1"
    assert results[0]["url"] == "https://example.com/1"
    assert results[0]["snippet"] == "Snippet 1"


@pytest.mark.asyncio
async def test_web_search_returns_empty_without_api_key():
    """Graceful skip when no API key is configured."""
    with patch("app.agents.tools.settings") as mock_settings:
        mock_settings.brave_api_key = ""
        results = await web_search("test query")
    assert results == []


@pytest.mark.asyncio
async def test_web_search_returns_empty_on_error():
    """Returns empty list on network error."""
    with patch("app.agents.tools.settings") as mock_settings, \
         patch("app.agents.tools.httpx.AsyncClient") as MockClient:
        mock_settings.brave_api_key = "test-key"
        mock_client = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.side_effect = Exception("network error")

        results = await web_search("test query")
    assert results == []


# --- update_entry tests ---

@pytest.mark.asyncio
async def test_update_entry_calls_notion():
    with patch("app.agents.tools.update_notion_properties") as mock_update:
        result = await update_entry("page-123", {"tags": ["contact", "stripe"]})
    assert result is True
    mock_update.assert_called_once_with("page-123", {"tags": ["contact", "stripe"]})


@pytest.mark.asyncio
async def test_update_entry_returns_false_on_error():
    with patch("app.agents.tools.update_notion_properties", side_effect=Exception("fail")):
        result = await update_entry("page-123", {"tags": []})
    assert result is False


# --- ask_user tests ---

@pytest.mark.asyncio
async def test_ask_user_sends_message():
    mock_bot = AsyncMock()
    with patch("app.agents.tools.append_to_conversation_log") as mock_log, \
         patch("app.agents.tools.session_store") as mock_session:
        await ask_user(mock_bot, 123, "page-abc", "What company is she at?", user_id=456)

    mock_bot.send_message.assert_called_once_with(chat_id=123, text="What company is she at?")
    mock_log.assert_called_once()


# --- enrichment agent tests ---

def _make_entry_data(**kwargs):
    defaults = {
        "type": "Contact",
        "title": "Sarah Chen",
        "headline": "Met at YC Demo Day.",
        "tags": ["contact"],
        "metadata": {"contact_name": "Sarah Chen"},
        "ai_summary": "Contact info for Sarah Chen.",
        "source_url": None,
        "raw_content": "Sarah Chen business card photo",
    }
    defaults.update(kwargs)
    return defaults


def _mock_tool_response(tool_calls=None, content=None):
    """Build a mock Groq response with optional tool calls."""
    choice = MagicMock()
    if tool_calls:
        choice.message.tool_calls = tool_calls
        choice.finish_reason = "tool_calls"
    else:
        choice.message.tool_calls = None
        choice.finish_reason = "stop"
    choice.message.content = content or ""
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_tool_call(name: str, args: dict, call_id: str = "call_1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


@pytest.mark.asyncio
async def test_enrichment_no_tool_calls():
    """Agent decides entry is complete — no tools called, no notification."""
    entry_data = _make_entry_data(type="Article", title="Complete Article")
    mock_bot = AsyncMock()

    with patch("app.agents.enrichment.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_tool_response()

        await enrich_entry(entry_data, "page-123", mock_bot, 456, 789)

    # No notification sent
    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_enrichment_search_then_update():
    """Agent searches, then updates the entry."""
    entry_data = _make_entry_data()
    mock_bot = AsyncMock()

    search_tool_call = _make_tool_call("web_search", {"query": "Sarah Chen Stripe"}, "call_1")
    update_tool_call = _make_tool_call("update_entry", {"fields": {"metadata": {"company": "Stripe"}}}, "call_2")

    # Round 1: search
    response1 = _mock_tool_response(tool_calls=[search_tool_call])
    # Round 2: update
    response2 = _mock_tool_response(tool_calls=[update_tool_call])
    # Round 3: done
    response3 = _mock_tool_response()

    with patch("app.agents.enrichment.OpenAI") as MockOpenAI, \
         patch("app.agents.enrichment.web_search", new_callable=AsyncMock) as mock_search, \
         patch("app.agents.enrichment.update_entry", new_callable=AsyncMock) as mock_update, \
         patch("app.agents.enrichment.append_to_conversation_log"):

        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [response1, response2, response3]
        mock_search.return_value = [{"title": "Sarah Chen - Stripe", "url": "...", "snippet": "ML engineer"}]
        mock_update.return_value = True

        await enrich_entry(entry_data, "page-123", mock_bot, 456, 789)

    mock_search.assert_called_once_with("Sarah Chen Stripe")
    mock_update.assert_called_once_with("page-123", {"metadata": {"company": "Stripe"}})
    # Notification sent
    mock_bot.send_message.assert_called()


@pytest.mark.asyncio
async def test_enrichment_ask_user():
    """Agent asks a follow-up question."""
    entry_data = _make_entry_data(type="Idea", title="App Concept")
    mock_bot = AsyncMock()

    ask_tool_call = _make_tool_call("ask_user", {"question": "What's the next step for this idea?"}, "call_1")
    response1 = _mock_tool_response(tool_calls=[ask_tool_call])
    response2 = _mock_tool_response()

    with patch("app.agents.enrichment.OpenAI") as MockOpenAI, \
         patch("app.agents.enrichment.ask_user", new_callable=AsyncMock) as mock_ask, \
         patch("app.agents.enrichment.append_to_conversation_log"):

        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [response1, response2]

        await enrich_entry(entry_data, "page-123", mock_bot, 456, 789)

    mock_ask.assert_called_once()


@pytest.mark.asyncio
async def test_enrichment_max_rounds_cap():
    """Agent stops after MAX_TOOL_ROUNDS even if it keeps requesting tools."""
    entry_data = _make_entry_data()
    mock_bot = AsyncMock()

    # Create a response that always has a tool call
    search_call = _make_tool_call("web_search", {"query": "test"})

    with patch("app.agents.enrichment.OpenAI") as MockOpenAI, \
         patch("app.agents.enrichment.web_search", new_callable=AsyncMock) as mock_search:

        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        # Always return a search tool call
        mock_client.chat.completions.create.return_value = _mock_tool_response(tool_calls=[search_call])
        mock_search.return_value = []

        await enrich_entry(entry_data, "page-123", mock_bot, 456, 789)

    # Should have been called exactly MAX_TOOL_ROUNDS=3 times
    assert mock_client.chat.completions.create.call_count == 3


@pytest.mark.asyncio
async def test_enrichment_groq_error_doesnt_crash():
    """Groq errors during enrichment don't crash — the entry is already saved."""
    entry_data = _make_entry_data()
    mock_bot = AsyncMock()

    with patch("app.agents.enrichment.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API error")

        # Should not raise
        await enrich_entry(entry_data, "page-123", mock_bot, 456, 789)

    mock_bot.send_message.assert_not_called()
