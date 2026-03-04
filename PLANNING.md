# Second Brain — Planning Document
> Brainstorming session: March 2026. Captures all decisions, identified bugs, and planned changes before implementation begins.

---

## 1. Current Problems

### 1.1 AI Provider: Gemini Rate Limits
The current implementation uses `gemini-2.5-flash` (and in places, the older `gemini-1.5-flash`) via the `google-generativeai` SDK. The free tier limits are too restrictive for reliable personal use:
- **20 requests/day** across all Gemini calls
- **5 requests/minute**

This is the primary motivation for migrating to Groq.

### 1.2 Bugs Identified in Current Implementation

> ⚠️ Bugs verified against live Notion entries and Telegram screenshots (March 2026).

**Bug 1 — URL extraction is fragile and fails silently across many URL types**
Both extraction paths in `url.py` silently return `""` in a wide range of failure cases. `raw_content = ""` flows through unchecked — the bot saves a hollow Notion entry and replies "Saved ✅" with no indication anything went wrong.

Known failure cases:

| URL type | Why it fails |
|---|---|
| Reddit share links (`/s/` format) | `.json?limit=10` trick requires a standard post URL; share links need redirect resolution first |
| JS-rendered pages | Twitter/X, LinkedIn, TikTok, Instagram, modern SPAs — `trafilatura` fetches raw HTML, gets an empty shell |
| Paywalled content | NYT, Bloomberg, Medium members-only — returns paywall HTML, not article |
| Login-required pages | LinkedIn profiles, private GitHub repos — returns login page |
| Bot-blocked sites | Amazon, some news sites — returns 403 or CAPTCHA |
| Short/redirect links | `bit.ly`, `t.co` — redirect chain may not resolve correctly |
| Direct PDF URLs | A URL serving a raw PDF file (not a webpage) |

Verified in Notion: entry titled *"No Content Provided for Analysis"* — Reddit share link `https://www.reddit.com/r/ClaudeAI/s/qz5gzCl5rR` correctly saved as `source_url` but page body empty, Type set to Note, tags `#empty #no-content #placeholder`.

**Recommended fix — replace `trafilatura` with Jina AI Reader:**
[Jina AI Reader](https://jina.ai/reader/) (`r.jina.ai`) is a free service requiring no API key. Prefix any URL to get clean markdown back: `GET https://r.jina.ai/{url}`. It runs a headless browser server-side, handling JS rendering, redirects, and most URL types robustly. Reddit JSON API can be kept as a first attempt for richer comment data, falling back to Jina on failure.

Additionally, extraction failure must **never be silent**. If `raw_content` is empty after all attempts, the bot should notify the user (e.g. "⚠️ Saved the link but couldn't fetch the content — add context manually") rather than producing a junk entry.

**Bug 2 — URL detection is too strict**
`detector.py` only classifies a message as `InputType.URL` if it *starts with* `http://` or `https://`:
```python
if message.text and message.text.startswith(("http://", "https://")):
```
Any message with text before the link (e.g. `"Found this interesting reddit post... https://reddit.com/..."`) is classified as `InputType.TEXT`. The URL is never scraped, and the linked content never reaches the AI.

Verified in Notion: entry titled *"Claude AI Customization Skills"* — AI correctly guessed it was Reddit content from the user's own annotation text, but the actual Reddit post was never fetched.

**Bug 3 — `source_url` never set for TEXT-type messages**
In `_extract_content`, the `TEXT` branch creates a `RawInput` with no `source_url`:
```python
elif input_type == InputType.TEXT:
    return RawInput(input_type=input_type, content=message.text)
```
Even when the message contains a URL, it is never extracted into `source_url`, so the Notion `Source URL` property is always empty for these entries.

Verified in Notion: `"Claude AI Customization Skills"` entry has `Source URL: ""` despite the message containing a Reddit link.

**Bug 4 — Old SDK and wrong model still in use**
Despite `CLAUDE.md` noting migration to `google-genai`, both `voice.py` and `gemini.py` still import the deprecated `google.generativeai` SDK. Both files call `gemini-1.5-flash`, not `gemini-2.5-flash` as intended. This means the app is running on an older, less capable model and a deprecated SDK simultaneously.

**Clarification on what is NOT a bug:**
- For bare URL messages (no preceding text), `source_url` IS correctly saved — the URL detection works fine in this case.
- The original message text IS preserved in the page body for TEXT-type entries — it is not lost.

---

## 2. AI Provider Migration: Gemini → Groq

### Why Groq
- **Generous free tier** — dramatically better than Gemini's 20 RPD
- **OpenAI-compatible API** — migrate once using the `openai` Python package; swap providers later by changing base URL and model name only
- **Full coverage** of all required capabilities: text, vision, and speech-to-text

### Model Mapping

| Task | Model | Free Tier Limits |
|---|---|---|
| Text classification, extraction, intent detection (complex) | `llama-3.3-70b-versatile` | 30 RPM / 1K RPD |
| Intent detection (simple, high-volume) | `llama-3.1-8b-instant` | 30 RPM / 14.4K RPD |
| Image analysis / vision | `meta-llama/llama-4-scout-17b-16e-instruct` | 30 RPM / 1K RPD |
| Voice transcription | `whisper-large-v3-turbo` | 20 RPM / 2K RPD / 28.8K audio seconds/day |

### Files Requiring Changes (3 files only)

| File | Change Required |
|---|---|
| `app/extractors/voice.py` | Replace `google.generativeai` + Gemini audio with Groq Whisper via `openai` SDK |
| `app/processors/gemini.py` | Replace `google.generativeai` with Groq chat completions; route image inputs to vision model |
| `app/processors/intent.py` | Replace `google.generativeai` with Groq chat completions |

### Files Requiring No Changes

| File | Reason |
|---|---|
| `app/extractors/pdf.py` | Pure Python (PyMuPDF) — no AI involved |
| `app/extractors/image.py` | Just base64 encodes bytes — no AI involved |
| `app/extractors/url.py` | Uses `trafilatura` for scraping — no AI involved |
| `app/extractors/detector.py` | Pure logic — no AI involved |

### Config Changes
- Add `GROQ_API_KEY` to `.env`, `.env.example`, and Render environment variables
- Remove (or keep as fallback) `GEMINI_API_KEY`
- Update `requirements.txt`: add `openai`, remove `google-generativeai` / `google-genai`

---

## 3. Notion Schema Redesign

### The Problem with the Current Schema
The current database has 25+ hardcoded columns (`Contact Name`, `Company`, `Role`, `Where Met`, `Author`, `Cook Time`, `Price Range`, etc.). For any given entry, ~18 of these columns are NULL. This is a relational database pattern forced onto what is fundamentally a heterogeneous, flexible knowledge store. It is rigid, hard to extend, and cluttered to browse.

### New Schema

| # | Field | Notion Type | Purpose |
|---|---|---|---|
| 1 | `Title` | Title | AI-generated descriptive title (≤10 words) |
| 2 | `Type` | Select | Dynamic content type — AI decides (Article, Contact, Idea, Reddit, Recipe, etc.) |
| 3 | `Headline` | Rich Text | One-sentence AI summary optimised for scanning — designed for future Claude reference |
| 4 | `Original Message` | Rich Text | Verbatim what the user sent — preserved exactly, never modified by AI |
| 5 | `Tags` | Multi-select | 2–5 lowercase tags for filtering |
| 6 | `Source URL` | URL | Origin link if applicable |
| 7 | `File` | Files & Media | Original file attached to the entry (image, PDF, voice note) |
| 8 | `Metadata` | Rich Text (JSON) | All type-specific structured data as a JSON object — replaces all hardcoded columns |
| 9 | `Created` | Created Time | Auto-populated timestamp |
| 10 | `Starred` | Checkbox | Manual flag for follow-up or high-value entries |

**+ Page Body (11th "field")**: Full content stored as Notion paragraph blocks — scraped article text, Reddit post + comments, PDF text, voice transcription, image analysis output. Not a database property — lives inside the page itself. Critical for future vector/semantic search.

### Metadata Field Design
Instead of hardcoded columns, the `Metadata` rich text field stores a dynamic JSON object. The AI determines the shape based on content type. Examples:

```json
// Contact
{
  "contact_name": "Sarah Chen",
  "company": "Stripe",
  "role": "ML Engineer",
  "where_met": "YC Demo Day March 2026"
}

// Book
{
  "author": "James Clear",
  "genre": "Self-improvement",
  "page_count": 320,
  "recommended_by": "Ravi"
}

// Idea
{
  "problem": "Users drop off during onboarding",
  "hypothesis": "Social proof reduces friction",
  "next_step": "Prototype one screen"
}

// Article / Reddit
{
  "key_takeaway": "Attach habits to existing anchors, not fixed times"
}

// Dynamic / invented type — AI decides fields
{
  "event": "Startup Grind March 2026",
  "speaker": "Naval Ravikant",
  "topic": "Default alive vs default dead"
}
```

### Why `Starred` Instead of `Status`
The current `Status` field is hardcoded to `"Unread"` and never changes — it is dead weight. A simple `Starred` checkbox is more honest and more useful for a personal memory system. It gives a way to flag entries for follow-up without implying a workflow that doesn't exist.

### What Gets Deleted from the Current Schema
All of the following columns are removed and replaced by the single `Metadata` JSON field:
`Contact Name`, `Company`, `Role`, `Where Met`, `Author`, `Recommended By`, `Cook Time`, `Product Name`, `Category`, `Price Range`, `Key Takeaway`, `Mentioned By`, `Use Case`, `Problem`, `Solution`, `Hypothesis`, `Next Step`, `Genre`, `Page Count`, `Cuisine`, `Dietary`, `Entities`, `Status`, `Summary` (replaced by `Headline`)

---

## 4. Future Vision: Agentic Pipeline (Phase 3)

> Not in current implementation scope — documented for future reference.

### The Gap
The current pipeline is single-shot: message → one AI call → Notion write. It has no tools, no loop, no agency. The vision is a memory agent that:
1. Saves immediately (zero-friction capture)
2. Enriches asynchronously — web search for context, entity lookup
3. Asks one targeted follow-up question if something high-value is missing

### Key Design Principle: Save First, Enrich After
Never block the save on a follow-up question. The "save immediately → CONTEXT/DONE/NEW intent" pattern that already exists is the right skeleton — it just needs to become a post-save enrichment channel rather than a passive listener.

### Capabilities to Add
- **Web search tool** — Triggered selectively when AI judges it would add value (e.g. name card photo → search person/company; book title → fetch synopsis)
- **Proactive follow-up** — One targeted question after saving, not a blocker before
- **Async enrichment** — Update the Notion entry after the initial save with additional context

### Model Requirements for Agentic Pipeline
Needs a model with solid function/tool calling support. `llama-4-scout` and `llama-4-maverick` on Groq both support tool use — consistent with the Groq migration above.

---

## 5. Implementation Order

1. **Fix the 4 bugs** (URL extraction fragility + Jina migration, URL detection, source_url for TEXT messages, old SDK/model)
2. **Groq migration** (3 files: `voice.py`, `gemini.py`, `intent.py`)
3. **Notion schema redesign** (update `notion.py`, update `gemini.py` system prompt, migrate Notion database)
4. **Phase 3: Agentic pipeline** (future)

---

*Last updated: March 2026 — Bug 1 broadened from Reddit share links to general URL extraction fragility; Jina AI Reader added as recommended fix*
