# Second Brain — Deployment Guide
> Handoff document for Claude Code. All code changes are complete. This guide covers what changed, env vars to set, and how to deploy.

---

## What Changed (Summary)

### Phase 3 — Agentic Enrichment Pipeline
| Feature | Files | Change |
|---|---|---|
| AI Summary in page body | `app/processors/ai.py`, `app/models.py` | `ProcessedEntry` now includes `ai_summary` field; system prompt produces 2-4 paragraph analysis per content type; max_tokens raised to 2048 |
| Structured Notion page body | `app/storage/notion.py` | Page body rebuilt with sections: **AI Summary → Raw Content → Conversation Log**, separated by dividers. 100-block limit enforced. |
| Conversation log | `app/storage/notion.py` | `append_to_conversation_log()` — appends "Speaker: message" blocks to page. Used by all handlers. |
| Smart CONTEXT handler | `app/processors/ai.py`, `app/handlers/message.py` | `process_context_update()` merges follow-up info into existing entry properties (metadata, tags, headline) via AI. Replaces dumb text append. |
| Session upgrades | `app/session.py` | Richer session data (tags, metadata, bot_last_message), 5-minute TTL auto-expiry, `update_interaction()` for timestamp refresh. |
| Intent classification v2 | `app/processors/intent.py` | Prompt now includes entry type, tags, bot's last message, elapsed time for better CONTEXT vs NEW distinction. |
| Brave Search client | `app/agents/tools.py` | `web_search()` via Brave Search API (httpx). Daily counter, graceful skip if no API key. |
| Enrichment agent | `app/agents/enrichment.py` | Background agent fires after every save. Uses Groq tool calling (web_search, update_entry, ask_user). 3-round cap. Sends "✨ Enriched" notification on updates. |
| Notion property updates | `app/storage/notion.py` | `update_notion_properties()` — updates specific properties (title, headline, tags, metadata) via `client.pages.update()`. |
| Error handling | `app/exceptions.py` | Added `BraveSearchError` for search failures. |

### Phase 2 — Bug Fixes
| Bug | File | Fix |
|---|---|---|
| URL extraction fragile + silent failures | `app/extractors/url.py` | Replaced trafilatura with Jina AI Reader; Reddit JSON kept as first attempt with Jina fallback; redirect resolution added for share links |
| URL detection too strict (`startswith`) | `app/extractors/detector.py` | Now uses Telegram's message entities to detect URLs anywhere in the message |
| `source_url` never set for TEXT+URL messages | `app/handlers/message.py` | URL extracted from message entities and passed as `source_url` even for TEXT-type messages |
| Empty content saves silently | `app/handlers/message.py` | Bot now notifies user with ⚠️ message if content extraction returns empty |
| Wrong SDK + wrong model | `app/extractors/voice.py`, `app/processors/ai.py` | Fully replaced — see Groq migration below |

### Groq Migration (replaces Gemini entirely)
| File | Change |
|---|---|
| `app/extractors/voice.py` | Replaced Gemini audio with Groq Whisper (`whisper-large-v3-turbo`) via `openai` SDK |
| `app/processors/ai.py` | **New file** — replaces `gemini.py`. Text tasks → `llama-3.3-70b-versatile`. Image tasks → `meta-llama/llama-4-scout-17b-16e-instruct` |
| `app/processors/gemini.py` | **Deleted** — replaced by `ai.py` |
| `app/processors/intent.py` | Replaced Gemini with Groq `llama-3.1-8b-instant` |

### Notion Schema Redesign
| File | Change |
|---|---|
| `app/storage/notion.py` | Full rewrite — new 10-property schema, JSON metadata blob, `original_message` field, `Headline` replaces `Summary` |
| `app/models.py` | `ProcessedEntry`: `summary` → `headline`; added `original_message`. `RawInput`: added `original_message` |
| `app/processors/ai.py` | Updated system prompt to produce `headline` + dynamic `metadata` JSON |

### Config & Dependencies
| File | Change |
|---|---|
| `app/config.py` | `gemini_api_key` → `groq_api_key` |
| `requirements.txt` | Removed `google-generativeai`, `trafilatura`. Added `openai` |
| `.env.example` | `GEMINI_API_KEY` → `GROQ_API_KEY` |

---

## Environment Variables

### Render — Variables to Update
Go to [Render Dashboard](https://dashboard.render.com/web/srv-d6k1prrh46gs73e6em90) → Environment.

| Action | Variable | Value |
|---|---|---|
| **Add** | `GROQ_API_KEY` | Your Groq API key from [console.groq.com](https://console.groq.com) |
| **Add** | `BRAVE_API_KEY` | Free key from [brave.com/search/api](https://brave.com/search/api/) — 2K queries/month free tier. Optional: enrichment agent skips search if missing. |
| **Delete** | `GEMINI_API_KEY` | No longer needed |
| Keep | `TELEGRAM_BOT_TOKEN` | Unchanged |
| Keep | `NOTION_TOKEN` | Unchanged |
| Keep | `NOTION_DATABASE_ID` | Unchanged |
| Keep | `WEBHOOK_SECRET` | Unchanged |

> ⚠️ Do NOT commit the actual `GROQ_API_KEY` value to git. It lives only in `.env` locally and in Render's env vars.

---

## Notion Database Migration

The database schema has been fully redesigned. **This must be done before or immediately after deploying** — the new code will fail to write entries against the old schema.

### Option A — Automated (preferred)
The Notion MCP in Cowork has already been used to migrate the schema. Verify by opening the database and confirming these properties exist:

**New properties (10):**
`Title`, `Type`, `Headline`, `Original Message`, `Tags`, `Source URL`, `File`, `Metadata`, `Created`, `Starred`

**Deleted properties (25+):**
`Author`, `Category`, `Company`, `Contact Name`, `Cook Time`, `Cuisine`, `Dietary`, `Entities`, `Genre`, `Hypothesis`, `Key Takeaway`, `Mentioned By`, `Next Step`, `Page Count`, `Price Range`, `Problem`, `Product Name`, `Recommended By`, `Role`, `Solution`, `Status`, `Summary`, `Use Case`, `Where Met`

### Option B — Manual (if migration needs to be redone)
1. Open the Second Brain database in Notion
2. Delete all columns listed under "Deleted properties" above
3. Add the following new columns:

| Property Name | Type | Notes |
|---|---|---|
| `Headline` | Text | |
| `Original Message` | Text | |
| `File` | Files & Media | |
| `Metadata` | Text | Stores JSON |
| `Starred` | Checkbox | |

4. Rename `Summary` → `Headline` (or delete and recreate)
5. Existing entries will have empty new fields — that's expected

---

## Deployment Steps

```bash
# From the second-brain repo root
git add .
git commit -m "Migrate to Groq, fix URL extraction, redesign Notion schema"
git push origin main
```

Render auto-deploys within ~3 minutes. Monitor at:
https://dashboard.render.com/web/srv-d6k1prrh46gs73e6em90

---

## Verification Checklist

After deploy, test each input type via Telegram (@MyMindPalaceBot):

- [ ] **Bare URL** — Send `https://www.reddit.com/r/ClaudeAI/s/...` (share link) → should save with content, not empty
- [ ] **Text + URL** — Send `"Check this out https://reddit.com/..."` → should save with `Source URL` populated
- [ ] **Plain text** — Send an idea → should save with `Original Message` populated in Notion
- [ ] **Image** → should classify and extract via Llama 4 Scout vision
- [ ] **Voice note** → should transcribe via Whisper
- [ ] **JS-heavy URL** — Send a Twitter/X link → Jina should handle it
- [ ] **Empty extraction** — Send a URL that can't be fetched → bot should reply with ⚠️ warning, not silent junk save

---

## File Tree of Changed Files

```
app/
├── config.py               ← groq_api_key + brave_api_key; extra="ignore" for pydantic
├── models.py               ← added ai_summary, original_message to ProcessedEntry
├── exceptions.py           ← GroqError + BraveSearchError
├── session.py              ← rewritten: TTL expiry, timestamps, bot_last_message tracking
├── agents/                 ← NEW package (Phase 3)
│   ├── __init__.py
│   ├── enrichment.py       ← background enrichment agent (Groq tool calling)
│   └── tools.py            ← web_search (Brave), update_entry, ask_user
├── extractors/
│   ├── detector.py         ← URL detection uses Telegram entities
│   ├── url.py              ← Jina AI Reader + better Reddit handling
│   └── voice.py            ← Groq Whisper
├── processors/
│   ├── ai.py               ← Groq LLM + ai_summary + process_context_update()
│   ├── gemini.py           ← DELETED
│   └── intent.py           ← richer context (type, tags, bot_last_message, elapsed)
├── handlers/
│   └── message.py          ← session expiry, smart CONTEXT, conversation log, enrichment fire
└── storage/
    └── notion.py           ← structured page body, conversation log, update_notion_properties()
requirements.txt            ← openai added, google-generativeai + trafilatura removed
.env.example                ← GROQ_API_KEY + BRAVE_API_KEY
```

---

*Generated: March 2026*
