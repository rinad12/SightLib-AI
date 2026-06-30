# Architecture Specification: GridShelf AI

## 1. Context and Business Logic (React UI + Headless Agent)

The system consists of two main layers: a **React frontend application** and a **headless AI agent pipeline**. 

### 1.1 Frontend Application (React)
* **Visual Style (Skeuomorphic UI):** The interface must simulate a realistic, physical library. Books should be rendered as interactive 3D/2D spines on bookshelves, not just standard web cards.
* **Core Workflows:**
  1. **Photo Upload Mode:** User takes/uploads a photo of a book. The AI extracts and enriches the data via Google Books, returning a "Draft". The user reviews and edits the fields in a form before finalizing the save.
  2. **Manual Entry Mode:** User can bypass the AI entirely and manually type the book's details into an empty form.
* **Human-in-the-Loop (HITL):** For photo uploads, the AI agent **does not** save the book to the database automatically. It returns the recognized and enriched data to the React UI. The user acts as the final validator.

### 1.2 Backend & Agent Pipeline
The AI reacts exclusively to hard triggers from the React backend. Integration with the database and external APIs is performed via Server-Sent Events (SSE) using custom MCP servers.

### 1.3 Security & Authentication (Strict Gating & Least Privilege)
* **System Login:** Google Auth exclusively.
* **User ID Isolation:** The LLM agent **never** receives or transmits the `User ID` directly. The backend injects it into DB/MCP requests.
* **Database Access Restriction:** The agent does not write SQL. Furthermore, there is no generic database tool available. The `library-db-mcp` is intentionally restricted to expose **exactly two specialized tools** (one for reading, one for writing). 
* **Usage Limits (Structural Gating via Policy Server):**
  * Photo Upload Pipeline (`process-book-photo`): Max 3/day, 10/month.
  * Internet Book Search (Google Books API via `search-books`): Max 3/day.
  * Recommendation Pipeline (`recommend-books`): Max 5/day.
  * *Manual entry does not trigger the AI and has no limits.*

## 2. Tech Stack and Target Versions

* **Frontend:** React 18+, Tailwind CSS (for realistic textures/shelves styling), Framer Motion (for book interactions).
* **Backend / Agent Framework:** Python 3.12, `google-agents-cli` (v1.0.0+), `pydantic-ai` (v0.0.24+).
* **Environment:** GCP Cloud Run.
* **Database:** GCP Cloud SQL for PostgreSQL (Version 15) via custom `library-db-mcp`.
* **External APIs:** Google Books API (strictly used inside the custom search MCP).
* **LLM:** * **Gemini 3.1 Pro:** OCR extraction.
  * **Gemini Flash:** Recommendations and contextual search summarization.

## 3. Use Cases, BDD & Testing (Evaluation-Driven Development)

### Instruction for Antigravity:
> **Generate at least 3 JSON evaluation cases for each skill BEFORE writing logic.**

### Scenario A: Photo Upload & Review (`process-book-photo`)
* **Flow:** React UI sends photo -> Agent (Gemini 3.1 Pro) performs OCR -> Calls `web-search-mcp` (Google Books API) for genre/description -> **Agent returns a Draft JSON** -> React UI displays the draft in an editable form -> User edits/confirms -> React UI calls Backend to save to DB.
* **Edge Case (OCR Failure):** If the photo is blurry, the agent returns an empty/partial Draft JSON with `status: manual_input_required`. The React UI displays the empty form for manual completion.

### Scenario B: Manual Entry (Frontend Only)
* **Flow:** User clicks "Add Manually" -> React UI displays empty form -> User fills details -> React UI calls Backend to save to DB. The AI agent is bypassed to save tokens.

### Scenario C: Contextual Internet Search (`search-books`)
* **Flow:** User wants to add a book not in their library. UI sends prompt (e.g., "Cyberpunk 1980s") -> Backend enforces the 3 requests/day limit -> Agent calls `get_user_library` -> Agent creates `library_summary` -> Agent calls `find_books_by_context` (queries Google Books API) -> Returns list to UI.
* **Fallback Logic:**
  1. If library is empty/irrelevant: Search relies strictly on the user's prompt.
  2. If no user prompt is provided: Search relies strictly on the `library_summary` (Discovery mode).
  3. If both are empty/missing: Return `status: missing_context` (no search performed).

### Scenario D: Personalized Recommendations (`recommend-books`)
* **Flow:** User asks "What to read next from my shelf?" -> Agent calls `get_user_library` -> Returns Carousel of books already in the user's library.

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
To enforce the principle of least privilege, this MCP exposes **only two specific tools**. There are absolutely no generic SQL execution tools, deletion tools, or user-management tools available to the agent.
1. `save_book(...)` — Saves/updates a book. *Note: Primarily called by the Backend API after user confirms in React UI.*
2. `get_user_library()` — Reads and returns the user's current books. 

### Exported Tools from `web-search-mcp`:
1. `find_books_by_context(user_prompt: str, library_summary: str)` — Wraps the Google Books API to fetch structured metadata safely and reliably.

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
      description: "Custom MCP wrapping the Google Books API. Exposes ONLY find_books_by_context."
      endpoint: "[https://custom-search-mcp-service.a.run.app/sse](https://custom-search-mcp-service.a.run.app/sse)"
      auth:
        secret_ref: GCP_SECRET_MANAGER_SEARCH_TOKEN
    - id: library-db-mcp
      type: mcp
      description: "Custom DB MCP. Exposes EXACTLY TWO tools: save_book and get_user_library. No generic DB access permitted. Expects User ID in request headers."
      endpoint: "[https://gcp-postgres-mcp-service.a.run.app/sse](https://gcp-postgres-mcp-service.a.run.app/sse)"
      auth:
        secret_ref: GCP_SECRET_MANAGER_DB_TOKEN

skills:
  - id: process-book-photo
    description: "OCR pipeline. Returns draft data for React UI review. DOES NOT SAVE TO DB."
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
    description: "Searches Google Books API for new books based on prompt or library context."
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
    description: "Recommends books ALREADY in the user's library."
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