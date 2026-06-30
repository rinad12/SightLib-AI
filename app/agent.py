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

_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import SseConnectionParams


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


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="You are a helpful AI assistant designed to provide accurate and useful information.",
    tools=[db_mcp_toolset, search_mcp_toolset],
)

app = App(
    root_agent=root_agent,
    name="app",
)
