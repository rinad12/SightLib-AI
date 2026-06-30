# Skill: process-book-photo

## Overview
This skill processes cover photos of books using high-accuracy OCR powered by Gemini 3.1 Pro, queries the contextual web-search-mcp, and saves the book to the user's library using the library-db-mcp.

## Inputs
- `image_bytes`: Base64 encoded book cover image.

## Outputs
Strictly typed JSON object corresponding to the A2UI Card component:
- `component`: "Card"
- `status`: "success" | "manual_input_required" | "partial_data" | "quota_exceeded"
- `data`:
  - `title`: string | null
  - `author`: string | null
  - `genre`: string | null
  - `description`: string | null

## Implementation Rules
- Do NOT write logic in this file yet (stub only).
- Prepare 3+ evaluation cases before implementing logic.
