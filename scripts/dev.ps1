# Starts the DB MCP server, search MCP server, backend, and frontend
# each in its own PowerShell window so their logs stay visible and separate.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendRoot = Join-Path $ProjectRoot "frontend"

Start-Process powershell -WorkingDirectory $ProjectRoot -ArgumentList `
    '-NoExit', '-Command', 'uv run uvicorn mcp_servers.db_mcp_server:app --host 127.0.0.1 --port 8001'

Start-Process powershell -WorkingDirectory $ProjectRoot -ArgumentList `
    '-NoExit', '-Command', 'uv run uvicorn mcp_servers.search_mcp_server:app --host 127.0.0.1 --port 8002'

Start-Process powershell -WorkingDirectory $ProjectRoot -ArgumentList `
    '-NoExit', '-Command', 'uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000'

Start-Process powershell -WorkingDirectory $FrontendRoot -ArgumentList `
    '-NoExit', '-Command', 'npm run dev'

Write-Host "Started db_mcp_server (8001), search_mcp_server (8002), backend (8000), and frontend in separate windows."
