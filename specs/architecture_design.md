# Architecture Specification: GridShelf AI

## 1. Context and Business Logic (Strict Frontend-Driven Architecture)

The system consists of two explicit layers: a **React frontend application** and a **headless AI agent pipeline**. The relationship between them is strictly deterministic: **the AI agent never initiates any workflows independently; every single agent scenario is explicitly and unambiguously triggered by a direct user action on the frontend.**

### 1.1 Frontend Application (React UI)
* **Visual Style (Skeuomorphic UI):** The interface simulates a realistic, physical library. Books are rendered as interactive 3D/2D spines arranged on bookshelves, providing an immersive, tactile experience rather than a standard flat dashboard.
* **Core UI Triggers:** The React frontend serves as the sole orchestrator of the pipeline via three distinct user-initiated entry points:
  1. **Photo Upload Trigger:** Activated when the user clicks the camera/upload button to capture or upload a physical book cover.
  2. **Contextual Search Trigger:** Activated when the user submits a discovery prompt or requests automated recommendations based on their shelf context.
  3. **Manual Entry Mode (Bypass):** A purely client-side form where the user types details manually. This workflow completely bypasses the AI pipeline to optimize resource usage and eliminate token costs.
* **Human-in-the-Loop (HITL) Validation:** For all AI-assisted entry paths, the agent **never** writes directly to the database. It constructs a structured data "Draft" and returns it to the React UI. The user reviews, edits, and explicitly clicks a frontend "Confirm Save" button to execute the final database insertion.

### 1.2 Backend & Agent Pipeline
The backend operates purely as a reactive, headless execution environment. It exposes a dedicated REST endpoint per AI skill (`POST /api/process-book-photo`, `POST /api/search-books`, `POST /api/recommend-books`), each internally building the right prompt for the ADK workflow and invoking it. Integration with the relational database and the Google Books API is managed via Server-Sent Events (SSE) through dedicated, custom MCP servers. Book writes (`POST /api/books`) go through the `library-db-mcp` `save_book` tool via a direct MCP client call (`call_db_mcp_tool` in `app/fast_api_app.py`), not raw SQL in the backend process.

### 1.3 Security & Authentication (Strict Gating & Least Privilege)
* **System Login:** Google Sign-In (Google Identity Services on the frontend, `google-auth`'s `id_token.verify_oauth2_token` on the backend). The backend issues a signed session cookie (`starlette.middleware.sessions.SessionMiddleware` + `itsdangerous`) after verifying the Google ID token; every data endpoint requires this session (`require_session_user_id` in `app/fast_api_app.py`) instead of trusting a client-supplied `user_id`. The verified Google `sub` claim is the canonical user id, mapped to a stable UUID the same way the rest of the system already maps arbitrary user-id strings (`uuid.uuid5(NAMESPACE_DNS, sub)`).
* **User ID Isolation:** The LLM agent **never** handles or passes the `User ID`. The backend infrastructure securely injects the validated user identifier directly into the headers of the database MCP requests (`X-User-ID`, see `library_db_header_provider` in `app/agent.py`).
* **Database Access Restriction:** The agent has zero raw SQL capabilities. The `library-db-mcp` is intentionally restricted to expose **exactly two specialized tools** (one for reading, one for writing), adhering strictly to the principle of least privilege. Both the agent (`get_user_library`) and the backend's own `/api/books` endpoint (`save_book`, via `call_db_mcp_tool`) go through this MCP layer rather than issuing raw SQL of their own.
* **Usage Limits (Structural Gating via Policy Server):** Enforced server-side in `app/fast_api_app.py` (`check_and_record_usage`) before the LLM is ever invoked, backed by a `usage_log` table (bootstrapped idempotently at startup, see `ensure_schema`):
  * Photo Upload Pipeline (`process-book-photo`): Max 3 requests/day, 10 requests/month per user.
  * Internet Book Search (Google Books API via `search-books`): Max 3 requests/day per user.
  * Recommendation Pipeline (`recommend-books`): Max 5 requests/day per user.
  * *Manual form submissions do not call the LLM and are completely unlimited.*

## 2. Tech Stack and Target Versions

* **Frontend:** React 19 (`frontend/package.json` pins `^19.2.7`), Tailwind CSS (for custom wooden/minimalist shelf textures), Framer Motion (for realistic book-pulling and shelf-sorting animations).
* **Backend / Agent Framework:** Python 3.12, `google-adk[gcp,mcp]` (`>=2.0.0,<3.0.0`) as the runtime agent/workflow framework. `agents-cli` (`google-agents-cli`) is a separate developer CLI used for scaffolding/eval/deploy, not the runtime library. Structured output validation is done via plain `pydantic.BaseModel` + ADK's `output_schema`; `pydantic-ai` is listed in `pyproject.toml` but is not imported or used anywhere in the current code.
* **Environment:** GCP Cloud Run.
* **Database:** GCP Cloud SQL for PostgreSQL (Version 15) managed via custom `library-db-mcp` for writes; the backend still reads directly via `asyncpg` for the UI's `GET /api/library` (a read has no least-privilege concern the way a write does).
* **External APIs:** Google Books API (encapsulated within the custom search MCP, authenticated via `GOOGLE_BOOKS_API_KEY`).
* **LLM Orchestration:**
  * **`gemini-3.1-pro-preview`:** Dedicated entirely to the high-overhead OCR extraction within the photo processing pipeline (`ocr_agent` in `app/agent.py`).
  * **`gemini-3.5-flash`:** Used by `recommend_agent` (shelf-only "what to read next" reasoning) and `search_agent` (turning free-form queries into Google Books search keywords and filtering out non-book results like anthologies/catalogs/criticism).

## 3. Use Cases & BDD Scenarios (Unambiguous UI Invocations)

### Instruction for Antigravity:
> **Generate at least 3 JSON evaluation cases for each skill BEFORE writing execution logic. All flows must map perfectly to the React UI trigger events.**

### Scenario A: Photo Upload Pipeline (`process-book-photo`)
* **Frontend Trigger Event:** User clicks the "Scan Cover" button and uploads an image.
* **Execution Flow:** React UI transmits `image_bytes` -> Backend Policy Server verifies daily quota -> Agent (Gemini 3.1 Pro) parses cover via OCR -> Calls `web-search-mcp` (Google Books API) to fetch missing metadata -> **Agent returns a structured Draft JSON to the UI** -> React UIpopulates an editable form -> User adjusts fields -> User clicks frontend "Save to Shelf" button -> React API updates the database.
* **Edge Case (OCR Failure):** If the image is unreadable, the agent returns a Draft JSON with `status: manual_input_required`. The React UI immediately presents the standard form with empty fields, allowing the user to type the info manually.

### Scenario B: Manual Entry (Frontend Only)
* **Frontend Trigger Event:** User clicks the "Add Manually" button on the empty shelf slot.
* **Execution Flow:** React UI bypasses the AI pipeline entirely -> Displays an empty metadata form -> User enters data -> User clicks "Confirm" -> React frontend sends a direct REST request to the backend API to save the entry via the DB layer. No LLM tokens are consumed.

### Scenario C: Contextual Internet Search (`search-books`)
* **Frontend Trigger Event:** User enters a custom text prompt into the discovery bar (e.g., "Hard sci-fi from the 1970s") or clicks the "Surprise Me" button on an empty bookshelf.
* **Execution Flow:** React UI calls `POST /api/search-books` -> Backend checks the 3 requests/day search limit (`usage_log`) -> Agent calls `get_user_library` to understand existing items -> Agent builds a `library_summary` from the real genres/titles on the shelf -> `search_agent` (Gemini Flash) turns the free-form query into good Google Books search keywords, may call `find_books_by_context` more than once with different phrasings, and filters the raw results down to real, readable books (dropping anthologies, academic essay collections, criticism, and catalogs) -> Returns the curated list to the UI.
* **Fallback Logic Rules:**
  1. *Library is empty/new user:* The search filters rely strictly on the text prompt provided by the user.
  2. *No text prompt provided:* The search functions in "Discovery Mode", evaluating the `library_summary` to fetch missing books from the Google Books API.
  3. *Both prompt and library are empty:* The pipeline short-circuits instantly and returns `status: missing_context` without executing external queries.

### Scenario D: Personalized Recommendations (`recommend-books`)
* **Frontend Trigger Event:** User clicks the "What to Read Next?" button, optionally after typing a preference (e.g., "dark fantasy") into the discovery bar.
* **Execution Flow:** React UI calls `POST /api/recommend-books` -> Backend checks the 5 requests/day limit -> Agent queries the user's collection via `get_user_library` and narrows it to books not marked `read` -> **This is shelf-only**: `recommend_agent` (Gemini Flash) picks exclusively from the user's own unread/in-progress books, it never fetches new books from the internet -> If a preference was given, the agent judges it semantically (language/synonyms/mood) against each shelf book's genre/description/title, and returns an **empty list on purpose** if nothing genuinely fits (surfaced to the user as "no match", not silently substituted with the whole shelf) -> If no preference was given, the agent infers taste from the user's already-`read` books and favors similar unread ones; if nothing has been read yet either, the backend picks a random unread book instead of calling the LLM -> Frontend maps returned titles back to shelf book IDs and highlights them on the physical shelf.

## 4. Database Schema & Custom Tools

```yaml
database:
  engine: "Cloud SQL PostgreSQL 15"
  tables:
    users:
      columns:
        id: { type: "UUID", primary_key: true }
        external_id: { type: "VARCHAR(255)", unique: true, description: "Verified Google `sub` claim" }
        email: { type: "VARCHAR(255)" }
        created_at: { type: "TIMESTAMP" }
    books:
      columns:
        id: { type: "UUID", primary_key: true }
        title: { type: "VARCHAR(255)" }
        author: { type: "VARCHAR(255)" }
        genre: { type: "VARCHAR(100)" }
        description: { type: "TEXT" }
    user_library:
      columns:
        id: { type: "UUID", primary_key: true }
        user_id: { type: "UUID", foreign_key: "users.id" }
        book_id: { type: "UUID", foreign_key: "books.id" }
        status: { type: "VARCHAR(50)" }
        added_at: { type: "TIMESTAMP" }
    usage_log:
      columns:
        id: { type: "UUID", primary_key: true }
        user_id: { type: "UUID" }
        skill: { type: "VARCHAR(50)", description: "process-book-photo | search-books | recommend-books" }
        created_at: { type: "TIMESTAMP" }
```
`users` and `usage_log` are bootstrapped idempotently (`CREATE TABLE IF NOT EXISTS`) at backend startup by `ensure_schema()` in `app/fast_api_app.py`, rather than through a separate migration tool.

### Exported Tools from `library-db-mcp` (Strictly Restricted):
This server enforces absolute boundary control. It exposes **exactly two explicit business-logic functions**. The agent has no access to deletion mechanisms, drop commands, or user table modification parameters.
1. `save_book(title, author, genre, description, status)` — Writes or updates book metadata and reading status, and links it to the user. Called both by the agent's photo-enrichment flow context and directly by the backend's `POST /api/books` endpoint (via a raw MCP client call, not through an agent run).
2. `get_user_library()` — Reads and structures the authenticated user's book collection data.

### Exported Tools from `web-search-mcp`:
1. `find_books_by_context(user_prompt: str, library_summary: str)` — Interacts securely with the external Google Books API using the restricted project API Key.

## 5. Resource Configuration (YAML Manifest)

```yaml
manifest_version: "1.0"
name: gridshelf-ai
version: "1.0.0"
runtime: python312

resources:
  mcp_servers:
    - id: web-search-mcp
      type: mcp
      description: "Custom MCP wrapping the Google Books API. Exposes ONLY find_books_by_context tool."
      endpoint: "https://custom-search-mcp-service.a.run.app/sse"
      auth:
        secret_ref: GCP_SECRET_MANAGER_SEARCH_TOKEN
    - id: library-db-mcp
      type: mcp
      description: "Custom DB MCP. Exposes EXACTLY TWO tools: save_book and get_user_library. Expects User ID in request headers."
      endpoint: "https://gcp-postgres-mcp-service.a.run.app/sse"
      auth:
        secret_ref: GCP_SECRET_MANAGER_DB_TOKEN

skills:
  - id: process-book-photo
    description: "OCR pipeline initiated by Frontend upload. Returns draft data for React UI review. DOES NOT SAVE TO DB."
    input:
      type: object
      properties:
        image_bytes: { type: string, format: byte }
    output:
      type: object
      properties:
        status: { type: string, enum: ["success", "manual_input_required", "quota_exceeded"] }
        draft_data:
          type: object
          properties:
            title: { type: string, nullable: true }
            author: { type: string, nullable: true }
            genre: { type: string, nullable: true }
            description: { type: string, nullable: true }

  - id: search-books
    description: "Searches Google Books API based strictly on explicit Frontend triggers (Prompt or Discovery)."
    input:
      type: object
      properties:
        user_prompt: { type: string, nullable: true }
    output:
      type: object
      properties:
        status: { type: string, enum: ["success", "missing_context", "quota_exceeded"] }
        items:
          type: array
          items:
            type: object

  - id: recommend-books
    description: "Generates reading recommendations from existing database shelf, triggered by UI click."
    input:
      type: object 
    output:
      type: object
      properties:
        status: { type: string, enum: ["success", "empty_library", "quota_exceeded"] }
        items:
          type: array
          items:
            type: object
```