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
- **March 2026**: Full migration from Gemini to Groq (see below)
- **March 2026**: Notion schema redesigned from 25 rigid columns to 10 flexible fields
- **March 2026**: Bug fixes — URL detection, source_url, silent empty saves, Jina extraction
- Planning docs: `PLANNING.md` (decisions + bug log), `DEPLOY.md` (Claude Code handoff)

## Key Decisions
- **Groq** for all AI tasks — OpenAI-compatible API, generous free tier, no cost
  - Text tasks: `llama-3.3-70b-versatile` (1K RPD)
  - Intent detection: `llama-3.1-8b-instant` (14.4K RPD)
  - Vision/images: `meta-llama/llama-4-scout-17b-16e-instruct` (1K RPD)
  - Voice transcription: `whisper-large-v3-turbo` (2K RPD / 28.8K audio seconds/day)
- **Jina AI Reader** (`r.jina.ai`) for URL extraction — no API key, handles JS rendering, redirects, share links
- **Reddit JSON API** as first attempt for Reddit URLs (richer comment data), falls back to Jina
- **Dynamic metadata**: AI returns a JSON blob — no hardcoded per-type columns
- **Save first, ask after**: bot always saves immediately, never blocks waiting for metadata
- **Full raw content stored** in Notion page body — designed for future vector/semantic search
- **Render free tier**: sleep-on-inactivity is acceptable for personal use; webhook-based (not polling)

## Notion Schema (10 properties + page body)
| Property | Type | Purpose |
|---|---|---|
| `Name` | Title | AI-generated title (≤10 words) |
| `Type` | Select | Dynamic content type |
| `Headline` | Text | One-sentence AI summary for scanning |
| `Original Message` | Text | Verbatim what the user sent |
| `Tags` | Multi-select | 2–5 lowercase tags |
| `Source URL` | URL | Origin link |
| `File` | Files & Media | Attached image/PDF/voice |
| `Metadata` | Text (JSON) | Dynamic type-specific structured data |
| `Starred` | Checkbox | Manual follow-up flag |
| `Date Saved` | Created Time | Auto timestamp |

Page body = full raw content (scraped article, Reddit post+comments, transcription, etc.)

## Project Structure
```
second-brain/
├── app/
│   ├── config.py         (groq_api_key replaces gemini_api_key)
│   ├── models.py         (RawInput + ProcessedEntry — includes original_message)
│   ├── session.py, bot.py, main.py
│   ├── extractors/       (detector, url, pdf, image, voice)
│   ├── processors/       (ai.py ← NEW replaces gemini.py, intent.py)
│   ├── storage/          (notion)
│   └── handlers/         (message — main pipeline)
├── scripts/
│   ├── register_webhook.py
│   └── test_gemini.py    (outdated — replace with test_groq.py in future)
├── tests/                (33 tests — may need updating after migration)
├── PLANNING.md           ← decisions, bug log, schema design rationale
├── DEPLOY.md             ← deployment checklist for Claude Code
├── .env.example
├── render.yaml
└── requirements.txt
```

## Re-deploying / Making Changes
1. Edit code locally
2. `git push origin HEAD:main` — Render auto-deploys within ~3 min
3. **Before deploying**: add `GROQ_API_KEY` to Render env vars, remove `GEMINI_API_KEY`
4. See `DEPLOY.md` for full deployment checklist
5. To manually trigger: `curl -X POST -H "Authorization: Bearer <RENDER_API_KEY>" https://api.render.com/v1/services/srv-d6k1prrh46gs73e6em90/deploys`

## Future Phases
- **Phase 3**: Agentic pipeline — web search tool, proactive enrichment after save, one targeted follow-up question
- **Phase 3**: Vector embeddings + semantic search (Pinecone or pgvector)
- File uploads to Notion (image/PDF/voice attached to entry) — deferred from current migration
- Replace `scripts/test_gemini.py` with a Groq equivalent
- Update test suite (33 tests) to reflect new schema and Groq calls
- Telegram `/find` command for in-bot search
- Weekly digest automation
- Deduplication on save
