# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import contextlib
import os
from collections.abc import AsyncIterator

import google.auth
from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.cloud import logging as google_cloud_logging
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import asyncpg
import json
import uuid

load_dotenv()

import logging
logger = logging.getLogger(__name__)
cloud_logger = None

try:
    setup_telemetry()
    _, project_id = google.auth.default()
    logging_client = google_cloud_logging.Client()
    cloud_logger = logging_client.logger(__name__)
except Exception as e:
    print(f"Skipping GCP telemetry setup (running in offline mode): {e}")
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "https://127.0.0.1:5173",
        "https://localhost:5173",
    ]
)

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

    try:
        conn = await get_db_conn()
        try:
            await ensure_schema(conn)
        finally:
            await conn.close()
    except Exception as e:
        logger.warning(f"Could not bootstrap DB schema at startup (DB may be offline): {e}")

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name
    await attach_a2a_routes(
        app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{adk_app.name}",
    )
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=False,
    lifespan=lifespan,
)
app.title = "sightlib-ai-agent"
app.description = "API for interacting with the Agent sightlib-ai-agent"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "https://127.0.0.1:5173",
        "https://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Signs the session cookie issued after a verified Google login. Must be set to a
# real secret in production - the dev fallback below is fine for local use only.
# SameSite/Secure are also env-driven: locally the frontend is proxied same-origin
# (see frontend/vite.config.js) so "lax"/non-secure is fine, but if frontend and
# backend are deployed on different domains, set SESSION_COOKIE_SAMESITE=none and
# SESSION_COOKIE_SECURE=true (Secure cookies require the backend itself to be HTTPS,
# which Cloud Run provides by default).
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET_KEY", "dev-insecure-secret-change-me"),
    same_site=os.environ.get("SESSION_COOKIE_SAMESITE", "lax"),
    https_only=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
)

GOOGLE_OAUTH_CLIENT_ID = os.environ.get(
    "GOOGLE_OAUTH_CLIENT_ID",
    "372551110403-ccfnb1119779oa6ugmsnbjkh780b0e9p.apps.googleusercontent.com",
)

# Temporary flag for demo recordings: lets visitors in without a Google account, so a screen
# capture doesn't have to show a real login. Turn back off (unset or "false") afterwards -
# see DEMO_MODE in .env.example.
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"

# Database helper for REST API
async def get_db_conn():
    return await asyncpg.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASS", "postgres"),
        database=os.environ.get("DB_NAME", "gridshelf"),
        port=os.environ.get("DB_PORT", "5432")
    )


def resolve_user_uuid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_DNS, user_id)


async def ensure_schema(conn):
    """Idempotent bootstrap for tables that aren't part of the original hand-rolled schema.
    Also migrates a `users` table that may already exist from an older, narrower schema
    (CREATE TABLE IF NOT EXISTS alone won't add columns to a table that already exists)."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS external_id VARCHAR(255)")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255)")
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_external_id ON users (external_id)
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_log (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL,
            skill VARCHAR(50) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_usage_log_user_skill_time
        ON usage_log (user_id, skill, created_at)
    """)

    # Core catalog tables. CREATE TABLE IF NOT EXISTS is a no-op if they already exist
    # (e.g. you created them by hand earlier) - this just lets a fresh clone/DB work
    # out of the box without a separate manual migration step.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id UUID PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            author VARCHAR(255) NOT NULL,
            genre VARCHAR(100),
            description TEXT
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_library (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL,
            book_id UUID NOT NULL REFERENCES books(id),
            status VARCHAR(50) NOT NULL DEFAULT 'unread',
            added_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_library_user_id ON user_library (user_id)
    """)


async def ensure_user(conn, user_uuid: uuid.UUID, external_id: str | None = None, email: str | None = None):
    await conn.execute(
        """
        INSERT INTO users (id, external_id, email)
        VALUES ($1, $2, $3)
        ON CONFLICT (id) DO NOTHING
        """,
        user_uuid, external_id, email
    )


def is_demo_guest(user_id: str) -> bool:
    """True for the throwaway accounts created by /api/auth/guest. Only meaningful while
    DEMO_MODE is on - used to waive quotas for judges/reviewers trying the demo."""
    return DEMO_MODE and user_id.startswith("guest-")


async def check_and_record_usage(conn, user_uuid: uuid.UUID, skill: str, per_day: int, per_month: int | None = None) -> bool:
    """Structural gating: returns True (and records the call) if the user is still within
    quota for `skill`, False if the daily or monthly limit has been reached."""
    now = datetime.utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    count_day = await conn.fetchval(
        "SELECT COUNT(*) FROM usage_log WHERE user_id = $1 AND skill = $2 AND created_at >= $3",
        user_uuid, skill, day_start
    )
    if count_day >= per_day:
        return False

    if per_month:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        count_month = await conn.fetchval(
            "SELECT COUNT(*) FROM usage_log WHERE user_id = $1 AND skill = $2 AND created_at >= $3",
            user_uuid, skill, month_start
        )
        if count_month >= per_month:
            return False

    await conn.execute(
        "INSERT INTO usage_log (id, user_id, skill, created_at) VALUES ($1, $2, $3, NOW())",
        uuid.uuid4(), user_uuid, skill
    )
    return True


DB_MCP_URL = os.environ.get("DB_MCP_URL", "http://127.0.0.1:8001/sse")


async def call_db_mcp_tool(tool_name: str, arguments: dict, user_id: str) -> str:
    """Calls a library-db-mcp tool directly (outside of an agent run), passing the
    authenticated user id via header exactly like the agent's McpToolset does."""
    headers = {"X-User-ID": user_id}
    token = os.environ.get("GCP_SECRET_MANAGER_DB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with sse_client(DB_MCP_URL, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return "\n".join(part.text for part in result.content if hasattr(part, "text"))


def require_session_user_id(request: Request) -> str:
    """Returns the authenticated user's id (Google `sub`) from the signed session
    cookie set by /api/auth/google, or raises 401 if there is no active session."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


class GoogleLoginRequest(BaseModel):
    id_token: str


@app.post("/api/auth/google")
async def auth_google(req: GoogleLoginRequest, request: Request):
    try:
        claims = google_id_token.verify_oauth2_token(
            req.id_token, google_auth_requests.Request(), GOOGLE_OAUTH_CLIENT_ID
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google ID token: {e}")

    google_sub = claims["sub"]
    email = claims.get("email")
    user_uuid = resolve_user_uuid(google_sub)

    try:
        conn = await get_db_conn()
        try:
            await ensure_user(conn, user_uuid, external_id=google_sub, email=email)
        finally:
            await conn.close()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}

    request.session["user_id"] = google_sub
    request.session["email"] = email
    return {"status": "success", "email": email}


@app.get("/api/config")
async def get_config():
    """Public, unauthenticated: tells the frontend which optional features are turned on."""
    return {"demo_mode": DEMO_MODE}


@app.post("/api/auth/guest")
async def auth_guest(request: Request):
    """Demo-only: logs the visitor in as a fresh, isolated guest account with no Google
    sign-in required. Disabled unless DEMO_MODE=true."""
    if not DEMO_MODE:
        raise HTTPException(status_code=403, detail="Guest login is disabled")

    guest_id = f"guest-{uuid.uuid4()}"
    user_uuid = resolve_user_uuid(guest_id)

    try:
        conn = await get_db_conn()
        try:
            await ensure_user(conn, user_uuid, external_id=guest_id, email=None)
        finally:
            await conn.close()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}

    request.session["user_id"] = guest_id
    request.session["email"] = "Guest"
    return {"status": "success", "email": "Guest"}


@app.get("/api/auth/me")
async def auth_me(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return {"authenticated": False}
    return {"authenticated": True, "email": request.session.get("email"), "user_id": user_id}


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return {"status": "success"}


class BookSaveRequest(BaseModel):
    title: str
    author: str
    genre: Optional[str] = ""
    description: Optional[str] = ""
    status: Optional[str] = "unread"

class ProcessBookPhotoRequest(BaseModel):
    image_bytes: str  # Base64 encoded string

class SearchBooksRequest(BaseModel):
    query: Optional[str] = None

class RecommendBooksRequest(BaseModel):
    preference: Optional[str] = None

@app.get("/api/library")
async def get_library(request: Request):
    user_id = require_session_user_id(request)
    user_uuid = resolve_user_uuid(user_id)
    try:
        conn = await get_db_conn()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}", "items": []}

    try:
        rows = await conn.fetch(
            """
            SELECT b.id, b.title, b.author, b.genre, b.description, ul.status
            FROM books b
            JOIN user_library ul ON b.id = ul.book_id
            WHERE ul.user_id = $1::uuid
            """,
            user_uuid
        )
        items = [dict(r) for r in rows]
        for item in items:
            item["id"] = str(item["id"])
        return {"status": "success", "items": items}
    except Exception as e:
        return {"status": "error", "message": str(e), "items": []}
    finally:
        await conn.close()

@app.post("/api/books")
async def save_book_api(req: BookSaveRequest, request: Request):
    user_id = require_session_user_id(request)
    user_uuid = resolve_user_uuid(user_id)

    try:
        conn = await get_db_conn()
        try:
            await ensure_user(conn, user_uuid)
        finally:
            await conn.close()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}

    # Writes go through the library-db-mcp save_book tool (not raw asyncpg here),
    # so the MCP layer stays the single, restricted path for database mutations.
    try:
        result_text = await call_db_mcp_tool(
            "save_book",
            {
                "title": req.title,
                "author": req.author,
                "genre": req.genre or "",
                "description": req.description or "",
                "status": req.status or "unread",
            },
            user_id,
        )
        if result_text.lower().startswith("error"):
            return {"status": "error", "message": result_text}
        return {"status": "success", "message": result_text}
    except Exception as e:
        logger.exception("Failed to save book via library-db-mcp")
        return {"status": "error", "message": str(e)}


@app.put("/api/books/{book_id}")
async def update_book_api(book_id: str, req: BookSaveRequest, request: Request):
    """Direct DB edit for a book already on the user's shelf. Intentionally NOT an
    MCP tool and NOT reachable through the agent - the LLM has no way to trigger this."""
    user_id = require_session_user_id(request)
    user_uuid = resolve_user_uuid(user_id)

    try:
        book_uuid = uuid.UUID(book_id)
    except ValueError:
        return {"status": "error", "message": "Invalid book id"}

    try:
        conn = await get_db_conn()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}

    try:
        owns = await conn.fetchval(
            "SELECT 1 FROM user_library WHERE user_id = $1 AND book_id = $2",
            user_uuid, book_uuid
        )
        if not owns:
            return {"status": "error", "message": "Book not found on your shelf"}

        await conn.execute(
            "UPDATE books SET title = $1, author = $2, genre = $3, description = $4 WHERE id = $5",
            req.title, req.author, req.genre or "", req.description or "", book_uuid
        )
        await conn.execute(
            "UPDATE user_library SET status = $1 WHERE user_id = $2 AND book_id = $3",
            req.status or "unread", user_uuid, book_uuid
        )
        return {"status": "success", "message": "Book updated"}
    except Exception as e:
        logger.exception("Failed to update book")
        return {"status": "error", "message": str(e)}
    finally:
        await conn.close()


@app.delete("/api/books/{book_id}")
async def delete_book_api(book_id: str, request: Request):
    """Removes a book from the current user's shelf (unlinks the user_library row,
    doesn't touch the shared books catalog row). Same restriction as above: plain
    authenticated REST mutation, no MCP tool, no agent access."""
    user_id = require_session_user_id(request)
    user_uuid = resolve_user_uuid(user_id)

    try:
        book_uuid = uuid.UUID(book_id)
    except ValueError:
        return {"status": "error", "message": "Invalid book id"}

    try:
        conn = await get_db_conn()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}

    try:
        result = await conn.execute(
            "DELETE FROM user_library WHERE user_id = $1 AND book_id = $2",
            user_uuid, book_uuid
        )
        if result == "DELETE 0":
            return {"status": "error", "message": "Book not found on your shelf"}
        return {"status": "success", "message": "Book removed from shelf"}
    except Exception as e:
        logger.exception("Failed to delete book")
        return {"status": "error", "message": str(e)}
    finally:
        await conn.close()


async def run_agent_pipeline(user_id: str, text: str, image_bytes: Optional[str] = None) -> dict:
    """Shared runner invocation used by the three dedicated skill endpoints below."""
    runner = app.state.runner

    try:
        session_id = str(uuid.UUID(user_id))
    except ValueError:
        session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, user_id))

    from google.genai import types
    import base64

    parts = [types.Part.from_text(text=text)]
    if image_bytes:
        try:
            img_data = base64.b64decode(image_bytes)
            parts.append(types.Part.from_bytes(data=img_data, mime_type="image/jpeg"))
        except Exception as e:
            return {"status": "error", "message": f"Failed to decode image bytes: {str(e)}"}

    new_message = types.Content(role="user", parts=parts)

    try:
        session_service = runner.session_service
        session = await session_service.get_session(
            app_name=runner.app.name,
            user_id=user_id,
            session_id=session_id
        )
        if not session:
            session = await session_service.create_session(
                app_name=runner.app.name,
                user_id=user_id,
                session_id=session_id
            )

        final_output = None
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message
        ):
            if event.output:
                final_output = event.output

        if final_output is None:
            return {"status": "error", "message": "No output generated by agent"}

        try:
            return json.loads(final_output)
        except Exception:
            return {"status": "success", "output": final_output}

    except Exception as e:
        logger.exception("Error during agent run API execution")
        return {"status": "error", "message": str(e)}


@app.post("/api/process-book-photo")
async def process_book_photo_api(req: ProcessBookPhotoRequest, request: Request):
    user_id = require_session_user_id(request)
    user_uuid = resolve_user_uuid(user_id)
    try:
        conn = await get_db_conn()
        try:
            await ensure_user(conn, user_uuid)
            allowed = is_demo_guest(user_id) or await check_and_record_usage(
                conn, user_uuid, "process-book-photo", per_day=3, per_month=10
            )
        finally:
            await conn.close()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}

    if not allowed:
        return {
            "status": "quota_exceeded",
            "items": []
        }

    return await run_agent_pipeline(user_id, "Process this book cover photo", image_bytes=req.image_bytes)


@app.post("/api/search-books")
async def search_books_api(req: SearchBooksRequest, request: Request):
    user_id = require_session_user_id(request)
    user_uuid = resolve_user_uuid(user_id)
    try:
        conn = await get_db_conn()
        try:
            await ensure_user(conn, user_uuid)
            allowed = is_demo_guest(user_id) or await check_and_record_usage(
                conn, user_uuid, "search-books", per_day=5
            )
        finally:
            await conn.close()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}", "items": []}

    if not allowed:
        return {"status": "quota_exceeded", "items": []}

    text = f"Search for {req.query}" if req.query else "Search (empty prompt)"
    return await run_agent_pipeline(user_id, text)


@app.post("/api/recommend-books")
async def recommend_books_api(req: RecommendBooksRequest, request: Request):
    user_id = require_session_user_id(request)
    user_uuid = resolve_user_uuid(user_id)
    try:
        conn = await get_db_conn()
        try:
            await ensure_user(conn, user_uuid)
            allowed = is_demo_guest(user_id) or await check_and_record_usage(
                conn, user_uuid, "recommend-books", per_day=5
            )
        finally:
            await conn.close()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}", "items": []}

    if not allowed:
        return {"status": "quota_exceeded", "items": []}

    text = (
        f"Recommend some books based on my shelf: {req.preference}"
        if req.preference else "Recommend some books based on my shelf"
    )
    return await run_agent_pipeline(user_id, text)


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    if cloud_logger:
        cloud_logger.log_struct(feedback.model_dump(), severity="INFO")
    else:
        logger.info("Feedback: %s", feedback.model_dump())
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
