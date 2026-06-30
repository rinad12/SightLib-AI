# Skill: recommend-books

## Overview
This skill generates personalized book recommendations using Gemini Flash (latest), querying the user's historical reading list from library-db-mcp, summarizing the library, and searching for matching books via find_books_by_context on the web-search-mcp.

## Inputs
- `user_prompt`: Optional user text query (e.g. "I want dark fantasy").

## Outputs
Strictly typed JSON object corresponding to A2UI component (Carousel on success, Card on quota error):
- `component`: "Carousel" | "Card"
- `status`: "success" | "empty_library" | "quota_exceeded"
- `items`: array of recommendation cards (for Carousel)
- `data`: error message payload (for Card)

## Implementation Rules
- Do NOT write logic in this file yet (stub only).
- Prepare 3+ evaluation cases before implementing logic.
