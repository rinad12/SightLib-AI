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
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.cloud import logging as google_cloud_logging

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import asyncpg
import json
import uuid

load_dotenv()

import logging
logger = logging.getLogger(__name__)

try:
    setup_telemetry()
    _, project_id = google.auth.default()
    logging_client = google_cloud_logging.Client()
    logger = logging_client.logger(__name__)
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
    ]
)

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

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
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database helper for REST API
async def get_db_conn():
    return await asyncpg.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASS", "postgres"),
        database=os.environ.get("DB_NAME", "gridshelf"),
        port=os.environ.get("DB_PORT", "5432")
    )

class BookSaveRequest(BaseModel):
    title: str
    author: str
    genre: Optional[str] = ""
    description: Optional[str] = ""
    status: Optional[str] = "unread"

class AgentRunRequest(BaseModel):
    prompt: str
    image_bytes: Optional[str] = None # Base64 encoded string

@app.get("/api/library")
async def get_library(user_id: str = "default-user"):
    try:
        conn = await get_db_conn()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}", "items": []}
    
    try:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            user_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, user_id)
            
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
async def save_book_api(req: BookSaveRequest, user_id: str = "default-user"):
    try:
        conn = await get_db_conn()
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}
        
    try:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            user_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, user_id)
            
        # Check if book exists
        book_row = await conn.fetchrow(
            "SELECT id FROM books WHERE title = $1 AND author = $2",
            req.title, req.author
        )
        
        if book_row:
            book_uuid = book_row["id"]
            await conn.execute(
                "UPDATE books SET genre = COALESCE(NULLIF(genre, ''), $1), description = COALESCE(NULLIF(description, ''), $2) WHERE id = $3",
                req.genre, req.description, book_uuid
            )
        else:
            book_uuid = uuid.uuid4()
            await conn.execute(
                "INSERT INTO books (id, title, author, genre, description) VALUES ($1, $2, $3, $4, $5)",
                book_uuid, req.title, req.author, req.genre, req.description
            )
            
        # Link to library
        link_row = await conn.fetchrow(
            "SELECT id FROM user_library WHERE user_id = $1 AND book_id = $2",
            user_uuid, book_uuid
        )
        if not link_row:
            await conn.execute(
                "INSERT INTO user_library (id, user_id, book_id, status, added_at) VALUES ($1, $2, $3, $4, NOW())",
                uuid.uuid4(), user_uuid, book_uuid, req.status
            )
        else:
            await conn.execute(
                "UPDATE user_library SET status = $1 WHERE user_id = $2 AND book_id = $3",
                req.status, user_uuid, book_uuid
            )
            
        return {"status": "success", "message": "Book saved successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        await conn.close()

@app.post("/api/agent/run")
async def run_agent_api(req: AgentRunRequest, user_id: str = "default-user"):
    runner = app.state.runner
    
    try:
        session_id = str(uuid.UUID(user_id))
    except ValueError:
        session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, user_id))
        
    from google.genai import types
    import base64
    
    if req.image_bytes:
        try:
            img_data = base64.b64decode(req.image_bytes)
            new_message = types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=req.prompt),
                    types.Part.from_bytes(data=img_data, mime_type="image/jpeg")
                ]
            )
        except Exception as e:
            return {"status": "error", "message": f"Failed to decode image bytes: {str(e)}"}
    else:
        new_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=req.prompt)]
        )
        
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


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
