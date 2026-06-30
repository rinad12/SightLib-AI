# Skill: search-books

## Overview
This skill performs a contextual internet search for new books that are not in the user's library. It analyzes the user prompt and the user's library context, queries library-db-mcp, and searches online using find_books_by_context on the web-search-mcp.

## Inputs
- `user_prompt`: Optional user text search query (e.g. "I want dark fantasy").

## Outputs
Strictly typed JSON object corresponding to A2UI component (List on success, Card on short-circuit or error):
- `component`: "List" | "Card"
- `status`: "success" | "no_context"
- `items`: array of book cards (for List)
- `data`: error or message payload (for Card)

## Implementation Rules
- If the user's library is empty, or the prompt contradicts library, ignore library and search only using user_prompt.
- If prompt is empty, search relying solely on library summary.
- If both are empty, short-circuit, do not call search tool, and return A2UI Card with status no_context.
