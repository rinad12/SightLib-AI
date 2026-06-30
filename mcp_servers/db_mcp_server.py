import os
import json
import logging
import uuid
import contextvars
from fastapi import FastAPI, Request
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
import asyncpg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_mcp_server")

app = FastAPI(title="Library DB MCP Server")
mcp_server = Server("library-db-mcp")

# ContextVar to track HTTP headers for user isolation
request_headers = contextvars.ContextVar("request_headers", default={})


async def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return await asyncpg.connect(db_url)

    return await asyncpg.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASS", "postgres"),
        database=os.environ.get("DB_NAME", "gridshelf"),
        port=os.environ.get("DB_PORT", "5432")
    )


@mcp_server.list_tools()
async def list_tools():
    return [
        Tool(
            name="get_user_library",
            description="Reads and returns the current user's library books.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="save_book",
            description="Saves or updates a book in the library and links it to the user.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "genre": {"type": "string"},
                    "description": {"type": "string"}
                },
                "required": ["title", "author"]
            }
        )
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    headers = request_headers.get()
    user_id = headers.get("x-user-id") or headers.get("X-User-ID") or "default-user"

    try:
        conn = await get_db_connection()
    except Exception as e:
        logger.exception("Failed to connect to database")
        return [TextContent(type="text", text=f"Error connecting to database: {str(e)}")]

    try:
        if name == "get_user_library":
            query = """
                SELECT b.title, b.author, b.genre, b.description 
                FROM books b
                JOIN user_library ul ON b.id = ul.book_id
                WHERE ul.user_id = $1::uuid
            """
            # If user_id is not a valid UUID, use a namespace UUID or standard UUID
            try:
                user_uuid = uuid.UUID(user_id)
            except ValueError:
                # Fallback to a stable UUID generated from user_id string
                user_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, user_id)

            rows = await conn.fetch(query, user_uuid)
            books = [
                {
                    "title": r["title"],
                    "author": r["author"],
                    "genre": r["genre"],
                    "description": r["description"]
                }
                for r in rows
            ]
            return [TextContent(type="text", text=json.dumps(books, indent=2))]

        elif name == "save_book":
            title = arguments.get("title")
            author = arguments.get("author")
            genre = arguments.get("genre") or ""
            description = arguments.get("description") or ""

            try:
                user_uuid = uuid.UUID(user_id)
            except ValueError:
                user_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, user_id)

            # Check if book already exists in books table
            book_row = await conn.fetchrow(
                "SELECT id FROM books WHERE title = $1 AND author = $2",
                title, author
            )

            if book_row:
                book_uuid = book_row["id"]
                # Update metadata if provided and currently empty
                await conn.execute(
                    "UPDATE books SET genre = COALESCE(NULLIF(genre, ''), $1), description = COALESCE(NULLIF(description, ''), $2) WHERE id = $3",
                    genre, description, book_uuid
                )
            else:
                book_uuid = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO books (id, title, author, genre, description) VALUES ($1, $2, $3, $4, $5)",
                    book_uuid, title, author, genre, description
                )

            # Link to user_library if not already linked
            link_row = await conn.fetchrow(
                "SELECT id FROM user_library WHERE user_id = $1 AND book_id = $2",
                user_uuid, book_uuid
            )
            if not link_row:
                link_uuid = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO user_library (id, user_id, book_id, status, added_at) VALUES ($1, $2, $3, 'unread', NOW())",
                    link_uuid, user_uuid, book_uuid
                )

            return [TextContent(type="text", text="Book saved successfully")]

        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        logger.exception("Error executing MCP tool call")
        return [TextContent(type="text", text=f"Error executing tool: {str(e)}")]
    finally:
        await conn.close()


sse = SseServerTransport("/mcp")


@app.get("/sse")
async def handle_sse(request: Request):
    request_headers.set(dict(request.headers))
    async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())


@app.post("/message")
async def handle_message(request: Request):
    request_headers.set(dict(request.headers))
    return await sse.handle_post_message(request.scope, request.receive, request._send)
