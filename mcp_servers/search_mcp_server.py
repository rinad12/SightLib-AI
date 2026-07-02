import asyncio
import os
import json
import logging
from fastapi import FastAPI, Request
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("search_mcp_server")

app = FastAPI(title="Google Books Search MCP Server")
mcp_server = Server("web-search-mcp")


@mcp_server.list_tools()
async def list_tools():
    return [
        Tool(
            name="find_books_by_context",
            description="Searches Google Books API for new books based on user prompt and library summary.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_prompt": {"type": "string"},
                    "library_summary": {"type": "string"}
                }
            }
        )
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name != "find_books_by_context":
        raise ValueError(f"Unknown tool: {name}")

    user_prompt = arguments.get("user_prompt") or ""
    library_summary = arguments.get("library_summary") or ""

    # Construct Google Books search query
    query = user_prompt
    if not query and library_summary:
        query = library_summary

    if not query:
        return [TextContent(type="text", text="[]")]

    # Call Google Books API
    api_key = os.environ.get("GOOGLE_BOOKS_API_KEY")
    url = "https://www.googleapis.com/books/v1/volumes"
    params = {"q": query, "maxResults": 5}
    if api_key:
        params["key"] = api_key

    books = []
    max_attempts = 3
    try:
        async with httpx.AsyncClient() as client:
            data = None
            for attempt in range(1, max_attempts + 1):
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except httpx.HTTPStatusError as e:
                    # Retry on transient server-side errors (e.g. 503), not on 4xx (bad key/query).
                    if e.response.status_code < 500 or attempt == max_attempts:
                        raise
                    logger.warning(f"Google Books API returned {e.response.status_code}, retrying ({attempt}/{max_attempts})")
                    await asyncio.sleep(0.5 * attempt)
                except httpx.RequestError:
                    if attempt == max_attempts:
                        raise
                    logger.warning(f"Google Books API request failed, retrying ({attempt}/{max_attempts})")
                    await asyncio.sleep(0.5 * attempt)

            for item in (data or {}).get("items", []):
                volume_info = item.get("volumeInfo", {})
                title = volume_info.get("title")
                authors = ", ".join(volume_info.get("authors", [])) or "Unknown Author"
                categories = ", ".join(volume_info.get("categories", [])) or "Uncategorized"
                description = volume_info.get("description") or ""

                books.append({
                    "title": title,
                    "author": authors,
                    "genre": categories,
                    # Full description, untruncated - callers (LLM agents) are responsible for
                    # writing an appropriately sized synopsis instead of a blind character cut.
                    "description": description
                })
    except Exception as e:
        logger.exception("Error querying Google Books API")

    return [TextContent(type="text", text=json.dumps(books, indent=2))]


from fastapi import Response

class EmptyResponse(Response):
    async def __call__(self, scope, receive, send):
        pass

sse = SseServerTransport("/mcp")


@app.get("/sse")
async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())


@app.post("/mcp")
async def handle_message(request: Request):
    await sse.handle_post_message(request.scope, request.receive, request._send)
    return EmptyResponse()
