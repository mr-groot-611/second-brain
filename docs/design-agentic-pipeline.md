# Design: Agentic Enrichment Pipeline (Phase 3)

## What we're building

Two independent improvements that work together:

1. **A smarter conversation system** — universal session expiry, better intent classification, and a CONTEXT handler that actually updates entry properties (not just appends raw text). This fixes real problems in the current codebase regardless of enrichment.

2. **A background enrichment agent** — runs after every save, can search the web, improve metadata, generate an AI summary, and ask the user one targeted follow-up. Fully asynchronous, never blocks the save.

### The problem it solves

**Thin entries:** The initial AI pass extracts what it can from raw content, but it can't look things up. A contact photo gets saved with a name but no company. A book recommendation gets a title but no synopsis. An idea gets tagged but nobody asks "what's the next step?"

**Manual cleanup:** The user goes back to Notion to fill in gaps. The current CONTEXT handler makes this worse — when the user sends additional info, it just appends raw text to the page body without updating properties (tags, metadata, headline stay unchanged).

**Weak intent detection:** The classifier sees only the entry's title and headline, has no session expiry, and can't distinguish topically similar but unrelated messages. New entries sometimes get misclassified as CONTEXT updates.

## What we considered

### Enrichment architecture

**Approach 1 — Prompt-based decision tree:** AI returns structured JSON saying what enrichment to do, Python code executes it. Simpler but rigid — every new enrichment type needs new code paths.

**Approach 2 — Tool calling (chosen):** AI gets tools (`web_search`, `update_entry`, `ask_user`) and decides which to use. More flexible, truly agentic. The model reasons about what's missing and acts without per-type code.

**Approach 3 — Multi-agent with separate enrichment workers:** Dedicated agents per content type. Overkill for 10-30 entries/day.

**Why tool calling:** It's the right abstraction for "look at this entry and decide what would make it better." The model handles contacts, articles, ideas, and novel content types without per-type code. Adding new tools later (e.g., `check_duplicates`, `link_related_entries`) is natural.

### AI Summary generation

**Option A — Same AI call, bigger output (chosen):** Add an `ai_summary` field to the existing JSON prompt. The model already has all the content in context. No extra API call.

**Option B — Separate AI call:** Dedicated call for summary generation. Better quality potentially, but costs an extra Groq call per entry.

**Option C — Summary in enrichment only:** Don't generate during initial save; let the enrichment agent produce it. Keeps initial save fast but summary isn't available immediately.

**Why same-call:** The model is already analyzing the content for classification. Adding a summary field is zero-cost. Cap at 300-500 words to stay within token limits. The enrichment agent can update/improve the summary later with information from web searches.

## What we decided

### Core flow

```
User sends message
  → Existing pipeline runs (with AI summary added to JSON output)
  → Notion entry created (with structured page body)
  → Bot replies "✅ Saved as [Title]"
  → asyncio.create_task(enrich_entry(...))
      ↓ (background, user unblocked)
      1. Enrichment agent call (tool-calling LLM)
         - Examines: entry type, metadata, raw content, tags
         - Available tools: web_search, update_entry, ask_user
         - Decides what (if anything) to do
      2. Agent executes tool calls (0 or more)
      3. If anything was enriched → notify user: "✨ Added [description]"
```

### Save first, enrich after (unchanged principle)

The enrichment agent never blocks the save. The user always gets "✅ Saved" immediately. Enrichment happens in the background and the user is notified of what was added. Same pattern already used for file uploads (`asyncio.create_task` → "📎 File attached").

---

## Notion Page Body Structure

Every entry follows this layout:

```
┌──────────────────────────────────────────┐
│  1. AI Summary                           │
│     Interpretive analysis of the content │
│     Updated by enrichment if applicable  │
│                                          │
│  2. Raw Content                          │
│     Scraped article / transcription /    │
│     extracted PDF text / original text   │
│                                          │
│  3. File Attachment                      │
│     Image block or PDF file block        │
│     (if applicable)                      │
│                                          │
│  4. Conversation Log                     │
│     Full exchange between user and bot   │
│     Append-only, always present          │
└──────────────────────────────────────────┘
```

### Section 1: AI Summary

Generated during the initial save as part of the same AI call that produces title, tags, and metadata (added as a new `ai_summary` field in the JSON output). Serves different purposes per content type:

| Input type | What the AI Summary contains |
|---|---|
| Article / URL | Key takeaways, why it matters, what to remember |
| Image | Detailed description of what's in the image (currently page body is empty for images) |
| PDF | What the document covers, key sections, why it was saved |
| Voice note | Cleaned-up, structured version — filler words removed, thought organized |
| Bare idea / text | Structured framing: problem, hypothesis, what's actionable |
| Contact | Who this person is and context on why they're relevant |

The enrichment agent can update this section with additional context from web searches (e.g., contact summary gets company info, book entry gets synopsis).

### Section 2: Raw Content

The full extracted content, unchanged from current behavior:

| Input type | Raw content |
|---|---|
| URL / article | Full scraped content from Jina (markdown) |
| Reddit URL | Post + top comments (JSON API or Jina) |
| Plain text | The original message text |
| Text + URL | Original message text + scraped URL content |
| Image | Empty (base64 excluded per Bug 5 fix) |
| PDF | Extracted text from PyMuPDF |
| Voice note | Whisper transcription |

### Section 3: File Attachment

Image block or PDF file block, uploaded asynchronously (existing behavior). Only present for IMAGE and PDF entries.

### Section 4: Conversation Log

A structured, append-only record of every interaction between the user and the bot for this entry. Always present — even if there's no follow-up, the initial exchange is logged.

Format:
```
--- Conversation ---
Varun: Check out this person I met at YC Demo Day
Second Brain: ✅ Saved as Contact — Sarah Chen
Second Brain: What company is Sarah at?
Varun: Stripe, she's on the ML team
Second Brain: ✨ Updated with company and role info
```

Every bot–user interaction appends to this section:
- Initial save: "Varun: {original message}" + "Second Brain: ✅ Saved as..."
- Enrichment notification: "Second Brain: ✨ Added..."
- Enrichment follow-up: "Second Brain: {question}"
- User CONTEXT reply: "Varun: {reply}"
- DONE acknowledgment: "Second Brain: All saved 👍"

This log serves as training data for making the bot smarter over time, and provides full context when revisiting an entry.

---

## Conversation System Improvements (Universal)

These improvements apply to **all incoming messages**, not just enrichment follow-ups. They fix real problems in the current intent system.

### Problem 1: Sessions never expire

The current `SessionStore` has no timestamp and no TTL. A session from 9am persists until the user explicitly says "done" or sends something classified as NEW. This forces the intent classifier to run on stale sessions.

**Fix — 5-minute auto-expire:** Store a `last_interaction_at` timestamp in the session. On every incoming message, check if the session is older than 5 minutes. If so, clear it silently — the message is treated as NEW without ever hitting the intent classifier.

### Problem 2: Intent classifier has too little context

The current prompt gives the classifier only the entry's `title` and `headline`. It has no awareness of:
- What the bot last said to the user
- How long ago the last interaction was
- The entry's type, tags, or metadata

**Fix — richer classification context:** Pass the classifier:
- Entry title, headline, type, and tags
- The bot's last message (save confirmation, follow-up question, or enrichment notification)
- Time elapsed since last interaction

Updated prompt (conceptual):
```
Previously saved entry:
  Title: {title} | Type: {type} | Tags: {tags}
  Headline: {headline}

Bot's last message to user: "{bot_last_message}"
Time since last interaction: {elapsed}

User's new message: "{message}"

Classify as CONTEXT, DONE, or NEW.
```

This gives the 8B model much better signal for distinguishing "answering the bot's question" from "sending something completely new," even when topics are similar.

### Problem 3: CONTEXT handler doesn't update properties

Currently `update_notion_entry()` just appends `[Update] {raw text}` as a paragraph block. If the user says "She's at Stripe, ML team," the text is appended but metadata, tags, and headline are unchanged. The user ends up doing manual cleanup in Notion.

**Fix — smart CONTEXT processing:** When a message is classified as CONTEXT, re-run it through an AI call that:
1. Receives the existing entry's properties + the new message
2. Produces updated metadata, tags, and headline that incorporate the new information
3. Updates Notion properties in-place AND appends to the conversation log

This means CONTEXT replies actually make entries better, not just longer.

---

## The Enrichment Agent

### Model

`llama-3.3-70b-versatile` on Groq. Strong reasoning, supports tool calling, 1K RPD free tier.

### System prompt (conceptual)

> You are an enrichment agent for a personal knowledge base. You just received a saved entry. Examine it and decide: is there missing context you could find via web search? Are there metadata fields that should be filled in? Is there one specific question worth asking the user?
>
> Be selective. Not every entry needs enrichment. A fully-formed article with good tags needs nothing. A contact with no company info needs a search. A bare idea might benefit from one follow-up question.
>
> Use your tools or do nothing if the entry is already complete.

### Tools

| Tool | Signature | Purpose |
|---|---|---|
| `web_search` | `(query: str) → list[{title, url, snippet}]` | Brave Search API. Use when external information would fill gaps. |
| `update_entry` | `(fields: dict) → success` | Update Notion entry properties and/or AI summary. |
| `ask_user` | `(question: str) → void` | Send a follow-up question via Telegram. Only when something important is missing that search can't resolve. |

### Search provider: Brave Search API

- **Free tier:** 2,000 queries/month
- **Why Brave:** Most generous free tier, simple REST API, good general web search. No SDK needed — raw `httpx` calls.
- **Budget management:** No hard cap in code. The agent prompt is guided to be selective. A daily counter tracks usage. If daily searches exceed ~50, the agent prompt gets a note: "search budget is low today — only search if high value." Graceful degradation instead of a hard wall.
- **Expected usage:** At 10-30 entries/day, maybe 30-50% trigger a search → 5-15 searches/day → 150-450/month, well within 2K.

### Notion updates: pure in-place

Enrichment updates the existing entry directly:
- **Properties:** Metadata JSON, tags, headline — all updated in-place. The initial save's values are AI-generated anyway; enrichment just produces a better version.
- **AI Summary:** Updated with additional context from web searches or analysis.
- **No "enrichment" markers or dividers.** This is a personal knowledge base — one clean entry is better than an audit trail.
- **Ground truth preserved:** `Original Message` field always contains exactly what the user sent. The conversation log in the page body captures the full exchange.

### Follow-up questions: smart, not forced

The agent asks a follow-up only when:
1. Something clearly important is missing (contact with no company, idea with no next step)
2. The missing info can't be resolved via search
3. The question is specific and actionable ("What company is Sarah at?" not "Want to add more details?")

Follow-up messages are sent as natural Telegram messages — no special prefix or branding.

### Enrichment is independent of conversation handling

The enrichment pipeline and the conversation system are completely decoupled:

- **Enrichment** runs in the background via `asyncio.create_task()`. It doesn't know or care what the user is doing. It updates Notion, sends notifications, and optionally asks a follow-up.
- **Conversation handling** processes incoming messages. It uses the improved session system (auto-expire, smarter intent) to classify and route messages. It doesn't know or care whether enrichment is running.

The only overlap is that both may update the same Notion entry around the same time. Notion handles concurrent block appends (additive, not destructive). Property updates are unlikely to collide in the same second; if they do, last-write-wins is acceptable for a personal tool.

### Per-content-type enrichment expectations

| Content Type | Likely Enrichment | Follow-up? |
|---|---|---|
| Contact / name card | Search person + company, fill metadata | Rarely — search usually covers it |
| Article / URL | Extract key entities, improve tags | No |
| Book / podcast / movie | Fetch synopsis, author, ratings | Maybe: "Read/watched, or on the list?" |
| Bare idea / thought | Analyze for actionability | Maybe: "What's the next step?" or "Related to [project]?" |
| Recipe | Fetch nutritional info, prep time | No |
| Voice note (transcribed) | Re-analyze for entities, action items | Maybe: "You mentioned [name] — want me to look them up?" |
| Image (non-contact) | No search typically. Improve tags. | Rarely |

---

## Rate Limit Budget

At 10-30 entries/day:

| Call type | Per entry | Daily (30 entries) | Groq limit |
|---|---|---|---|
| Initial save (existing, now includes AI summary) | 1 | 30 | 1K RPD (70B) |
| Enrichment agent | 1 | 30 | 1K RPD (70B) |
| CONTEXT re-processing (if user replies) | 0-1 | 0-15 | 1K RPD (70B) |
| Intent classification | 0-1 | 0-30 | 14.4K RPD (8B) |
| **Total 70B calls** | **2-3** | **60-75** | **1K RPD** |

Brave Search: 5-15/day → 150-450/month of 2K monthly limit.

Comfortable headroom across the board.

---

## Constraints and Non-Goals

### Out of scope for this phase
- **Vector embeddings / semantic search** — future phase, separate design
- **Cross-entry linking** ("you saved something related last week") — requires search over existing entries, deferred
- **Multiple follow-up turns** — the agent asks at most one question. Multi-turn enrichment conversations are deferred.
- **Telegram `/find` command** — separate feature, not part of enrichment
- **Deduplication** — separate feature

### Constraints
- **Groq free tier:** 1K RPD on 70B, 14.4K RPD on 8B. Budget is comfortable but not infinite.
- **Brave Search free tier:** 2K queries/month. Soft-capped via prompt guidance + daily counter.
- **Render free tier:** Cold starts already add latency. Background enrichment runs after the response, so it doesn't add user-facing latency — but the Render instance must stay awake long enough to complete enrichment. Edge case: if enrichment takes >15 min of processing (unlikely), Render might sleep mid-task.
- **No persistent state beyond Notion:** The session store is in-memory. If Render restarts mid-enrichment, the background task is lost. Acceptable — the entry is already saved, just not enriched.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│               Conversation System (improved)             │
│                                                         │
│  Incoming message                                       │
│    → Session check (5-min auto-expire)                  │
│    → If session active: intent classification           │
│         (richer context: type, tags, bot's last msg)    │
│         CONTEXT → smart re-processing (update props)    │
│         DONE → clear session                            │
│         NEW → fall through to save pipeline             │
│    → If no session: save pipeline                       │
│                                                         │
│  Save pipeline (enhanced):                              │
│    Telegram → detector → extractor →                    │
│    AI (classify + tag + AI summary in one call) →       │
│    Notion write (structured page body) →                │
│    reply "✅ Saved"                                     │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ asyncio.create_task()
                       ▼
┌─────────────────────────────────────────────────────────┐
│          Enrichment Agent (independent background)       │
│                                                         │
│  Input: entry type, metadata, raw content, tags,        │
│         source URL, AI summary, original message        │
│                                                         │
│  LLM call with tool definitions (Groq tool calling)     │
│         │                                               │
│         ├─→ web_search(query)     → Brave Search API    │
│         ├─→ update_entry(fields)  → Notion API          │
│         ├─→ ask_user(question)    → Telegram Bot API    │
│         └─→ (no action)          → done                 │
│                                                         │
│  Post-execution: notify user if anything was enriched   │
│  All notifications appended to conversation log         │
└─────────────────────────────────────────────────────────┘
```

### New files

| File | Purpose |
|---|---|
| `app/agents/enrichment.py` | Enrichment agent: builds prompt, calls Groq with tools, processes tool calls |
| `app/agents/tools.py` | Tool implementations: `web_search`, `update_entry`, `ask_user` |

### Modified files

| File | Change |
|---|---|
| `app/config.py` | Add `BRAVE_API_KEY` |
| `app/processors/ai.py` | Add `ai_summary` to JSON prompt; structured page body output |
| `app/handlers/message.py` | Fire enrichment task; conversation log appends; smarter CONTEXT handling |
| `app/processors/intent.py` | Richer context in classification prompt (type, tags, bot's last message, elapsed time) |
| `app/session.py` | Add timestamps (`last_interaction_at`), `bot_last_message`; TTL-based auto-expire (5 min) |
| `app/storage/notion.py` | Extend `update_notion_entry()` to support property updates + AI summary updates; add conversation log append function |
| `.env.example` | Add `BRAVE_API_KEY` |
| `requirements.txt` | No new deps (already have `openai` and `httpx`) |

---

## Open Questions (Resolved)

1. **Brave Search free tier signup** — ✅ Resolved. `brave_api_key` is optional; enrichment gracefully skips search if missing. No breaking dependency.
2. **Groq tool calling reliability** — ✅ Resolved. Detailed system prompt with per-type enrichment guidelines and selectivity rules. 67 tests passing. Prompt tuning deferred to live usage.
3. **Render cold start + enrichment timing** — ✅ Accepted. If Render hibernates mid-enrichment, background task is lost. Acceptable — entry is already saved, just not enriched.
4. **Tool call iteration limit** — ✅ Resolved. Sequential with `MAX_TOOL_ROUNDS = 3`. Flexible pattern (search → update), capped to prevent loops.
5. **Existing `update_notion_entry()` scope** — ✅ Resolved. New `update_notion_properties()` function handles property updates. Legacy `update_notion_entry()` kept as fallback for CONTEXT error recovery.
6. **Conversation log format in Notion** — ✅ Resolved. Plain paragraph blocks with "Speaker: message" format. Simple and consistent.

## Implementation Notes (Post-Build)

**AI Summary updates from enrichment:** The design assumed the enrichment agent could update the AI Summary section in the Notion page body. In practice, Notion's block API doesn't support easy in-place updates to specific blocks — only appending new blocks. The enrichment agent can update *properties* (metadata, tags, headline) but not the AI Summary body section. This is acceptable: the initial AI summary is generated from full content context and is already good; enrichment focuses on metadata/tags which are properties. A future improvement could store AI summary as a database property if body updates become important.

**Enrichment notification logic:** Notifications ("✨ Enriched — ...") are only sent when properties are actually updated, not when only a follow-up question is asked. This avoids notification spam — the question itself serves as the user notification.

**Context truncation:** Raw content is truncated to 4000 chars before passing to the enrichment agent (and further to 3000 in the prompt). AI summary is capped at 1000 chars in the enrichment prompt. These limits prevent token explosion while preserving enough context for meaningful enrichment decisions.

**Conversation log for media entries:** For pure image/voice/PDF inputs where `original_message` is None, the conversation section starts with just the heading — the bot's save confirmation is the first appended line. Design assumed all entries have an original message context; this edge case is handled gracefully.
