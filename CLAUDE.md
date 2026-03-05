# Second Brain

## About
A personal knowledge capture system built for Varun. Telegram bot (@MyMindPalaceBot) captures any content (URLs, images, PDFs, voice notes, text) → Groq AI classifies and extracts structured metadata → stored in Notion for retrieval via Claude from any device (desktop, iOS, web).

## Goal
Zero-friction capture from phone or any device. Ask Claude later to retrieve entries using natural language queries against the Notion database.

## Architecture
```
Telegram Bot → FastAPI webhook (Render free tier) → Groq (Llama 4 Scout / Llama 3.3 70B / Whisper) → Notion database
```

## Deployment (Live)
- **Render service**: https://second-brain-aqhg.onrender.com
- **Render dashboard**: https://dashboard.render.com/web/srv-d6k1prrh46gs73e6em90
- **GitHub repo**: https://github.com/mr-groot-611/second-brain (public)
- **Telegram webhook**: registered at `/webhook/mindpalace_secret_2026`
- Auto-deploy on push to `main` is enabled

## Credentials & Config
- **Telegram bot**: @MyMindPalaceBot (token stored in `.env` and Render env vars)
- **Groq**: API key in `.env` and Render env vars — env var name: `GROQ_API_KEY`
- **Brave Search**: API key in `.env` and Render env vars — env var name: `BRAVE_API_KEY` (optional; enrichment skips web search if missing; free tier: 2K queries/month at https://brave.com/search/api/)
- **Notion integration token**: starts with `ntn_` — stored in `.env` and Render env vars
- **Notion database ID**: `21f1664902474a90a4c8b971fefd49d2`
- **Webhook secret**: `mindpalace_secret_2026`
- ⚠️ `.env` is gitignored — copy `.env.example` and fill in real values locally
- ⚠️ `GEMINI_API_KEY` is no longer used — replaced by `GROQ_API_KEY`

## Work Completed
- Full application deployed and working end-to-end
- Code pushed to GitHub (`main` branch), auto-deploys to Render on push
- Notion database connected and accessible by the integration
- Telegram webhook registered and verified
- **March 2026 Session 1**: Full migration from Gemini to Groq; Notion schema redesigned from 25 rigid columns to 10 flexible fields; bug fixes (URL detection, source_url, silent empty saves, Jina extraction)
- **March 2026 Session 2**: Post-deployment bug fixes (base64 fix, title/headline prompt, PDF error handling, session clearing on error, specific error messages); Notion file upload implemented for images + PDFs (async background upload, embedded as blocks in page body); `File` database property dropped (not supported via API); `app/exceptions.py` added
- **March 2026 Session 3 (Phase 3 — Agentic Pipeline)**: Full implementation of the agentic enrichment pipeline. All 13 tasks in `docs/plan-agentic-pipeline.md` completed. Added: AI summary generation during save, structured Notion page body (AI Summary → Raw Content → Conversation Log), conversation log append, session TTL auto-expiry (5 min), richer intent classification, smart CONTEXT handler (AI merges follow-up info into existing properties), Brave Search client, background enrichment agent with Groq tool calling (web_search + update_entry + ask_user), `BraveSearchError` exception. Stale test files (`test_gemini.py`, `test_extractors.py`) removed. 67 tests passing.
- **March 2026 Session 4 (Bug Fix — Notion unicode rejection)**: Fixed Notion write failures for URLs whose Jina-extracted content contains non-BMP emoji (e.g. 🙌 U+1F64C). Root cause: Notion's API rejects `rich_text` blocks with characters > U+FFFF with a 400 validation error, which was mis-reported to user as a token error. Fix: added `_sanitize()` in `app/storage/notion.py` that replaces non-BMP chars with U+FFFD; applied to all text fields (blocks, title, headline, tags, metadata, original_message, conversation log). 67 tests still passing. Committed to `main`; **needs `git push origin HEAD:main` to deploy**.
- Planning docs: `PLANNING.md` (decisions + bug log), `DEPLOY.md` (Claude Code handoff), `CHANGE_LOG.md` (per-session code changes for Claude Code handoff)

## Key Decisions
- **Groq** for all AI tasks — OpenAI-compatible API, generous free tier, no cost
  - Text tasks: `llama-3.3-70b-versatile` (1K RPD)
  - Intent detection: `llama-3.1-8b-instant` (14.4K RPD)
  - Vision/images: `meta-llama/llama-4-scout-17b-16e-instruct` (1K RPD)
  - Voice transcription: `whisper-large-v3-turbo` (2K RPD / 28.8K audio seconds/day)
- **Jina AI Reader** (`r.jina.ai`) for URL extraction — no API key, handles JS rendering, redirects, share links
- **Reddit JSON API** as first attempt for Reddit URLs (richer comment data), falls back to Jina
- **Dynamic metadata**: AI returns a JSON blob — no hardcoded per-type columns
- **Save first, enrich after**: bot saves immediately, then fires a background enrichment agent (Groq tool calling) that may search the web, update metadata, or ask a follow-up question
- **Full raw content stored** in Notion page body — designed for future vector/semantic search
- **Brave Search** (free tier, 2K/month) for enrichment agent web searches; gracefully skips if no API key
- **Session TTL** of 5 minutes — expired sessions are treated as new messages (no stale intent classification)
- **Render free tier**: sleep-on-inactivity is acceptable for personal use; webhook-based (not polling)

## Notion Schema (9 properties + page body)
| Property | Type | Purpose |
|---|---|---|
| `Name` | Title | AI-generated title (≤10 words) |
| `Type` | Select | Dynamic content type |
| `Headline` | Text | One-sentence AI summary for scanning |
| `Original Message` | Text | Verbatim what the user sent |
| `Tags` | Multi-select | 2–5 lowercase tags |
| `Source URL` | URL | Origin link |
| `Metadata` | Text (JSON) | Dynamic type-specific structured data |
| `Starred` | Checkbox | Manual follow-up flag |
| `Date Saved` | Created Time | Auto timestamp |

Page body (structured sections):
1. **AI Summary** — 2-4 paragraph interpretive analysis (key takeaways, structured framing, cleaned-up transcriptions)
2. **Raw Content** — full scraped/transcribed text + uploaded image/PDF embedded as Notion block
3. **Conversation** — running log of user messages and bot responses (appended via `append_to_conversation_log`)

Note: `File` (Files & Media) property was dropped — Notion API does not support writing file_upload IDs to database properties, only to page blocks.

## Project Structure
```
second-brain/
├── app/
│   ├── config.py         (groq_api_key, brave_api_key, extra="ignore")
│   ├── models.py         (RawInput + ProcessedEntry — includes ai_summary, original_message)
│   ├── exceptions.py     (GroqError, NotionError, TelegramFileError, BraveSearchError)
│   ├── session.py        (SessionStore with TTL expiry, timestamps, bot_last_message)
│   ├── bot.py, main.py
│   ├── agents/           (Phase 3 enrichment)
│   │   ├── enrichment.py (background enrichment agent — Groq tool calling)
│   │   └── tools.py      (web_search, update_entry, ask_user)
│   ├── extractors/       (detector, url, pdf, image, voice)
│   ├── processors/       (ai.py — process_with_ai + process_context_update, intent.py)
│   ├── storage/          (notion — write, update_properties, append_conversation_log, file upload)
│   └── handlers/         (message — main pipeline with session expiry, smart CONTEXT, enrichment)
├── scripts/
│   └── register_webhook.py
├── tests/                (67 tests — all passing)
├── docs/
│   ├── product-vision.md         ← public product vision, positioning, 4 pillars, competitive landscape
│   ├── design-agentic-pipeline.md
│   └── plan-agentic-pipeline.md (Complete)
├── PLANNING.md           ← decisions, bug log, schema design rationale
├── DEPLOY.md             ← deployment checklist (updated for Phase 3)
├── .env.example
├── render.yaml
└── requirements.txt
```

## Re-deploying / Making Changes
1. Edit code locally
2. `git push origin HEAD:main` — Render auto-deploys within ~3 min
3. **Before deploying Phase 3**: add `BRAVE_API_KEY` to Render env vars (optional but recommended for enrichment)
4. See `DEPLOY.md` for full deployment checklist
5. To manually trigger: `curl -X POST -H "Authorization: Bearer <RENDER_API_KEY>" https://api.render.com/v1/services/srv-d6k1prrh46gs73e6em90/deploys`

## Known Issues (Pending Fix)
- **Telegram video notes not handled** — `message.video_note` (round video format) falls through silently: no response, no Notion entry. Decision pending: graceful rejection message vs full audio transcription support. Fix goes in `detector.py` + `message.py`.

## Design Docs
- `docs/design-agentic-pipeline.md` — Phase 3 agentic enrichment pipeline design. Covers: background enrichment agent with Groq tool calling, Brave Search integration, smart follow-up questions, AI summary in page body, conversation log, session auto-expire + smarter intent detection, smart CONTEXT handler that updates properties.
- `docs/design-second-brain-retrieval-skill.md` — Cowork plugin design for automatic Notion retrieval on memory/find/recall queries. Adaptive depth (surface for 3+, deep read for 1-2), keyword + semantic search, natural language result presentation. Plugin file: `second-brain-retrieval.plugin`.

## Implementation Plans
- `docs/plan-agentic-pipeline.md` — **Complete**. 13 tasks all implemented and verified. Local tests pass (67 tests). Needs live Telegram testing after deploy.

## Future Phases
- **Enrichment AI Summary append** — enrichment agent currently can't update the original AI Summary block in Notion (block API limitation). Enhancement: append a new "Enriched Summary" section after web search results are available, rather than trying to edit the existing block. See `docs/design-agentic-pipeline.md` → "Implementation Notes" for context.
- Vector embeddings + semantic search (Pinecone or pgvector)
- Telegram `/find` command for in-bot search
- Weekly digest automation
- Deduplication on save
- Prompt tuning based on live usage (ai_summary quality, enrichment agent selectivity, intent classification accuracy)

## Public Product Direction
Vision and competitive landscape documented in `docs/product-vision.md`. Key decisions from March 2026 brainstorm:
- **Vision**: "Your memory, augmented" — genuine knowledge layer, not a smart reminder app
- **Moat**: depth of AI processing (enrichment pipeline) enables synthesis-quality retrieval vs competitors who do lookup
- **4 pillars**: Capture → Understand → Act → Retrieve/Synthesise
- **Target user**: power users / knowledge workers (niche, not mass market)
- **Storage for public**: Notion won't work multi-tenant — needs own DB (Supabase/Postgres), decided in principle
- **Capture surface for public**: deferred — separate brainstorm needed
- **Out of scope for now**: collaboration/shared memory, proactive/ambient surfacing, general consumer market
- **Next brainstorm needed**: capture surface beyond Telegram, onboarding, action integrations (calendar/todos), pricing/monetisation, launch sequencing
