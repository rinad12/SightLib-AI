# SightLib AI 📚

**Your cozy little AI-powered reading nook.**

SightLib AI is a personal book library app: scan a photo of one or more book covers and let Gemini read them for you, get AI-curated recommendations from your own shelf, or discover new books to read — all wrapped in a warm, skeuomorphic "wooden bookshelf" UI.

## Features

- **Scan Cover** — photograph a single book, a stack, or a whole shelf. Gemini 3.1 Pro (vision) detects every book in the photo, and each one is enriched with genre/description from Google Books, then polished by an LLM pass that fixes OCR typos and rewrites truncated/garbled descriptions into a clean synopsis.
- **What to Read Next? ("From My Shelf")** — an LLM picks what to read next from your own unread/in-progress books, either matching a typed mood/genre or inferring your taste from what you've already finished. Never suggests a book you don't already own.
- **Discover New Books ("Search Online")** — a second LLM agent turns a free-form request into good search keywords, queries Google Books, and filters out anthologies/catalogs/criticism so you only see real, readable books.
- **Manual add/edit/delete** — full control to add, edit, or remove books yourself, independent of any AI step (the agent has no access to edit/delete - those are plain authenticated REST endpoints).
- **Google Sign-In** — each user has their own private library; per-skill daily/monthly usage quotas are enforced server-side before any LLM call.

## Architecture

```
frontend/          React 19 + Tailwind + Framer Motion (Vite dev server, HTTPS)
app/                FastAPI backend + Google ADK agent (Gemini 3.1 Pro for OCR, Gemini 3.5 Flash for
                     recommend/search/polish agents)
mcp_servers/        Two custom MCP servers the agent talks to over SSE:
                      - db_mcp_server.py     (library-db-mcp: get_user_library, save_book)
                      - search_mcp_server.py (web-search-mcp: find_books_by_context, wraps Google Books API)
```

The agent never has raw SQL access or an edit/delete tool - see [`specs/architecture_design.md`](specs/architecture_design.md) for the full design write-up (security model, quota policy, database schema).

## Prerequisites

- **Python 3.12** and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- **Node.js 18+** and npm
- **PostgreSQL** (local install, or a remote instance - tables are created automatically on first run)
- **A Google Cloud project** with billing enabled

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/rinad12/SightLib-AI.git
cd SightLib-AI
uv sync
cd frontend && npm install && cd ..
```

### 2. PostgreSQL

Create an empty database (default name expected is `gridshelf`, configurable via `.env`):

```bash
createdb gridshelf
```

No manual schema/migration step is needed - the backend creates all required tables (`users`, `books`, `user_library`, `usage_log`) on startup if they don't already exist.

### 3. Google Cloud setup

1. **Vertex AI (for OCR + LLM agents):**
   ```bash
   gcloud config set project <your-project-id>
   gcloud services enable aiplatform.googleapis.com
   gcloud auth application-default login
   ```
   Vertex AI requires billing to be enabled on the project.

2. **Google Books API key** (used for search/enrichment - without a key you'll hit a very low anonymous quota):
   - Enable the API: `gcloud services enable books.googleapis.com`
   - Create an API key under **APIs & Services → Credentials → Create Credentials → API key**, restricted to the Books API.

3. **Google OAuth Client ID** (for Sign-In With Google):
   - **APIs & Services → OAuth consent screen** - fill in the basic app info (App name, support email).
   - **APIs & Services → Credentials → Create Credentials → OAuth client ID → Web application.**
   - Under **Authorized JavaScript origins**, add:
     ```
     https://localhost:5173
     https://127.0.0.1:5173
     ```
     (Google Identity Services requires HTTPS, even for localhost - the dev server below serves over HTTPS with a self-signed cert for this reason.)

### 4. Configure environment variables

Copy the example files and fill in the values from step 3:

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
```

`.env` (backend):
```
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASS=your_postgres_password
DB_NAME=gridshelf
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_BOOKS_API_KEY=your_google_books_api_key
GOOGLE_OAUTH_CLIENT_ID=your_oauth_client_id.apps.googleusercontent.com
SESSION_SECRET_KEY=any_long_random_string
```

`frontend/.env`:
```
VITE_GOOGLE_CLIENT_ID=your_oauth_client_id.apps.googleusercontent.com
```
(same Client ID as above - it's not a secret, it's fine to expose in frontend code)

### 5. Run it

The app is four processes: two MCP servers, the backend, and the frontend dev server. Easiest way on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

This opens each in its own window. To run them manually instead:

```bash
uv run uvicorn mcp_servers.db_mcp_server:app --host 127.0.0.1 --port 8001
uv run uvicorn mcp_servers.search_mcp_server:app --host 127.0.0.1 --port 8002
uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev
```

Open **`https://localhost:5173`** (HTTPS, port 5173). Your browser will warn about the self-signed dev certificate - click through ("Advanced → Proceed") to continue; this is expected for local development.

## Tests

```bash
uv run pytest tests/unit tests/integration
```

## Tech stack

React 19 · Tailwind CSS · Framer Motion · FastAPI · Google ADK (Agent Development Kit) · Gemini 3.1 Pro / 3.5 Flash · Model Context Protocol (MCP) · PostgreSQL · Google Books API · Google Sign-In
