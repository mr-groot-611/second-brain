# Second Brain

A personal knowledge capture system powered by Telegram, Gemini AI, and Notion.

Send anything to the Telegram bot — URLs, images, PDFs, voice notes, or plain text — and it gets automatically classified, summarised, and saved to your Notion database with structured metadata. Ask Claude to retrieve it later from any device.

## Architecture

```
Telegram Bot → FastAPI (Render) → Gemini AI → Notion
```

- **Capture**: Telegram bot (@MyMindPalaceBot) accepts any content type
- **Process**: Gemini 1.5 Flash classifies, summarises, and extracts type-specific metadata
- **Store**: Notion database with full raw content + structured fields
- **Retrieve**: Ask Claude — it reads your connected Notion workspace

## Supported Content Types

| Type | What it captures |
|------|-----------------|
| Article | Web articles (trafilatura extraction) |
| Reddit | Reddit threads + top comments |
| Book | Title, author, genre, page count, key ideas |
| Contact | Name, company, role, where met, notes |
| Recipe | Ingredients, steps, cuisine, prep time |
| Product | Name, price, specs, purchase URL |
| Place | Location, category, opening hours |
| Lead | Business opportunity mentions |
| Idea | Original thoughts and observations |
| Note | Fallback for anything else |

Gemini can also invent new type names when content doesn't fit any category.

## Features

- **Zero friction capture** — send anything, no formatting required
- **Conversational context** — add follow-up context to any saved entry; Gemini detects intent (CONTEXT / DONE / NEW) automatically
- **Full content stored** — raw text always saved for future vector/semantic search
- **Voice notes** — transcribed via Gemini Audio (no Whisper needed)
- **PDFs** — text extracted with PyMuPDF
- **Images** — described via Gemini Vision

## Setup

### Prerequisites

- Python 3.11+
- Telegram bot token (from @BotFather)
- Gemini API key (Google AI Studio)
- Notion internal integration token + database ID
- Render account (free tier works)

### Local Development

```bash
# Clone the repo
git clone https://github.com/mr-groot-611/second-brain.git
cd second-brain

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill in credentials
cp .env.example .env
# Edit .env with your real values

# Run tests
pytest tests/ -v

# Run locally (for testing — webhook won't work without a public URL)
uvicorn app.main:app --reload
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `GEMINI_API_KEY` | From Google AI Studio |
| `NOTION_TOKEN` | Internal integration secret (starts with `ntn_`) |
| `NOTION_DATABASE_ID` | ID from your Notion database URL |
| `WEBHOOK_SECRET` | Any random string you choose |

### Notion Setup

1. Create an internal integration at https://www.notion.so/my-integrations
2. Copy the integration secret → `NOTION_TOKEN`
3. Open your Second Brain database in Notion
4. Click **···** → **Add connections** → select your integration
5. Copy the database ID from the URL: `notion.so/{workspace}/{DATABASE_ID}?v=...`

### Deploy to Render

1. Push this repo to GitHub
2. Go to https://render.com → **New Web Service**
3. Connect your GitHub repo
4. Set:
   - **Runtime**: Python
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add all 5 environment variables in the Render dashboard
6. Deploy and copy your Render URL (e.g. `https://second-brain-xxxx.onrender.com`)

### Register Telegram Webhook

After deploying to Render:

```bash
RENDER_URL=https://your-app.onrender.com python scripts/register_webhook.py
```

Or set `RENDER_URL` in your `.env` file, then run the script.

## Project Structure

```
second-brain/
├── app/
│   ├── config.py          # Settings (loaded from .env)
│   ├── models.py          # InputType, RawInput, ProcessedEntry
│   ├── session.py         # In-memory session state
│   ├── bot.py             # Telegram Application setup
│   ├── main.py            # FastAPI app + webhook endpoint
│   ├── extractors/
│   │   ├── detector.py    # Detect input type from message
│   │   ├── url.py         # Article + Reddit extraction
│   │   ├── pdf.py         # PDF text extraction (PyMuPDF)
│   │   ├── image.py       # Base64 image preparation
│   │   └── voice.py       # Voice transcription (Gemini Audio)
│   ├── processors/
│   │   ├── gemini.py      # Main AI processing pipeline
│   │   └── intent.py      # CONTEXT / DONE / NEW classification
│   ├── storage/
│   │   └── notion.py      # Write + update Notion pages
│   └── handlers/
│       └── message.py     # Telegram message handler (main pipeline)
├── scripts/
│   └── register_webhook.py
├── tests/
│   ├── test_models.py
│   ├── test_detector.py
│   ├── test_extractors.py
│   ├── test_session.py
│   ├── test_intent.py
│   ├── test_gemini.py
│   ├── test_notion.py
│   └── test_webhook.py
├── .env.example
├── render.yaml
└── requirements.txt
```

## Usage

Once deployed and webhook registered:

1. Open Telegram → search **@MyMindPalaceBot** → `/start`
2. Send anything:
   - A URL: `https://paulgraham.com/founders.html`
   - A thought: `Idea: use embeddings to cluster my saved articles weekly`
   - A contact: `Met Priya at NASSCOM — she's Head of Product at Sarvam AI, working on voice AI for Bharat`
   - A photo of a book cover, whiteboard, or receipt
   - A PDF attachment
   - A voice note
3. Bot saves it to Notion and replies with a summary
4. Add context: `she also mentioned they're hiring ML engineers`
5. Ask Claude: *"What do I know about Sarvam AI?"*

## Retrieval

Ask Claude in any conversation:
- *"What books have I saved with fewer than 300 pages?"*
- *"Who did I meet at Startup Grind?"*
- *"What recipes did I save last month?"*
- *"Find everything I've saved about LLM fine-tuning"*

Claude reads your connected Notion workspace and answers from your saved entries.

## Future Roadmap

- **Phase 3**: Vector embeddings + semantic search (Pinecone or pgvector)
- **Telegram query**: `/find founders essay` directly in the bot
- **Deduplication**: detect near-duplicate entries on save
- **Weekly digest**: Notion automation or cron to summarise recent captures
