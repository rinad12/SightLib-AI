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
import random
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
DB_MCP_URL = os.environ.get("DB_MCP_URL", "http://127.0.0.1:8001/sse")
SEARCH_MCP_URL = os.environ.get("SEARCH_MCP_URL", "http://127.0.0.1:8002/sse")

db_mcp_toolset = McpToolset(
    connection_params=SseConnectionParams(
        url=DB_MCP_URL
    ),
    header_provider=library_db_header_provider,
)

search_mcp_toolset = McpToolset(
    connection_params=SseConnectionParams(
        url=SEARCH_MCP_URL
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


def _parse_mcp_result(res: Any) -> Any:
    """Safely extracts and parses JSON/text from an MCP tool call result."""
    if not res:
        return res

    # 1. If it has a 'result' key, extract it (for backwards compatibility)
    if isinstance(res, dict) and "result" in res:
        res = res["result"]

    # 2. If it's a CallToolResult object (having 'content' attribute)
    if hasattr(res, "content") and isinstance(res.content, list):
        for item in res.content:
            if hasattr(item, "text") and item.text:
                try:
                    return json.loads(item.text)
                except Exception:
                    return item.text
            elif isinstance(item, dict) and item.get("text"):
                try:
                    return json.loads(item["text"])
                except Exception:
                    return item["text"]

    # 3. If it's a dict with 'content' list
    if isinstance(res, dict) and "content" in res and isinstance(res["content"], list):
        for item in res["content"]:
            if isinstance(item, dict) and item.get("text"):
                try:
                    return json.loads(item["text"])
                except Exception:
                    return item["text"]
            elif hasattr(item, "text") and item.text:
                try:
                    return json.loads(item.text)
                except Exception:
                    return item.text

    # 4. If it's a list (already parsed or raw content list)
    if isinstance(res, list):
        if len(res) > 0:
            first = res[0]
            if hasattr(first, "text") and first.text:
                try:
                    return json.loads(first.text)
                except Exception:
                    return first.text
            elif isinstance(first, dict) and first.get("text"):
                try:
                    return json.loads(first["text"])
                except Exception:
                    return first["text"]
        return res

    # 5. If it's a string, try loading it as JSON
    if isinstance(res, str):
        try:
            return json.loads(res)
        except Exception:
            return res

    return res


async def get_user_library(tool_context: Context) -> list:
    """Retrieves the list of books in the current user's library.

    Args:
        tool_context: The execution context.
    """
    try:
        res = await _call_mcp_tool(db_mcp_toolset, "get_user_library", {}, tool_context)
        parsed = _parse_mcp_result(res)
        if isinstance(parsed, list):
            return parsed
        return []
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
        parsed = _parse_mcp_result(res)
        if isinstance(parsed, list):
            raw_books = parsed

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


class RecommendedBook(BaseModel):
    title: str
    author: str | None = None
    genre: str | None = None
    description: str | None = None


class RecommendationResult(BaseModel):
    items: list[RecommendedBook] = []


recommend_agent = Agent(
    name="recommend_agent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are a reading assistant picking what the user should read next from books they ALREADY own.

You will be given:
- "shelf": a JSON array of the user's unread/in-progress shelf books (each with title, author, genre, description, status)
- "reading_history": a JSON array of books the user has already finished, for inferring their taste
- "user_preference": an optional description of the mood/genre/theme the user feels like reading right now

Rules:
- Only choose books from the given "shelf" list. Never invent a book and never suggest anything outside the shelf
  — this is a shelf-only recommendation, not a search.
- Copy the "title" field EXACTLY as given (same spelling/casing) for each book you pick.
- If "user_preference" is given, judge it semantically (language, synonyms, mood, themes) against the genre/
  description/title of each shelf book. If NONE of the shelf books genuinely fit the preference, return an empty
  list — do not force a loose match just to return something.
- If "user_preference" is empty/null, use "reading_history" instead: infer the genres/authors/themes the user
  clearly enjoys from what they've already finished, and pick shelf books that best continue that taste.
- Return between 0 and 5 books.

Return JSON matching this schema:
{
  "items": [
    {"title": "...", "author": "...", "genre": "...", "description": "..."}
  ]
}
""",
    output_schema=RecommendationResult,
)


class SearchBooksResult(BaseModel):
    items: list[RecommendedBook] = []


search_agent = Agent(
    name="search_agent",
    model=Gemini(
        model="gemini-3.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    tools=[search_mcp_toolset],
    instruction="""You help a reader discover new books to read next.

You will be given:
- "query": what the user is looking for, in their own words (any language)
- "library_summary": a short description of the kind of books already on their shelf, for context

You have a tool, find_books_by_context, that searches Google Books (arguments: user_prompt, library_summary).
Google Books' search is a literal keyword search, so:
- Turn the user's request into good search keywords yourself before calling the tool (translate to English if
  that gets better results, extract genre/theme/year instead of passing the whole sentence verbatim).
- You may call the tool more than once with different phrasings if the first results look off-topic.
- From the raw search results, KEEP only real, readable books (novels, story collections, well-known nonfiction)
  that someone would actually want to read. DROP "Year's Best..." anthology omnibuses, academic essay collections,
  literary criticism, library/auction catalogs, symposium proceedings, and anything that clearly isn't a
  standalone book, unless the user explicitly asked for that kind of thing.
- Return at most 8 books, best matches first. If nothing good is found, return an empty list.

Return JSON matching this schema:
{
  "items": [
    {"title": "...", "author": "...", "genre": "...", "description": "..."}
  ]
}
""",
    output_schema=SearchBooksResult,
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
        title = ocr_res.get("extracted_title")
        author = ocr_res.get("extracted_author")

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

        # Recommend what to read next: books already on the shelf that
        # haven't been finished yet, not the whole library regardless of status.
        unread = [
            book for book in library
            if isinstance(book, dict) and book.get("status") != "read"
        ]
        if not unread:
            res = {
                "status": "empty_library",
                "items": []
            }
            return json.dumps(res, indent=2)

        # Books already finished, used to infer taste when no preference is given.
        read_books = [
            book for book in library
            if isinstance(book, dict) and book.get("status") == "read"
        ]

        # Optional user preference, e.g. "Recommend some books based on my shelf: dark fantasy"
        preference = ""
        if ":" in text:
            preference = text.split(":", 1)[1].strip()

        if not preference and not read_books:
            # Nothing to go on (no preference, nothing finished yet) - just pick something.
            recommended = [random.choice(unread)]
        else:
            # Let the LLM pick which shelf books match the preference (semantically,
            # across languages/synonyms), or - if no preference - infer taste from
            # reading history, instead of literal substring matching. A legitimate
            # empty result (nothing on the shelf fits the preference) is kept empty
            # on purpose, so the frontend can tell the user nothing matched instead
            # of silently falling back to the whole shelf.
            try:
                prompt = json.dumps({
                    "shelf": unread,
                    "reading_history": read_books,
                    "user_preference": preference or None
                }, indent=2)
                rec_res = await ctx.run_node(recommend_agent, prompt)
                recommended = rec_res.get("items") or []
                if not recommended and not preference:
                    # Empty prompt and the model couldn't infer anything from reading
                    # history either - fall back to a random pick instead of "no match".
                    recommended = [random.choice(unread)]
            except Exception:
                logger.exception("Failed to run recommend_agent")
                recommended = unread  # technical failure only - not a "no match" result

        res = {
            "status": "success",
            "items": recommended
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
            idx = text_lower.index("search for ")
            query = text[idx + len("search for "):]
        elif "search " in text_lower:
            idx = text_lower.index("search ")
            query = text[idx + len("search "):]
        else:
            query = text

        query = query.replace("(contradicts library)", "").replace("(empty prompt)", "").strip()
        if query.lower() in ("hi", "hello", "hey", "what can you help me with?"):
            query = ""

        contradicts = "contradicts" in text_lower or is_empty_library

        if contradicts:
            library_summary = ""
        else:
            genres = sorted({
                book.get("genre") for book in library
                if isinstance(book, dict) and book.get("genre")
            })
            titles = [
                book.get("title") for book in library
                if isinstance(book, dict) and book.get("title")
            ]
            if genres or titles:
                parts = []
                if genres:
                    parts.append(f"Genres on the shelf: {', '.join(genres)}.")
                if titles:
                    parts.append(f"Example titles already owned: {', '.join(titles[:10])}.")
                library_summary = " ".join(parts)
            else:
                library_summary = ""

        # Let the LLM turn the free-form query into good search keywords and
        # filter out anthologies/catalogs/criticism, instead of passing the
        # raw sentence straight to the Google Books keyword search.
        list_res = []
        try:
            prompt = json.dumps({
                "query": query,
                "library_summary": library_summary
            }, indent=2)
            search_res = await ctx.run_node(search_agent, prompt)
            list_res = search_res.get("items") or []
        except Exception:
            logger.exception("Failed to run search_agent")
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
