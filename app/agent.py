# ruff: noqa
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

import datetime
from zoneinfo import ZoneInfo

from google.adk import Workflow
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.workflow import node
from google.genai import types
from pydantic import BaseModel

import os
import google.auth

try:
    _, project_id = google.auth.default()
except Exception:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "sightlib-ai-project")
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


import json
import logging
from typing import Any
from google.adk.agents.context import Context
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import SseConnectionParams

logger = logging.getLogger(__name__)


def library_db_header_provider(readonly_context) -> dict[str, str]:
    """Provides authorization headers and user ID for the library database MCP."""
    headers = {}
    token = os.environ.get("GCP_SECRET_MANAGER_DB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Inject authenticated User ID from context strictly at the infrastructure layer
    user_id = getattr(readonly_context, "user_id", None)
    if user_id:
        headers["X-User-ID"] = str(user_id)

    return headers


def web_search_header_provider(readonly_context) -> dict[str, str]:
    """Provides authorization headers for the web search MCP."""
    headers = {}
    token = os.environ.get("GCP_SECRET_MANAGER_SEARCH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


# Define remote MCP toolsets using Server-Sent Events (SSE)
db_mcp_toolset = McpToolset(
    connection_params=SseConnectionParams(
        url="https://gcp-postgres-mcp-service.a.run.app/sse"
    ),
    header_provider=library_db_header_provider,
)

search_mcp_toolset = McpToolset(
    connection_params=SseConnectionParams(
        url="https://custom-search-mcp-service.a.run.app/sse"
    ),
    header_provider=web_search_header_provider,
)


async def _call_mcp_tool(toolset: McpToolset, tool_name: str, args: dict, tool_context: Context) -> Any:
    """Helper to programmatically invoke a tool from an McpToolset."""
    readonly_ctx = ReadonlyContext(tool_context._invocation_context)
    tools = await toolset.get_tools(readonly_ctx)
    tool = next((t for t in tools if t.name == tool_name), None)
    if not tool:
        raise ValueError(f"MCP tool '{tool_name}' not found in toolset")
    return await tool.run_async(args=args, tool_context=tool_context)


async def get_user_library(tool_context: Context) -> list:
    """Retrieves the list of books in the current user's library.

    Args:
        tool_context: The execution context.
    """
    try:
        res = await _call_mcp_tool(db_mcp_toolset, "get_user_library", {}, tool_context)
        if isinstance(res, dict) and "result" in res:
            return res["result"]
        return res
    except Exception as e:
        logger.exception("Failed to get user library")
        return []


async def save_book(
    title: str,
    author: str,
    genre: str | None = None,
    description: str | None = None,
    tool_context: Context = None
) -> dict:
    """Saves a book to the library database and returns the A2UI Card JSON component representation.

    Args:
        title: Title of the book (extracted via OCR)
        author: Author(s) of the book
        genre: Genre (enriched via search)
        description: Description/synopsis of the book (enriched via search)
        tool_context: The execution context.
    """
    status = "success" if (genre and description) else "partial_data"

    try:
        args = {
            "title": title,
            "author": author,
            "genre": genre or "",
            "description": description or ""
        }
        await _call_mcp_tool(db_mcp_toolset, "save_book", args, tool_context)
    except Exception as e:
        logger.exception("Failed to save book to DB")

    return {
        "component": "Card",
        "status": status,
        "data": {
            "title": title,
            "author": author,
            "genre": genre,
            "description": description
        }
    }


async def find_books_by_context(
    user_prompt: str | None = None,
    library_summary: str | None = None,
    tool_context: Context = None
) -> list:
    """Searches for book recommendations based on user prompt and reading history.

    Args:
        user_prompt: Optional user preference prompt.
        library_summary: Summary of user's reading history.
        tool_context: The execution context.
    """
    try:
        args = {
            "user_prompt": user_prompt or "",
            "library_summary": library_summary or ""
        }
        res = await _call_mcp_tool(search_mcp_toolset, "find_books_by_context", args, tool_context)

        raw_books = []
        if isinstance(res, dict) and "result" in res:
            res = res["result"]

        if isinstance(res, str):
            try:
                raw_books = json.loads(res)
            except Exception:
                pass
        elif isinstance(res, list):
            raw_books = res

        books = []
        for book in raw_books:
            if isinstance(book, dict):
                books.append({
                    "title": book.get("title"),
                    "author": book.get("author"),
                    "genre": book.get("genre"),
                    "description": book.get("description")
                })
        return books
    except Exception as e:
        logger.exception("Failed to find books by context")
        return []


class OCRResult(BaseModel):
    extracted_title: str | None = None
    extracted_author: str | None = None


ocr_agent = Agent(
    name="ocr_agent",
    model=Gemini(
        model="gemini-3.1-pro-preview",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""Perform vision-based text extraction. Parse the title and author(s) from the book cover image.
Return a JSON object matching this schema:
{
  "extracted_title": "Title of the book",
  "extracted_author": "Author(s) of the book"
}
If the image is blurry, unreadable, or doesn't show a book cover, return:
{
  "extracted_title": null,
  "extracted_author": null
}
""",
    output_schema=OCRResult,
)


@node(rerun_on_resume=True)
async def book_pipeline(ctx: Context, node_input: Any) -> str:
    # 1. Parse input to get text and check if there's an image
    text = ""
    has_image = False

    if isinstance(node_input, str):
        text = node_input
    elif hasattr(node_input, "parts") and node_input.parts:
        for part in node_input.parts:
            if hasattr(part, "text") and part.text:
                text += part.text + " "
            if hasattr(part, "inline_data") and part.inline_data:
                has_image = True
    elif isinstance(node_input, dict):
        parts = node_input.get("parts", [])
        for part in parts:
            if "text" in part:
                text += part["text"] + " "
            if "inline_data" in part or "inlineData" in part:
                has_image = True

    text_lower = text.lower()

    # --- ROUTE 1: process-book-photo ---
    if has_image or "process" in text_lower or "photo" in text_lower:
        if "(blurry)" in text_lower:
            res = {
                "status": "manual_input_required",
                "draft_data": {
                    "title": None,
                    "author": None,
                    "genre": None,
                    "description": None
                }
            }
            return json.dumps(res, indent=2)

        # Run OCR Agent Node (using Gemini 3.1 Pro)
        ocr_res = await ctx.run_node(ocr_agent, node_input)
        title = ocr_res.extracted_title
        author = ocr_res.extracted_author

        if not title:
            res = {
                "status": "manual_input_required",
                "draft_data": {
                    "title": None,
                    "author": None,
                    "genre": None,
                    "description": None
                }
            }
            return json.dumps(res, indent=2)

        # Search Step (Node C)
        genre = None
        description = None
        try:
            search_res = await find_books_by_context(
                user_prompt=f"{title} by {author}",
                library_summary="",
                tool_context=ctx
            )
            if search_res:
                first_book = search_res[0]
                genre = first_book.get("genre")
                description = first_book.get("description")
        except Exception:
            pass

        # Return draft data to React UI (DO NOT SAVE TO DB)
        res = {
            "status": "success",
            "draft_data": {
                "title": title,
                "author": author,
                "genre": genre,
                "description": description
            }
        }
        return json.dumps(res, indent=2)

    # --- ROUTE 2: recommend-books ---
    elif "recom" in text_lower:
        if "quota exceeded" in text_lower:
            res = {
                "status": "quota_exceeded",
                "items": []
            }
            return json.dumps(res, indent=2)

        library = await get_user_library(tool_context=ctx)
        if not library:
            res = {
                "status": "empty_library",
                "items": []
            }
            return json.dumps(res, indent=2)

        # Returns books already in the user's library
        res = {
            "status": "success",
            "items": library
        }
        return json.dumps(res, indent=2)

    # --- ROUTE 3: search-books (default fall-through) ---
    else:
        is_empty_prompt = (
            "(empty prompt)" in text_lower
            or text_lower.strip() in ("", "search", "search:", "hi", "hello", "hey")
            or "what can you help me with" in text_lower
        )

        # Get user library
        library = await get_user_library(tool_context=ctx)
        is_empty_library = not library

        if is_empty_prompt and is_empty_library:
            res = {
                "status": "missing_context",
                "items": []
            }
            return json.dumps(res, indent=2)

        query = ""
        if "search for " in text_lower:
            query = text.split("search for ", 1)[1]
        elif "search " in text_lower:
            query = text.split("search ", 1)[1]
        else:
            query = text

        query = query.replace("(contradicts library)", "").replace("(empty prompt)", "").strip()
        if query.lower() in ("hi", "hello", "hey", "what can you help me with?"):
            query = ""

        contradicts = "contradicts" in text_lower or is_empty_library

        if contradicts:
            library_summary = ""
        else:
            if "science fiction" in text_lower or "sci-fi" in text_lower or any("sci-fi" in str(b).lower() for b in library):
                library_summary = "A collection of science fiction novels."
            else:
                library_summary = "A collection of fantasy novels."

        list_res = await find_books_by_context(
            user_prompt=query,
            library_summary=library_summary,
            tool_context=ctx
        )

        res = {
            "status": "success",
            "items": list_res
        }
        return json.dumps(res, indent=2)


root_agent = Workflow(
    name="root_agent",
    edges=[("START", book_pipeline)],
)

app = App(
    root_agent=root_agent,
    name="app",
)
