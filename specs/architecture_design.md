# Architecture Specification: GridShelf AI

## 1. Context and Business Logic (Strict Frontend-Driven Architecture)

The system consists of two explicit layers: a **React frontend application** and a **headless AI agent pipeline**. The relationship between them is strictly deterministic: **the AI agent never initiates any workflows independently; every single agent scenario is explicitly and unambiguously triggered by a direct user action on the frontend.**

### 1.1 Frontend Application (React UI)
* **Visual Style (Skeuomorphic UI):** The interface simulates a realistic, physical library. Books are rendered as interactive 3D/2D spines arranged on bookshelves, providing an immersive, tactile experience rather than a standard flat dashboard.
* **Core Core UI Triggers:** The React frontend serves as the sole orchestrator of the pipeline via three distinct user-initiated entry points:
  1. **Photo Upload Trigger:** Activated when the user clicks the camera/upload button to capture or upload a physical book cover.
  2. **Contextual Search Trigger:** Activated when the user submits a discovery prompt or requests automated recommendations based on their shelf context.
  3. **Manual Entry Mode (Bypass):** A purely client-side form where the user types details manually. This workflow completely bypasses the AI pipeline to optimize resource usage and eliminate token costs.
* **Human-in-the-Loop (HITL) Validation:** For all AI-assisted entry paths, the agent **never** writes directly to the database. It constructs a structured data "Draft" and returns it to the React UI. The user reviews, edits, and explicitly clicks a frontend "Confirm Save" button to execute the final database insertion.

### 1.2 Backend & Agent Pipeline
The backend operates purely as a reactive, headless execution environment. It exposes strictly defined endpoints that map 1:1 to the frontend triggers. Integration with the relational database and the Google Books API is managed via Server-Sent Events (SSE) through dedicated, custom MCP servers.

### 1.3 Security & Authentication (Strict Gating & Least Privilege)
* **System Login:** Authenticated exclusively via Google Auth.
* **User ID Isolation:** The LLM agent **never** handles or passes the `User ID`. The backend infrastructure securely injects the validated user identifier directly into the headers of the database MCP requests.
* **Database Access Restriction:** The agent has zero raw SQL capabilities. The `library-db-mcp` is intentionally restricted to expose **exactly two specialized tools** (one for reading, one for writing), adhering strictly to the principle of least privilege.
* **Usage Limits (Structural Gating via Policy Server):**
  To prevent infrastructure abuse, the backend Policy Server intercepts requests *before* invoking the LLM:
  * Photo Upload Pipeline (`process-book-photo`): Max 3 requests/day, 10 requests/month per user.
  * Internet Book Search (Google Books API via `search-books`): Max 3 requests/day per user.
  * Recommendation Pipeline (`recommend-books`): Max 5 requests/day per user.
  * *Manual form submissions do not call the LLM and are completely unlimited.*

## 2. Tech Stack and Target Versions

* **Frontend:** React 18+, Tailwind CSS (for custom wooden/minimalist shelf textures), Framer Motion (for realistic book-pulling and shelf-sorting animations).
* **Backend / Agent Framework:** Python 3.12, `google-agents-cli` (v1.0.0+), `pydantic-ai` (v0.0.24+) for strict structural validation.
* **Environment:** GCP Cloud Run.
* **Database:** GCP Cloud SQL for PostgreSQL (Version 15) managed via custom `library-db-mcp`.
* **External APIs:** Google Books API (strictly encapsulated within the custom search MCP).
* **LLM Orchestration:** * **Gemini 3.1 Pro:** Dedicated entirely to the high-overhead OCR extraction within the photo processing pipeline.
  * **Gemini Flash:** Utilized for lightweight, rapid JSON structured recommendations and search query context generation.

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
* **Execution Flow:** React UI calls the `search-books` endpoint -> Backend checks the 3 requests/day search limit -> Agent calls `get_user_library` to understand existing items -> Agent builds a concise `library_summary` -> Agent passes parameters to `find_books_by_context` (Google Books API tool) -> Returns a clean list of external book recommendations to the UI.
* **Fallback Logic Rules:**
  1. *Library is empty/new user:* The search filters rely strictly on the text prompt provided by the user.
  2. *No text prompt provided:* The search functions in "Discovery Mode", evaluating the `library_summary` to fetch missing books from the Google Books API.
  3. *Both prompt and library are empty:* The pipeline short-circuits instantly and returns `status: missing_context` without executing external queries.

### Scenario D: Personalized Recommendations (`recommend-books`)
* **Frontend Trigger Event:** User clicks the "What should I read next from my shelf?" button located directly on the skeuomorphic library interface.
* **Execution Flow:** React UI triggers the endpoint -> Agent queries the user's specific collection via `get_user_library` -> Gemini Flash analyzes current statuses (e.g., heavily favors items marked as `unread`) -> Formats data into a valid A2UI `Carousel` payload -> Frontend receives the JSON and dynamically animates the recommended books out of the physical shelf.

## 4. Database Schema & Custom Tools

```yaml
database:
  engine: "Cloud SQL PostgreSQL 15"
  tables:
    users:
      columns:
        id: { type: "UUID", primary_key: true }
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
```

### Exported Tools from `library-db-mcp` (Strictly Restricted):
This server enforces absolute boundary control. It exposes **exactly two explicit business-logic functions**. The agent has no access to deletion mechanisms, drop commands, or user table modification parameters.
1. `save_book(...)` — Writes or updates book metadata. (Primarily triggered via the backend REST endpoint after frontend user confirmation).
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
      endpoint: "[https://custom-search-mcp-service.a.run.app/sse](https://custom-search-mcp-service.a.run.app/sse)"
      auth:
        secret_ref: GCP_SECRET_MANAGER_SEARCH_TOKEN
    - id: library-db-mcp
      type: mcp
      description: "Custom DB MCP. Exposes EXACTLY TWO tools: save_book and get_user_library. Expects User ID in request headers."
      endpoint: "[https://gcp-postgres-mcp-service.a.run.app/sse](https://gcp-postgres-mcp-service.a.run.app/sse)"
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