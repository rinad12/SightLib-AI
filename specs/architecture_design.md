# Architecture Specification: GridShelf AI (Headless Book Pipeline)

## 1. Context and Business Logic (Invisible Pipeline)

The system is an automated pipeline for managing a personal library. It operates as a **headless agent without a user-facing chat interface**.

The agent reacts exclusively to hard triggers (file uploads, button clicks) and functions as a set of isolated microservices (Skills). Instead of generating text responses, the agent always returns strictly typed JSON objects corresponding to frontend components (A2UI: Card, Carousel, List).

Integration with the outside world (web search, database operations) is performed strictly via Server-Sent Events (SSE) using custom MCP servers. The database is hosted on **Google Cloud Platform (GCP)**.

### 1.1 Security & Authentication (Strict Context Injection)

* **System Login:** User registration and authorization are handled exclusively via **Google Auth**.
* **User ID Isolation (CRITICAL):** The LLM agent **never** receives the `User ID` in plain text and **never** passes it to the tools (MCP servers) itself.
* **Injection Mechanism:** The `User ID` is passed to the tools strictly at the backend/infrastructure layer (e.g., via secure headers or session context objects). When the agent decides to call a tool like `save_book` or `get_user_library`, the infrastructure automatically injects the authenticated user's ID into the request. This eliminates the risk of the agent accessing other users' data due to errors or prompt injection.
* **SQL Injection Protection (Custom MCP):** The agent **does not write or generate SQL queries**. Database interaction occurs through a manually written (custom) `library-db-mcp` that exposes only predefined, secure functions.
* **Usage Limits & Policy Server (Structural Gating):** To prevent abuse, strict quotas are enforced:
  * Photo Upload (`process-book-photo`): **Max 3 photos/day and 10 photos/month** per user.
  * Recommendations (`recommend-books`): **Max 5 requests/day** per user.
  
  The backend (Policy Server) checks these quotas *before* invoking the agent skills. If a limit is exceeded, the pipeline instantly returns an A2UI component (Card) with an error/limit notification, **without invoking the LLM or consuming tokens**.

## 2. Tech Stack and Target Versions

To prevent LLM hallucinations and the use of deprecated APIs, the project must be generated with strict adherence to the following versions:

* **Language:** Python 3.12
* **Agent Management & Orchestration:**
  * `google-agents-cli` (v1.0.0+)
  * `pydantic-ai` (v0.0.24+) — for strict output typing and A2UI schema validation.
  * `langchain` (v0.2.0+) — utility helpers, if adapters are needed.
* **Deployment Environment:** GCP Cloud Run.
* **Database:** GCP Cloud SQL for PostgreSQL (Version 15). DB access is routed through a dedicated custom `library-db-mcp`.
* **LLM:** Current Gemini Lineup:
  * **Gemini 3.1 Pro:** Used in the `process-book-photo` skill for high-accuracy OCR on complex book covers (poor lighting, glare).
  * **Gemini Flash (latest):** Used in the `recommend-books` skill for fast and cost-effective generation based on text summaries.

## 3. Use Cases, BDD & Testing (Evaluation-Driven Development)

### Instruction for the Code Agent (Antigravity):
> **Generate at least 3 JSON evaluation cases (eval cases) for each skill BEFORE writing their logic.** This guarantees a proper testing framework and exact compliance with the A2UI output format.

### Scenario A: Process Uploaded Photo (`process-book-photo`)
* **Expected Flow:** UI sends `image_bytes` -> Backend checks limits (max 3/day) -> Agent (Gemini 3.1 Pro) performs OCR -> Calls `web-search-mcp` for genre/description -> Calls custom `save_book` tool (without User ID) -> Returns A2UI `Card`.
* **Edge Case 1 (OCR Failure):** If the photo is blurry and the model returns an empty title, the agent *must not* crash or call the search MCP. It returns an A2UI `Card` with `status: manual_input_required` and empty fields for manual user entry on the frontend.
* **Edge Case 2 (Book not found online):** If OCR is successful but `web-search-mcp` finds nothing, the agent saves only the recognized author and title to the DB, setting description to `null`. It returns a `Card` with a partial data warning.

### Scenario B: Personalized Recommendations (`recommend-books`)
* **Expected Flow:** UI triggers skill (optionally with user prompt) -> Backend checks limits (max 5/day) -> Agent (Gemini Flash) calls custom `get_user_library` tool (User ID injected via context) -> LLM generates a concise `library_summary` -> Agent calls custom search tool `find_books_by_context(user_prompt, library_summary)` -> Formats final output -> Returns A2UI `Carousel`.
* **Edge Case 1 (Empty Library):** If the DB returns an empty array (new user), the agent *must not* hallucinate. Fallback triggered: returns A2UI `Carousel` with a hardcoded list of universal bestsellers.
* **Edge Case 2 (Quota Exceeded):** If the user hits the 5 requests/day limit, the pipeline (at the Policy Server level) blocks LLM execution and returns an A2UI `Card` indicating they must wait until tomorrow.

## 4. Database Schema & Custom Tools

To understand data structures, the relational schema is provided below. **Note:** The agent does not query these tables directly.

```yaml
database:
  engine: "Cloud SQL PostgreSQL 15"
  tables:
    users:
      description: "User profiles (Google Authentication)"
      columns:
        id: { type: "UUID", primary_key: true, description: "Unique user ID (mapped from Google Auth ID)" }
        created_at: { type: "TIMESTAMP", description: "Profile creation timestamp" }
    books:
      description: "Global book directory, enriched with web search data"
      columns:
        id: { type: "UUID", primary_key: true, description: "Unique book ID" }
        title: { type: "VARCHAR(255)", description: "Book title (extracted via OCR)" }
        author: { type: "VARCHAR(255)", description: "Author(s)" }
        genre: { type: "VARCHAR(100)", description: "Genre (enriched via web-search-mcp)" }
        description: { type: "TEXT", description: "Short description or synopsis" }
    user_library:
      description: "Many-to-Many junction table defining books in a specific user's library"
      columns:
        id: { type: "UUID", primary_key: true, description: "Unique record ID" }
        user_id: { type: "UUID", foreign_key: "users.id", description: "User reference. WARNING: Injected at DB/MCP level, agent does not pass this!" }
        book_id: { type: "UUID", foreign_key: "books.id", description: "Book reference" }
        status: { type: "VARCHAR(50)", description: "Reading status (unread, reading, read)" }
        added_at: { type: "TIMESTAMP", description: "Date added by user" }
```

### Exported Tools from Custom `library-db-mcp`:
1. `save_book(title: str, author: str, genre: str, description: str)` — Saves a new book to the directory and links it to the user.
2. `get_user_library()` — Returns the list of books added by the current user.

### Exported Tools from Custom `web-search-mcp`:
1. `find_books_by_context(user_prompt: str, library_summary: str)` — The MCP handles search queries, scrapes data (e.g., Goodreads), and returns a structured list of relevant books based on the user's specific request and their historical reading preferences.

## 5. Resource Configuration (YAML Manifest)

**Instruction for Antigravity:** Use the manifest below as a high-level architectural blueprint. During code generation, **distribute skills into separate folders** (e.g., `.agent/skills/<skill-name>/SKILL.md`) following the pattern of **progressive context disclosure** to avoid overloading a single file with all the logic.

```yaml
manifest_version: "1.0"
name: gridshelf-ai-agent
version: "1.0.0"
runtime: python312

# External Dependencies Declaration (MCP Servers)
resources:
  mcp_servers:
    - id: web-search-mcp
      type: mcp
      description: "Custom MCP for contextual book search. Exposes find_books_by_context tool."
      endpoint: "https://custom-search-mcp-service.a.run.app/sse"
      auth:
        secret_ref: GCP_SECRET_MANAGER_SEARCH_TOKEN

    - id: library-db-mcp
      type: mcp
      description: "Custom MCP (RPC API to PostgreSQL). Exposes strictly typed business functions (save_book, get_user_library) to prevent SQL injection. WARNING: Expects User ID in request headers, not tool arguments."
      endpoint: "https://gcp-postgres-mcp-service.a.run.app/sse"
      auth:
        secret_ref: GCP_SECRET_MANAGER_DB_TOKEN

# Direct Interface Invoked Skills
skills:
  - id: process-book-photo
    description: "Cover photo processing pipeline using Gemini 3.1 Pro OCR"
    input:
      type: object
      properties:
        image_bytes: { type: string, format: byte, description: "Base64 encoded image" }
    output:
      type: object
      description: "Valid JSON object for A2UI Card component"
      properties:
        component: { type: string, enum: ["Card"] }
        status: { type: string, enum: ["success", "manual_input_required", "partial_data", "quota_exceeded"] }
        data:
          type: object
          properties:
            title: { type: string, nullable: true }
            author: { type: string, nullable: true }
            genre: { type: string, nullable: true }
            description: { type: string, nullable: true }

  - id: recommend-books
    description: "Recommendation generation using Gemini Flash and Custom Web Search MCP"
    input:
      type: object
      properties:
        user_prompt: { type: string, nullable: true, description: "Optional user input, e.g., 'I want dark fantasy'" }
    output:
      type: object
      description: "Valid JSON object for A2UI (Carousel on success, Card on quota error)"
      properties:
        component: { type: string, enum: ["Carousel", "Card"] }
        status: { type: string, enum: ["success", "empty_library", "quota_exceeded"] }
        items:
          type: array
          description: "Used for Carousel, array of recommendation cards"
          items:
            type: object
        data:
          type: object
          description: "Used for Card, error message payload"
```
