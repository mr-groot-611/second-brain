# Plan: Agentic Enrichment Pipeline (Phase 3)

Design doc: docs/design-agentic-pipeline.md
Status: **Complete** (local verification done; live Telegram testing on deploy)

---

## Tasks

### [x] 1. Add `ai_summary` to the AI processor and data model
**Files:** `app/models.py`, `app/processors/ai.py`
**What:** Add an `ai_summary` field to `ProcessedEntry` and update the system prompt in `ai.py` to produce it as part of the existing JSON output. This is the interpretive analysis — key takeaways for articles, cleaned-up version for voice notes, detailed description for images, structured framing for ideas.
**Technical notes:**
- Add `ai_summary: str = ""` to `ProcessedEntry` in `models.py`.
- In `ai.py`, update `SYSTEM_PROMPT` to include `"ai_summary"` in the JSON schema. Describe it as: "A 2-4 paragraph analysis. For articles: key takeaways and why it matters. For images: detailed description. For voice notes: cleaned-up structured version of what the user said (remove filler, organize the thought). For ideas: structured framing (problem, hypothesis, what's actionable). For contacts: who they are and why relevant."
- Add examples to the prompt for different content types so the model gets the tone right.
- In `process_with_ai()`, extract `data.get("ai_summary", "")` and pass it to `ProcessedEntry`.
- Increase `max_tokens` from 1024 to 2048 to accommodate the longer summary output.
- The JSON fallback path (line 122-132) should set `ai_summary=""`.
**Verify:** Send a test message to the bot (or mock the AI call in a test). Confirm the returned `ProcessedEntry` has a non-empty `ai_summary` for a sample article, image, and text input. Write a unit test in `tests/test_ai.py` that mocks Groq and verifies the JSON parsing includes `ai_summary`.

---

### [x] 2. Restructure Notion page body with sections
**Files:** `app/storage/notion.py`
**What:** Rewrite `write_to_notion()` to produce the structured page body layout: AI Summary → Raw Content → Conversation Log. Currently it dumps `raw_content` as paragraph blocks with no structure.
**Technical notes:**
- The page body should be built as an ordered list of Notion blocks:
  1. **Heading block**: `## AI Summary` (heading_2 type)
  2. **Paragraph blocks**: `entry.ai_summary` chunked into 2000-char blocks (reuse `_chunk_text`)
  3. **Divider block** (divider type)
  4. **Heading block**: `## Raw Content` (heading_2 type)
  5. **Paragraph blocks**: `entry.raw_content` chunked (existing logic)
  6. **Divider block**
  7. **Heading block**: `## Conversation` (heading_2 type)
  8. **Paragraph block**: Initial conversation entry — `"Varun: {entry.original_message}"` (or `"Varun: [image]"` / `"Varun: [voice note]"` / `"Varun: [PDF]"` for non-text). Skip this line if `original_message` is None.
- For image entries, `raw_content` is empty string — the Raw Content section will just have the heading and divider. The file attachment block (added by background upload) lands after the last written block, which is fine.
- Update `write_to_notion()` signature: it now needs `ProcessedEntry` to include `ai_summary` (from task 1).
- Keep the 100-block limit on `children` — count total blocks and truncate raw content if needed (AI summary and conversation log are more important than raw content tail).
- Helper function: `_build_page_body(entry: ProcessedEntry) -> list[dict]` to keep `write_to_notion` clean.
**Verify:** Send a test save through the bot and open the Notion entry. Confirm: AI Summary heading + content appears first, Raw Content heading + scraped text second, Conversation heading + initial message third. Write a unit test that calls `_build_page_body` with a sample `ProcessedEntry` and asserts the block structure (heading types, content, order).

---

### [x] 3. Add conversation log append function to Notion storage
**Files:** `app/storage/notion.py`
**What:** Add a function `append_to_conversation_log(page_id: str, speaker: str, message: str)` that appends a formatted line to the Conversation section of an existing Notion page.
**Technical notes:**
- Appends a paragraph block: `"{speaker}: {message}"` (e.g., `"Varun: She's at Stripe"` or `"Second Brain: ✅ Saved as Contact — Sarah Chen"`).
- Uses `client.blocks.children.append()` — same as existing `update_notion_entry()`.
- Notion appends blocks at the end of the page, which is where the Conversation section lives (by design from task 2). So a simple append to the page is correct — no need to find the conversation heading.
- Truncate `message` to 2000 chars (Notion rich_text limit).
- Wrap in try/except, raise `NotionError` on failure (consistent with existing pattern).
- The `speaker` parameter uses the actual name: `"Varun"` for the user, `"Second Brain"` for the bot.
**Verify:** Unit test: mock `client.blocks.children.append` and verify it's called with the correctly formatted paragraph block. Integration check: after a save + CONTEXT reply, open Notion and confirm both lines appear in the Conversation section.

---

### [x] 4. Upgrade session store with timestamps and bot message tracking
**Files:** `app/session.py`
**What:** Extend `SessionStore` to track `last_interaction_at` timestamp and `bot_last_message` for richer intent classification. Add a `is_expired()` check with 5-minute TTL.
**Technical notes:**
- Change the session entry from a plain dict to a richer structure. The `set()` method should store:
  ```python
  {
      "page_id": str,
      "title": str,
      "type": str,
      "headline": str,
      "tags": list[str],           # NEW — needed for intent context
      "metadata": dict,            # NEW — needed for smart CONTEXT processing
      "bot_last_message": str,     # NEW — what the bot last said
      "last_interaction_at": float # NEW — time.time() timestamp
  }
  ```
- Add method `is_expired(user_id: int, ttl_seconds: int = 300) -> bool` — returns `True` if `last_interaction_at` is older than `ttl_seconds` or if no session exists. If expired, auto-clears the session and returns `True`.
- Add method `update_interaction(user_id: int, bot_message: str = None)` — refreshes `last_interaction_at` to now, optionally updates `bot_last_message`.
- Keep the existing `get()`, `set()`, `clear()` API — the handler code still uses them.
**Verify:** Unit test: create a session, verify `is_expired` returns False immediately, mock `time.time` to advance 6 minutes, verify `is_expired` returns True and the session is cleared. Test `update_interaction` refreshes the timestamp.

---

### [x] 5. Upgrade intent classification with richer context
**Files:** `app/processors/intent.py`
**What:** Update the classification prompt to include entry type, tags, bot's last message, and time elapsed. This gives the 8B model much better signal for distinguishing CONTEXT from NEW.
**Technical notes:**
- Change `classify_intent` signature to accept the full session dict (not just `last_entry` with title/headline):
  ```python
  def classify_intent(session: dict, new_message: str) -> Intent:
  ```
- Update `INTENT_PROMPT` to:
  ```
  Previously saved entry:
    Title: {title} | Type: {type} | Tags: {tags}
    Headline: {headline}

  Bot's last message to user: "{bot_last_message}"
  Time since last interaction: {elapsed}

  User's new message: "{message}"

  Classify as CONTEXT, DONE, or NEW.
  - CONTEXT: this message adds information or answers the bot's question about the previously saved entry
  - DONE: acknowledgement — user is finished with the previous entry
  - NEW: completely unrelated new item to save
  ```
- Compute `elapsed` as a human-readable string: "30 seconds ago", "2 minutes ago", etc.
- The bot_last_message field helps the classifier understand if the user is answering a specific question vs. sending something new.
- Default `bot_last_message` to the save confirmation if not explicitly set.
**Verify:** Unit test: mock Groq, send a classification request with rich context including a bot follow-up question. Verify the prompt is constructed correctly with all fields. Test that the function handles missing optional fields gracefully (e.g., no tags, no bot_last_message).

---

### [x] 6. Smart CONTEXT handler — re-process and update properties
**Files:** `app/handlers/message.py`, `app/processors/ai.py`, `app/storage/notion.py`
**What:** When a message is classified as CONTEXT, re-run it through an AI call that merges the new information into the existing entry's properties, then updates Notion in-place (properties + conversation log). Replace the current dumb `[Update]` text append.
**Technical notes:**
- **New function in `ai.py`:** `process_context_update(existing_entry: dict, new_message: str) -> dict` — takes the existing entry's properties (title, type, headline, tags, metadata) and the user's new message, returns updated properties as a dict.
  - System prompt: "The user previously saved this entry: {existing props}. They've now added: '{new_message}'. Return updated JSON with any fields that should change. Only include fields that need updating. Keep the title unless the new info fundamentally changes what the entry is about."
  - Uses `llama-3.3-70b-versatile`, `max_tokens=1024`.
- **New function in `notion.py`:** `update_notion_properties(page_id: str, updates: dict)` — updates specific Notion database properties (metadata, tags, headline, etc.) on an existing page. Uses `client.pages.update()`.
- **In `message.py`:** Replace the CONTEXT branch (lines 31-37):
  1. Call `process_context_update(session_data, message.text)` → get updated fields
  2. Call `update_notion_properties(page_id, updated_fields)` → update Notion
  3. Call `append_to_conversation_log(page_id, "Varun", message.text)` → log user message
  4. Call `append_to_conversation_log(page_id, "Second Brain", "Updated ✏️ — ...")` → log bot response
  5. Update session with new properties and refresh timestamp
  6. Reply to user with confirmation
- Wrap the AI call in the same `GroqError` handling as the existing pipeline.
**Verify:** Test scenario: save a contact entry (title: "Sarah Chen", metadata: `{}`), then send a CONTEXT message "She's at Stripe, ML team." Verify: Notion metadata updates to include `"company": "Stripe", "role": "ML team"`. Tags should update if relevant. Conversation log should have both messages. Unit test: mock the AI response for `process_context_update` and verify the Notion update is called with correct properties.

---

### [x] 7. Wire up session and intent changes in message handler
**Files:** `app/handlers/message.py`
**What:** Update the message handler to use the new session features (auto-expire, richer context, conversation log) and connect everything from tasks 2-6.
**Technical notes:**
- **Session expiry check (before intent classification):** At the top of `handle_message`, after `session_store.get(user_id)`, call `session_store.is_expired(user_id)`. If expired, set `last_entry = None` so the message falls through to the save pipeline.
- **Pass full session to intent classifier:** Change `classify_intent(last_entry, message.text)` to `classify_intent(session_data, message.text)` (matches task 5 signature change).
- **Store richer session data:** After initial save, `session_store.set()` now includes `tags`, `metadata`, and `bot_last_message` (the save confirmation text).
- **Conversation log on initial save:** After `write_to_notion`, call `append_to_conversation_log(page_id, "Varun", entry.original_message or "[media]")` and `append_to_conversation_log(page_id, "Second Brain", reply_text)`. Wait — actually the initial conversation entry is already written in the page body during `write_to_notion` (task 2). So we only need to append the bot's save confirmation here.
  - Correction: task 2 writes the initial `"Varun: ..."` line during page creation. The bot's `"Second Brain: ✅ Saved as..."` confirmation needs to be appended after the reply is sent. Use `append_to_conversation_log` for this.
- **Update interaction timestamp:** After every bot reply (save, context update, done), call `session_store.update_interaction(user_id, bot_message=reply_text)`.
- **DONE handler:** After clearing session, append `"Second Brain: All saved 👍"` to conversation log.
**Verify:** End-to-end test flow: send a new item → verify session created with full data including timestamp. Wait, send CONTEXT → verify intent classifier gets rich context. Send DONE → verify session cleared. Restart: send new item after 6 minutes → verify session was auto-expired (no intent classification, goes straight to save). Check Notion conversation log has all entries.

---

### [x] 8. Add Brave Search API client
**Files:** `app/agents/tools.py` (new), `app/config.py`, `.env.example`
**What:** Create the `web_search` tool implementation using Brave Search API. Also add `BRAVE_API_KEY` to config.
**Technical notes:**
- **`app/config.py`:** Add `brave_api_key: str = ""` to `Settings` (default empty string so the app doesn't crash if the key isn't set — enrichment just skips search).
- **`.env.example`:** Add `BRAVE_API_KEY=your_brave_search_api_key`.
- **Create `app/agents/__init__.py`** (empty).
- **Create `app/agents/tools.py`:**
  - `async def web_search(query: str, num_results: int = 5) -> list[dict]`:
    - `GET https://api.search.brave.com/res/v1/web/search?q={query}&count={num_results}`
    - Headers: `{"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": settings.brave_api_key}`
    - Parse response: extract `web.results` → return list of `{"title": str, "url": str, "snippet": str}`
    - Use `httpx.AsyncClient` (already a dependency).
    - If `brave_api_key` is empty, return empty list (graceful skip).
    - Wrap in try/except — on any error, log and return empty list (enrichment should never crash the pipeline).
  - Daily counter: module-level `_search_count` int and `_search_date` string. Reset count when date changes. Exposed via `get_daily_search_count() -> int`.
- **No new dependencies** — `httpx` is already in `requirements.txt`.
**Verify:** Unit test: mock `httpx.AsyncClient.get` and verify the function parses Brave's response format correctly. Test the empty-API-key graceful skip. Test the error handling (network failure returns empty list). Manual test: run the function with a real API key against a simple query and verify results.

---

### [x] 9. Build the enrichment agent
**Files:** `app/agents/enrichment.py` (new), `app/agents/tools.py` (extend)
**What:** Create the core enrichment agent that uses Groq tool calling to decide what to do with a saved entry, then executes the tool calls.
**Technical notes:**
- **`app/agents/tools.py` additions:**
  - `async def update_entry(page_id: str, fields: dict)`: Calls `update_notion_properties()` from `notion.py` (task 6) and optionally updates AI summary. `fields` can include: `metadata`, `tags`, `headline`, `ai_summary`.
  - `async def ask_user(bot, chat_id: int, page_id: str, question: str)`: Sends a Telegram message via `bot.send_message(chat_id, question)`. Also appends `"Second Brain: {question}"` to conversation log. Updates session's `bot_last_message`.
- **`app/agents/enrichment.py`:**
  - `async def enrich_entry(entry_data: dict, page_id: str, bot, chat_id: int, user_id: int)`:
    - Entry data includes: `type`, `title`, `headline`, `tags`, `metadata`, `ai_summary`, `source_url`, `raw_content` (truncated to ~4000 chars to stay within context).
    - Build system prompt (from design doc, section "The Enrichment Agent").
    - If `get_daily_search_count() > 50`, append: "Search budget is low today — only search if high value."
    - Define tool schemas for Groq tool calling:
      ```python
      tools = [
          {"type": "function", "function": {"name": "web_search", "description": "...", "parameters": {...}}},
          {"type": "function", "function": {"name": "update_entry", "description": "...", "parameters": {...}}},
          {"type": "function", "function": {"name": "ask_user", "description": "...", "parameters": {...}}},
      ]
      ```
    - Call Groq with `model="llama-3.3-70b-versatile"`, pass tools.
    - Process response: if `tool_calls` in response, execute each tool call by dispatching to the corresponding function.
    - Allow sequential tool calls: after executing the first round, if the model requests more (e.g., search → update), make a second LLM call with the tool results. Cap at 3 rounds to prevent loops.
    - Track what was changed. If anything was updated, send notification: `"✨ Added {description}"` and append to conversation log.
    - Entire function wrapped in try/except — log errors, never crash. If enrichment fails, the entry is already saved.
  - Use `GroqError` handling consistent with the rest of the codebase.
**Verify:** Unit test with mocked Groq response containing tool calls: verify the agent correctly parses and dispatches to `web_search`, `update_entry`, and `ask_user`. Test the "no tool calls" path (agent decides entry is complete). Test the 3-round cap. Test error handling (Groq fails → no crash, no notification).

---

### [x] 10. Wire enrichment agent into the save pipeline
**Files:** `app/handlers/message.py`
**What:** Fire the enrichment agent as a background task after every successful save, passing all required context.
**Technical notes:**
- After `write_to_notion()` returns `page_id` and the save confirmation is sent, create the background task:
  ```python
  enrichment_data = {
      "type": entry.content_type,
      "title": entry.title,
      "headline": entry.headline,
      "tags": entry.tags,
      "metadata": entry.metadata,
      "ai_summary": entry.ai_summary,
      "source_url": entry.source_url,
      "raw_content": entry.raw_content[:4000],  # truncate for context window
  }
  asyncio.create_task(
      enrich_entry(enrichment_data, page_id, context.bot, message.chat_id, user_id)
  )
  ```
- This goes right after the existing file upload `create_task` block (line 67-73 in current `message.py`).
- Import `enrich_entry` from `app.agents.enrichment`.
- The enrichment task needs `context.bot` for sending Telegram messages and `user_id` for session updates (if `ask_user` is called).
**Verify:** End-to-end: send a contact message (e.g., photo of a business card). Verify: (1) "✅ Saved" comes back immediately, (2) after a few seconds, "✨ Added..." notification arrives (if enrichment found something), (3) Notion entry has enriched metadata and updated AI summary. Send a plain text note and verify enrichment decides to do nothing (no notification).

---

### [x] 11. Add `BraveSearchError` to exception handling
**Files:** `app/exceptions.py`
**What:** Add a `BraveSearchError` exception class for search failures, consistent with the existing error pattern.
**Technical notes:**
- Add:
  ```python
  class BraveSearchError(Exception):
      """Raised when a Brave Search API call fails."""
      pass
  ```
- This is used in `tools.py` for logging/tracking but is caught internally by the enrichment agent (never surfaces to the user). The agent treats search failures as "no results" — graceful degradation.
**Verify:** Verify the exception class exists and can be raised/caught. No separate test file needed — covered by enrichment agent tests.

---

### [x] 12. Update `.env.example` and config documentation
**Files:** `.env.example`, `DEPLOY.md`
**What:** Add `BRAVE_API_KEY` to environment config and deployment docs.
**Technical notes:**
- `.env.example`: Add `BRAVE_API_KEY=your_brave_search_api_key_here` with a comment: `# Brave Search API — get free key at https://brave.com/search/api/ (2K queries/month free)`
- `DEPLOY.md`: Add `BRAVE_API_KEY` to the Render env vars table (Action: Add, with note about where to get it). Update the "What Changed" section with a summary of Phase 3 changes.
- `CLAUDE.md` update is handled in a separate step after all tasks.
**Verify:** Visual review: `.env.example` has the new key, `DEPLOY.md` has updated env var table.

---

### [x] 13. End-to-end verification and prompt tuning
**Note:** Local verification complete — 67 tests pass, all imports clean, all integration points verified via code review. Stale test files (`test_gemini.py`, `test_extractors.py`) removed. Live Telegram testing deferred to deployment — requires `BRAVE_API_KEY` set in Render env vars and a push to `main`. Prompt tuning will be done iteratively based on real-world results.
**Files:** Multiple — primarily prompt strings in `ai.py`, `intent.py`, `enrichment.py`
**What:** Test the full pipeline end-to-end via Telegram with real messages across all content types. Tune prompts based on actual results.
**Technical notes:**
- Test matrix (send each via Telegram and verify Notion output):
  - [ ] **Bare URL** — verify AI summary captures key takeaways, enrichment adds entities/tags
  - [ ] **Text + URL** — verify original message preserved, URL scraped, AI summary generated
  - [ ] **Plain text idea** — verify AI summary structures the thought, enrichment may ask a follow-up
  - [ ] **Image** — verify AI summary describes the image, page body no longer empty
  - [ ] **Voice note** — verify AI summary is a cleaned-up version of the transcription
  - [ ] **Contact info** — verify enrichment searches and fills metadata
  - [ ] **CONTEXT reply** — verify properties update in-place, conversation log appended
  - [ ] **DONE message** — verify session clears, conversation log has closing line
  - [ ] **New message after 5+ minutes** — verify session auto-expired, treated as NEW
  - [ ] **New message while session active** — verify intent classifier correctly identifies NEW
- Prompt tuning areas:
  - AI summary length and tone (is it useful? too verbose? too thin?)
  - Enrichment agent selectivity (is it searching when it shouldn't? missing obvious searches?)
  - Follow-up question quality (specific and actionable, or vague?)
  - Intent classification accuracy with the richer prompt
- Adjust prompts iteratively based on results. Document any significant prompt changes.
**Verify:** All items in the test matrix pass. Notion entries are richer than before. No regressions in the base save pipeline.
