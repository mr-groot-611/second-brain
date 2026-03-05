"""Enrichment agent — runs in the background after every save.

Uses Groq tool calling to decide what to do with a saved entry:
  - web_search: look up missing information
  - update_entry: update Notion properties
  - ask_user: send a follow-up question via Telegram

The agent is selective — not every entry needs enrichment.
"""

import json
import logging
from openai import OpenAI, RateLimitError, APIError

from app.config import settings
from app.agents.tools import web_search, update_entry, ask_user, get_daily_search_count
from app.storage.notion import append_to_conversation_log

logger = logging.getLogger(__name__)

ENRICHMENT_SYSTEM_PROMPT = """You are an enrichment agent for a personal knowledge base. You just received a saved entry. Examine it and decide: is there missing context you could find via web search? Are there metadata fields that should be filled in? Is there one specific question worth asking the user?

Be selective. Not every entry needs enrichment. A fully-formed article with good tags needs nothing. A contact with no company info needs a search. A bare idea might benefit from one follow-up question.

Guidelines:
- For contacts: search for the person + company to fill in metadata gaps
- For articles: entry is usually complete from the scrape — skip unless tags are thin
- For books/movies/podcasts: search for synopsis, author info, ratings
- For bare ideas: consider asking ONE specific follow-up ("What's the next step?")
- For voice notes: re-analyze for entities or action items
- For recipes: fetch nutritional info or prep time if missing

Rules:
- Use web_search ONLY when external information would genuinely fill gaps
- Use update_entry to write improved metadata, tags, or headline back to the entry
- Use ask_user ONLY when something important is missing that search can't resolve
- Ask at most ONE question, and make it specific ("What company is Sarah at?" not "Want to add more details?")
- If the entry is already complete, do nothing — return without using any tools

{budget_note}"""

# Tool schemas for Groq tool calling
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information to fill gaps in the entry. Use when external context would improve the entry (e.g., look up a person's company, a book's synopsis, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_entry",
            "description": "Update the Notion entry with improved metadata, tags, or headline based on new information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "object",
                        "description": "Fields to update. Can include: metadata (object), tags (array of strings), headline (string).",
                    }
                },
                "required": ["fields"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Send a specific follow-up question to the user via Telegram. Use only when something important is missing that search can't resolve.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "A specific, actionable question for the user"
                    }
                },
                "required": ["question"]
            }
        }
    },
]

MAX_TOOL_ROUNDS = 3


async def enrich_entry(
    entry_data: dict,
    page_id: str,
    bot,
    chat_id: int,
    user_id: int,
) -> None:
    """Run the enrichment agent on a saved entry.

    This runs in the background via asyncio.create_task(). It never raises —
    all errors are caught and logged.

    Args:
        entry_data: dict with type, title, headline, tags, metadata, ai_summary,
                    source_url, raw_content (truncated)
        page_id: Notion page ID to update
        bot: Telegram bot instance for sending messages
        chat_id: Telegram chat ID
        user_id: Telegram user ID for session updates
    """
    try:
        client = OpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

        # Budget note
        budget_note = ""
        if get_daily_search_count() > 50:
            budget_note = "NOTE: Search budget is low today — only search if high value."

        system_prompt = ENRICHMENT_SYSTEM_PROMPT.format(budget_note=budget_note)

        # Build the user message with entry details
        user_message = f"""Entry to evaluate for enrichment:

Type: {entry_data.get('type', 'Unknown')}
Title: {entry_data.get('title', '')}
Headline: {entry_data.get('headline', '')}
Tags: {', '.join(entry_data.get('tags', []))}
Source URL: {entry_data.get('source_url', 'none')}
Metadata: {json.dumps(entry_data.get('metadata', {}), ensure_ascii=False)}
AI Summary: {entry_data.get('ai_summary', '')[:1000]}

Raw content (truncated):
{entry_data.get('raw_content', '')[:3000]}

Decide what enrichment (if any) this entry needs."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        enriched_something = False
        enrichment_descriptions = []

        for round_num in range(MAX_TOOL_ROUNDS):
            try:
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    max_tokens=1024,
                    temperature=0,
                )
            except (RateLimitError, APIError) as e:
                logger.warning("Enrichment agent Groq error (round %d): %s", round_num, e)
                break

            choice = response.choices[0]

            # If no tool calls, agent is done
            if not choice.message.tool_calls:
                break

            # Process each tool call
            messages.append(choice.message)  # assistant message with tool_calls

            for tool_call in choice.message.tool_calls:
                func_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse tool call args: %s", tool_call.function.arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Error: invalid arguments"
                    })
                    continue

                if func_name == "web_search":
                    results = await web_search(args.get("query", ""))
                    tool_result = json.dumps(results[:5], ensure_ascii=False)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result
                    })

                elif func_name == "update_entry":
                    fields = args.get("fields", {})
                    success = await update_entry(page_id, fields)
                    if success:
                        enriched_something = True
                        # Track what was updated
                        updated_keys = list(fields.keys())
                        enrichment_descriptions.append(f"updated {', '.join(updated_keys)}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"success": success})
                    })

                elif func_name == "ask_user":
                    question = args.get("question", "")
                    if question:
                        await ask_user(bot, chat_id, page_id, question, user_id)
                        enriched_something = True
                        enrichment_descriptions.append("asked a follow-up question")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"sent": bool(question)})
                    })

                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Unknown tool: {func_name}"
                    })

            # If finish_reason is "stop", no more tool calls expected
            if choice.finish_reason == "stop":
                break

        # Notify user if enrichment happened (but not if we only asked a question)
        if enriched_something and any("updated" in d for d in enrichment_descriptions):
            description = "; ".join(enrichment_descriptions)
            notification = f"✨ Enriched — {description}"
            try:
                await bot.send_message(chat_id=chat_id, text=notification)
                append_to_conversation_log(page_id, "Second Brain", notification)
            except Exception:
                logger.exception("Failed to send enrichment notification")

    except Exception as e:
        logger.exception("Enrichment agent failed for page %s: %s", page_id, e)
        # Never crash — the entry is already saved
