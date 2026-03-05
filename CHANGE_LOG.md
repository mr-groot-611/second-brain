# Change Log
> Rewritten each session. Claude Code should apply all changes listed here that haven't been deployed yet.
> Last updated: March 2026 (Session 3 — video note bug identified)

---

## Session 3 — Video Note Handling (pending decision)

### Status: Not yet implemented

**Bug found:** Telegram video notes (`message.video_note` — the round circular video format) are not handled by the bot. They fall through silently: no response to the user, nothing saved to Notion.

**Root cause:** `detector.py` only checks `message.voice` for voice/audio input. `message.video_note` is a separate Telegram message type and is never matched.

**Decision pending:** Two options:
1. **Graceful rejection** — reply "🎥 Video notes aren't supported — please send a regular voice message" (simple, ~5 lines)
2. **Full transcription support** — download video note, extract audio, pass to Whisper (requires `ffmpeg` on Render)

**Files to change (if option 1 — recommended):**
- `app/extractors/detector.py` — add `InputType.UNSUPPORTED` or check `message.video_note` explicitly
- `app/handlers/message.py` — handle the unrecognised type and reply with helpful message

---

## Session 2 — Post-Deployment Bug Fixes & Error Handling

### Status: Deployed ✅

---

### New file: `app/exceptions.py`
**Created from scratch.**
Three custom exception classes used across the pipeline:
```python
class GroqError(Exception):
    def __init__(self, message: str = "", is_rate_limit: bool = False): ...

class NotionError(Exception): ...

class TelegramFileError(Exception): ...
```

---

### `app/processors/ai.py`
**Three changes:**

1. **System prompt rewritten** — Title is now a "filing label (3-6 words), NOT a news headline". Headline must answer "WHY did I save this — not restate the title". Added bad/good examples for both fields.

2. **Base64 fix** — `raw_content` is now `""` for IMAGE entries so the base64 blob is never written to the Notion page body:
```python
page_raw_content = "" if raw.input_type == InputType.IMAGE else raw.content
```

3. **GroqError wrapping** — Groq API calls now caught and re-raised as `GroqError`:
```python
except RateLimitError as e:
    raise GroqError("rate limit", is_rate_limit=True) from e
except APIError as e:
    raise GroqError(str(e)) from e
```

---

### `app/processors/intent.py`
**GroqError wrapping** — Same pattern as `ai.py`: `RateLimitError` → `GroqError(is_rate_limit=True)`, `APIError` → `GroqError`.

---

### `app/extractors/pdf.py`
**Error handling added** — `extract_pdf()` now wrapped in try/except:
- Detects `doc.is_encrypted` → returns human-readable placeholder string
- Any other exception → logs and returns `""`
- Never throws; always returns a string

---

### `app/storage/notion.py`
**NotionError wrapping** — Both `write_to_notion()` and `update_notion_entry()` now catch `APIResponseError` and re-raise as `NotionError`.

---

### `app/handlers/message.py`
**Three changes:**

1. **PDF empty-content warning** — After extraction, if `raw.content == ""` and `input_type == PDF`, sends a ⚠️ warning to the user (mirrors the existing URL warning).

2. **Session cleared on failure** — `session_store.clear(user_id)` now called in every exception branch. Prevents the "stuck session" bug where a failed save left a stale session that caused cascading failures on the next message.

3. **Specific error handlers** — Replaced single generic `except Exception` with four specific handlers:
   - `GroqError` (rate limit) → tells user to wait a minute, shows free tier limits
   - `GroqError` (other) → tells user it's a temporary Groq issue
   - `NotionError` → tells user to check Render env vars
   - `TelegramFileError` → tells user to resend the file
   - `Exception` (fallback) → generic message + suggestion to check Render logs

---

## Session 2 — File Upload Feature

### Status: Deployed ✅

**Decision summary:**
- Files (images, PDFs) will be uploaded directly to Notion using the Notion File Upload API — no external hosting needed
- Voice notes: skip file upload entirely — the transcription is the value
- Files are embedded as **blocks in the page body** (image block for images, file block for PDFs), NOT as a database property — the Notion Files & Media property type doesn't support file_upload IDs via API
- The `File` database property has been dropped from the Notion schema (done via MCP already)
- Voice transcripts stored in `Original Message` is correct and consistent — no exception needed

**Flow (agreed):**
1. User sends file → normal pipeline runs → Notion entry created → "✅ Saved as..." sent immediately
2. `asyncio.create_task()` fires background coroutine (user unblocked)
3. Background: upload file bytes to Notion → append image/file block to page → send "📎 File attached to your entry."
4. On upload failure: "⚠️ Entry saved but couldn't attach the file."

**Notion File Upload API (3 steps for files < 20MB):**
```
POST /v1/file_uploads                          → get upload ID
POST /v1/file_uploads/{id}/send                → multipart/form-data with file bytes
PATCH /v1/blocks/{page_id}/children            → append image or file block
```
Block format for image:
```json
{"type": "image", "image": {"type": "file_upload", "file_upload": {"id": "<upload_id>"}}}
```
Block format for PDF:
```json
{"type": "file", "file": {"type": "file_upload", "file_upload": {"id": "<upload_id>"}, "caption": []}}
```

**Files to create/modify:**
1. `app/models.py` — add `file_bytes: Optional[bytes] = None` and `file_mime_type: Optional[str] = None` to `RawInput`
2. `app/handlers/message.py` — store raw bytes in `RawInput` for IMAGE and PDF; fire `asyncio.create_task(_upload_file_background(...))` after `write_to_notion`; add `_upload_file_background` async function
3. `app/storage/notion.py` — add `upload_and_attach_file(page_id, file_bytes, file_name, mime_type)` async function using `httpx.AsyncClient`

**Constraints:**
- Free Notion tier: 5 MiB per file (images and PDFs are well within this)
- `notion-client` Python library doesn't wrap file upload — use raw `httpx` calls
- Notion-Version header: `2022-06-28` (standard)

---

## Session 1 — Groq Migration + Schema Redesign

### Status: Deployed ✅

**Summary of what was done:**
- Migrated all AI calls from Gemini (`google-generativeai`) to Groq (OpenAI SDK pointed at `https://api.groq.com/openai/v1`)
- Rewrote Notion schema from 25 rigid columns to 10 flexible fields + JSON metadata blob
- Fixed 4 bugs: URL detection (entities), URL extraction (Jina AI Reader), source_url for TEXT+URL messages, silent empty saves
- Created `app/processors/ai.py` (replaces `gemini.py`)
- Updated `app/extractors/voice.py` (Groq Whisper)
- Updated `app/processors/intent.py` (Groq llama-3.1-8b-instant)
- Updated `app/storage/notion.py` (new 10-field schema)
- Updated `app/extractors/detector.py` (Telegram entity-based URL detection)
- Updated `app/extractors/url.py` (Jina AI Reader + Reddit JSON fallback)
- Updated `app/models.py` (added `original_message`, renamed `summary` → `headline`)
- Updated `app/config.py` (`groq_api_key` replaces `gemini_api_key`)
- Updated `requirements.txt` (added `openai`, removed `google-generativeai`, `trafilatura`)
- Updated `.env.example`
- Migrated Notion database schema via MCP (dropped 24 old columns, added 5 new ones)

**Pending from Session 1 (still to do):**
- ~~Delete `app/processors/gemini.py`~~ — ✅ already deleted by Claude Code
- Update test suite (33 tests reference old schema/Gemini)
- Create `scripts/test_groq.py` to replace `scripts/test_gemini.py`
