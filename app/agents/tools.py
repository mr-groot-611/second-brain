"""Tool implementations for the enrichment agent.

Tools:
  - web_search: Brave Search API
  - update_entry: Update Notion entry properties
  - ask_user: Send a follow-up question via Telegram
"""

import json
import logging
from datetime import date

import httpx

from app.config import settings
from app.exceptions import BraveSearchError
from app.storage.notion import update_notion_properties, append_to_conversation_log
from app.session import session_store

logger = logging.getLogger(__name__)

# Daily search counter — resets on new day
_search_count = 0
_search_date = ""


def get_daily_search_count() -> int:
    global _search_count, _search_date
    today = date.today().isoformat()
    if _search_date != today:
        _search_count = 0
        _search_date = today
    return _search_count


async def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Search the web using Brave Search API.

    Returns list of {"title": str, "url": str, "snippet": str}.
    Returns empty list if no API key or on any error (graceful degradation).
    """
    global _search_count, _search_date

    if not settings.brave_api_key:
        logger.info("Brave Search skipped — no API key configured")
        return []

    today = date.today().isoformat()
    if _search_date != today:
        _search_count = 0
        _search_date = today

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": num_results},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": settings.brave_api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        _search_count += 1

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })
        return results

    except httpx.HTTPStatusError as e:
        logger.warning("Brave Search HTTP error %s: %s", e.response.status_code, e.response.text[:200])
        return []
    except Exception as e:
        logger.warning("Brave Search failed: %s", e)
        return []


async def update_entry(page_id: str, fields: dict) -> bool:
    """Update Notion entry properties.

    Fields can include: metadata (dict), tags (list), headline (str), ai_summary (str).
    Returns True on success.
    """
    try:
        update_notion_properties(page_id, fields)
        return True
    except Exception as e:
        logger.warning("update_entry failed: %s", e)
        return False


async def ask_user(bot, chat_id: int, page_id: str, question: str, user_id: int = None) -> None:
    """Send a follow-up question to the user via Telegram.

    Also appends the question to the conversation log and updates session.
    """
    try:
        await bot.send_message(chat_id=chat_id, text=question)
        append_to_conversation_log(page_id, "Second Brain", question)
        if user_id:
            session_store.update_interaction(user_id, bot_message=question)
    except Exception as e:
        logger.warning("ask_user failed: %s", e)
