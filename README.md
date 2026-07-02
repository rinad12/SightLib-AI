# SightLib AI 📚

**Your cozy little AI-powered reading nook.**

Built for Kaggle's **5-Day AI Agents: Intensive Vibe Coding Course with Google** capstone.

SightLib AI turns a phone photo of your bookshelf into a managed digital library. Point a camera at a stack of books, and a Gemini vision agent reads every spine, cross-references it against Google Books, and hands you a clean, editable card — no typing. Two more agents then help you decide what to read next: one recommends strictly from books you already own, the other searches the wider internet when your shelf doesn't have what you're in the mood for.

## 🚀 Live Demo

> **Note for judges:** normal usage requires Google Sign-In (each user has their own private shelf), but deployment in submission runs with **Demo Mode** turned on: click "Try without signing in" on the landing screen to get a fresh guest account instantly, with no quota limits — no Google account needed to try every feature (Scan Cover, recommendations, search, manual library management).

## The problem

Anyone with more than a few dozen books runs into the same friction: you forget what you already own (and buy a duplicate), you forget what's sitting unread on the shelf, and cataloging a collection by hand — typing title, author, genre, description for every book — is tedious enough that most people never bother. Existing "shelfie" apps mostly just store a picture; they don't actually understand what's in it or help you decide what to read next.

## The solution — a small pipeline of purpose-built agents, not one big prompt

Rather than one LLM improvising the whole task, SightLib AI is built as a **deterministic, frontend-triggered pipeline** of narrow, single-purpose agents (Google ADK), each restricted to exactly the tools it needs:

| Agent | Model | Job | Tools it can call |
|---|---|---|---|
| `ocr_agent` | Gemini 3.1 Pro (vision) | Detects every distinct book in a photo (single cover, a stack, or a shelf) and extracts title/author for each, refusing to guess at illegible text | *(pure vision extraction, no tools)* |
| `polish_agent` | Gemini 3.5 Flash | Fixes OCR typos against the real title/author, rewrites raw/truncated Google Books descriptions into a clean synopsis, normalizes genre | *(text cleanup, no tools)* |
| `search_agent` | Gemini 3.5 Flash | Turns a free-form mood/genre request into good search keywords and filters out anthologies, criticism, and catalog junk | `find_books_by_context` (via `web-search-mcp`) |
| `recommend_agent` | Gemini 3.5 Flash | Recommends **only** from the user's own unread shelf — matching a typed mood, or inferring taste from books already finished — and returns nothing rather than force a bad match | *(reasons over already-fetched shelf data)* |

The agent layer never touches the database directly and never sees a raw user ID — see [Architecture & security](#architecture--security) below.

## Features

- **Scan Cover** — photograph one book, a stack, or a whole shelf in a single shot. Every book detected gets enriched with genre/description from Google Books and polished into a clean card; you review and confirm each one before it's saved (human-in-the-loop, nothing auto-writes).
- **What to Read Next? ("From My Shelf")** — grounded recommendations from books you already own; never suggests something you don't have.
- **Discover New Books ("Search Online")** — a second agent finds new books matching a mood/theme from the wider Google Books catalog.
- **Manual add/edit/delete** — full control to add, edit, or remove books yourself, completely independent of the AI path (the agent has no access to edit/delete — those are plain authenticated REST endpoints, not agent tools).
- **Google Sign-In** — each user has their own private library; per-skill daily/monthly usage quotas are enforced server-side, before any LLM call is made, not just displayed client-side.

## Architecture & security

```
frontend/          React 19 + Tailwind + Framer Motion (Vite dev server, HTTPS)
app/                FastAPI backend + Google ADK agent pipeline (agents table above)
mcp_servers/        Two custom MCP servers the agent talks to over SSE, each restricted
                     to exactly the tools listed:
                      - db_mcp_server.py     (library-db-mcp: get_user_library, save_book)
                      - search_mcp_server.py (web-search-mcp: find_books_by_context, wraps Google Books API)
```

Design principles carried through the whole system (full write-up in [`specs/architecture_design.md`](specs/architecture_design.md)):

- **Human-in-the-loop, always.** Every AI-assisted flow returns a *draft* to the UI; nothing is written to the database until the user reviews it and explicitly clicks Save.
- **Least-privilege tools.** `library-db-mcp` exposes exactly two tools (one read, one write) — the agent has zero raw SQL access, and no delete capability at all. Edit/delete are plain REST endpoints the agent can't reach.
- **Server-side identity, not agent-trusted identity.** The agent never receives or passes a user ID; the backend injects the session-verified ID directly into MCP request headers.
- **Structural quota gating.** Daily/monthly limits per skill are checked and recorded in a `usage_log` table *before* the LLM is invoked — a user can't burn budget by retrying.
- **Dedicated REST endpoint per skill** (`/api/process-book-photo`, `/api/search-books`, `/api/recommend-books`), each independently rate-limited.

## Prerequisites

- **Python 3.12** and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- **Node.js 18+** and npm
- **PostgreSQL** (local install, or a remote instance — tables are created automatically on first run)
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

No manual schema/migration step is needed — the backend creates all required tables (`users`, `books`, `user_library`, `usage_log`) on startup if they don't already exist.

### 3. Google Cloud setup

1. **Vertex AI (for OCR + LLM agents):**
   ```bash
   gcloud config set project <your-project-id>
   gcloud services enable aiplatform.googleapis.com
   gcloud auth application-default login
   ```
   Vertex AI requires billing to be enabled on the project.

2. **Google Books API key** (used for search/enrichment — without a key you'll hit a very low anonymous quota):
   - Enable the API: `gcloud services enable books.googleapis.com`
   - Create an API key under **APIs & Services → Credentials → Create Credentials → API key**, restricted to the Books API.

3. **Google OAuth Client ID** (for Sign-In With Google) — skip this step entirely if you just want to try the app via `DEMO_MODE` (step 4):
   - **APIs & Services → OAuth consent screen** — fill in the basic app info (App name, support email).
   - **APIs & Services → Credentials → Create Credentials → OAuth client ID → Web application.**
   - Under **Authorized JavaScript origins**, add:
     ```
     https://localhost:5173
     https://127.0.0.1:5173
     ```
     (Google Identity Services requires HTTPS, even for localhost — the dev server below serves over HTTPS with a self-signed cert for this reason.)

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
(same Client ID as above — it's not a secret, it's fine to expose in frontend code)

**Trying it out without Google Sign-In:** add `DEMO_MODE=true` to `.env` and you can skip step 3.3 (OAuth Client ID) entirely and leave `GOOGLE_OAUTH_CLIENT_ID` / `VITE_GOOGLE_CLIENT_ID` blank. The login screen will show a single "Try without signing in" button instead of Google Sign-In — each click creates a fresh, isolated guest account with quotas waived. Set it back to `false` (or remove it) to require real Google Sign-In again.

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

Open **`https://localhost:5173`** (HTTPS, port 5173). Your browser will warn about the self-signed dev certificate — click through ("Advanced → Proceed") to continue; this is expected for local development.

## Tests

```bash
uv run pytest tests/unit tests/integration
```

## Tech stack

React 19 · Tailwind CSS · Framer Motion · FastAPI · Google ADK (Agent Development Kit) · Gemini 3.1 Pro / 3.5 Flash · Model Context Protocol (MCP) · PostgreSQL · Google Books API · Google Sign-In
