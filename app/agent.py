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

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

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
    format: str = "Carousel",
    tool_context: Context = None
) -> dict:
    """Searches for book recommendations based on user prompt and reading history.

    Args:
        user_prompt: Optional user preference prompt.
        library_summary: Summary of user's reading history.
        format: Output component format ("Carousel" or "List").
        tool_context: The execution context.
    """
    items = []
    status = "success"

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

        for book in raw_books:
            if isinstance(book, dict):
                book_data = {
                    "title": book.get("title"),
                    "author": book.get("author"),
                    "genre": book.get("genre"),
                    "description": book.get("description")
                }
                if format == "List":
                    items.append(book_data)
                else:
                    items.append({
                        "component": "Card",
                        "status": "success",
                        "data": book_data
                    })
    except Exception as e:
        logger.exception("Failed to find books by context")

    return {
        "component": format,
        "status": status,
        "items": items
    }


INSTRUCTION = (
    "You are a headless automated book pipeline agent. You react to triggers and return strictly typed A2UI JSON payloads.\n"
    "Your final response MUST be a valid JSON object matching the A2UI specifications (either a Card, Carousel, or List component) with no additional text or conversational wrapper.\n\n"
    "CRITICAL RULES:\n"
    "1. Handling OCR Processing (process-book-photo):\n"
    "   - If the user prompt indicates a blurry or unreadable cover photo (e.g. prompt contains '(blurry)'), or if the OCR yields no text, output the A2UI Card with status 'manual_input_required' directly:\n"
    "     {\n"
    "       \"component\": \"Card\",\n"
    "       \"status\": \"manual_input_required\",\n"
    "       \"data\": {\n"
    "         \"title\": null,\n"
    "         \"author\": null,\n"
    "         \"genre\": null,\n"
    "         \"description\": null\n"
    "       }\n"
    "     }\n"
    "     Do not call any tools in this case.\n"
    "   - Otherwise, extract the title and author from the image cover. Then call find_books_by_context to enrich the book metadata (genre and description). If find_books_by_context yields no results (not found online), pass null for genre and description. Finally, call the save_book tool. Output the JSON object returned by save_book word-for-word as your final response.\n\n"
    "2. Handling Recommendations (recommend-books):\n"
    "   - If the user prompt indicates quota limits are exceeded (e.g. contains '(quota exceeded)'), output the quota error A2UI Card directly:\n"
    "     {\n"
    "       \"component\": \"Card\",\n"
    "       \"status\": \"quota_exceeded\",\n"
    "       \"data\": {\n"
    "         \"title\": null,\n"
    "         \"author\": null,\n"
    "         \"genre\": null,\n"
    "         \"description\": \"Daily recommendation limit reached. Please try again tomorrow.\"\n"
    "       }\n"
    "     }\n"
    "     Do not call any tools.\n"
    "   - Otherwise, call get_user_library. If the user library is empty (returns an empty list or nothing), output the fallback Carousel with status 'empty_library' containing the universal bestsellers: 'To Kill a Mockingbird' by Harper Lee, '1984' by George Orwell, and 'The Great Gatsby' by F. Scott Fitzgerald. Do not call find_books_by_context.\n"
    "   - If get_user_library returns books, generate a concise library summary, then call find_books_by_context. Output the JSON object returned by find_books_by_context word-for-word as your final response.\n\n"
    "3. Handling Contextual Internet Search (search-books):\n"
    "   - If the prompt indicates BOTH the search query is empty AND the user's library is empty (e.g. prompt contains 'Search (empty prompt, empty library)'), or both are empty, the agent must short-circuit. Output the A2UI Card with status 'no_context' directly:\n"
    "     {\n"
    "       \"component\": \"Card\",\n"
    "       \"status\": \"no_context\",\n"
    "       \"data\": {\n"
    "         \"title\": null,\n"
    "         \"author\": null,\n"
    "         \"genre\": null,\n"
    "         \"description\": \"Please enter a search term or add books to your library first.\"\n"
    "       }\n"
    "     }\n"
    "     Do not call any tools in this case.\n"
    "   - Otherwise, call get_user_library.\n"
    "   - If get_user_library returns an empty list, OR if the user prompt strongly contradicts the library context (e.g. library contains Sci-Fi but prompt is 'Search for cooking recipes (contradicts library)'), ignore the library context (set library_summary to ''). Extract the search topic (e.g. 'cooking recipes'), then call find_books_by_context with user_prompt=topic, library_summary='', and format='List'. Output the JSON object returned by find_books_by_context word-for-word.\n"
    "   - If the user prompt is empty or indicates no search term (e.g. contains 'Search (empty prompt)'), rely solely on the library context. Generate a concise library summary (e.g. 'A collection of science fiction novels.'), then call find_books_by_context with user_prompt='', library_summary=summary, and format='List'. Output the JSON object returned by find_books_by_context word-for-word.\n"
    "   - Otherwise, generate a library summary (e.g. 'A collection of fantasy novels.'), extract the search query (e.g. 'fantasy books' from 'Search for fantasy books'), and call find_books_by_context with user_prompt=query, library_summary=summary, and format='List'. Output the JSON response returned by find_books_by_context word-for-word."
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=INSTRUCTION,
    tools=[get_user_library, save_book, find_books_by_context],
)

app = App(
    root_agent=root_agent,
    name="app",
)
