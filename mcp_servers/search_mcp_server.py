import os
import json
import logging
from fastapi import FastAPI, Request
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
import httpx

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
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("items", []):
                volume_info = item.get("volumeInfo", {})
                title = volume_info.get("title")
                authors = ", ".join(volume_info.get("authors", [])) or "Unknown Author"
                categories = ", ".join(volume_info.get("categories", [])) or "Uncategorized"
                description = volume_info.get("description") or ""

                books.append({
                    "title": title,
                    "author": authors,
                    "genre": categories,
                    "description": description[:300] + "..." if len(description) > 300 else description
                })
    except Exception as e:
        logger.exception("Error querying Google Books API")

    return [TextContent(type="text", text=json.dumps(books, indent=2))]


sse = SseServerTransport("/mcp")


@app.get("/sse")
async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())


@app.post("/mcp")
async def handle_message(request: Request):
    return await sse.handle_post_message(request.scope, request.receive, request._send)
