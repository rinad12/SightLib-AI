# Coding Agent Guide

## Prerequisites

Install the CLI (one-time):
```bash
uv tool install google-agents-cli
```

---

## Development Phases

### Phase 1: Understand Requirements
Before writing any code, understand the project's requirements, constraints, and success criteria.

### Phase 2: Build and Implement
Implement agent logic in `app/`. Use `agents-cli playground` for interactive testing. Iterate based on user feedback.

### Phase 3: The Evaluation Loop (Main Iteration Phase)
Start with 1-2 eval cases, run `agents-cli eval generate`, then `agents-cli eval grade`, iterate by making changes and rerunning both commands until satisfied. Expect 5-10+ iterations. Once you have a baseline, reach for `agents-cli eval compare` (regression diffs), `agents-cli eval analyze` (cluster failure modes), and `agents-cli eval optimize` (auto-tune prompts). See the **Evaluation Guide** for metrics, dataset schema, LLM-as-judge config, and common gotchas.

### Phase 4: Pre-Deployment Tests
Run `uv run pytest tests/unit tests/integration`. Fix issues until all tests pass.

### Phase 5: Deploy to Dev
**Requires explicit human approval.** Run `agents-cli deploy` only after user confirms. See the **Deployment Guide** for details.

### Phase 6: Production Deployment
Ask the user: Option A (simple single-project) or Option B (full CI/CD pipeline with `agents-cli infra cicd`).

## Development Commands

| Command | Purpose |
|---------|---------|
| `agents-cli playground` | Interactive local testing |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests |
| `agents-cli eval dataset synthesize` | Synthesize multi-turn eval scenarios for your agent |
| `agents-cli eval generate` | Run agent on eval dataset, produce traces |
| `agents-cli eval grade` | Run agent evaluations on the traces |
| `agents-cli eval compare` | Compare two grade-results files (regression check) |
| `agents-cli eval analyze` | Cluster failure modes from grade results |
| `agents-cli eval metric list` | List built-in metrics available in the SDK |
| `agents-cli eval optimize` | Auto-tune agent prompts using eval data |
| `agents-cli lint` | Check code quality |
| `agents-cli infra single-project` | Set up project infrastructure (Terraform) |
| `agents-cli deploy` | Deploy to dev |
| `agents-cli scaffold enhance` | Add deployment target or CI/CD to project |
| `agents-cli scaffold upgrade` | Upgrade project to latest version |

---

## Operational Guidelines for Coding Agents

- **Code preservation**: Only modify code directly targeted by the user's request. Preserve all surrounding code, config values (e.g., `model`), comments, and formatting.
- **NEVER change the model** unless explicitly asked.
- **Model 404 errors**: Fix `GOOGLE_CLOUD_LOCATION` (e.g., `global` instead of `us-east1`), not the model name.
- **ADK tool imports**: Import the tool instance, not the module: `from google.adk.tools.load_web_page import load_web_page`
- **Run Python with `uv`**: `uv run python script.py`. Run `agents-cli install` first.
- **Stop on repeated errors**: If the same error appears 3+ times, fix the root cause instead of retrying.
- **Terraform conflicts** (Error 409): Use `terraform import` instead of retrying creation.

---

## SightLib-AI Global Rules & Architecture Constraints

### 1. Context and Business Logic (Headless Book Pipeline)
- The system is an automated headless agent pipeline without a user-facing chat interface.
- The agent reacts exclusively to hard triggers (file uploads, button clicks).
- The agent must always return strictly typed JSON objects corresponding to frontend components (A2UI: Card, Carousel, List).

### 2. Security & Authentication (User ID Isolation)
- User registration and authorization are handled via Google Auth.
- **User ID Isolation (CRITICAL):** The LLM agent **never** receives the User ID in plain text and **never** passes it to tools (MCP servers). The User ID is injected strictly at the backend/infrastructure layer (headers or session context) by the gateway.
- **SQL Injection Protection:** The agent **must not** generate or execute raw SQL queries. Database interaction is strictly mediated by the custom `library-db-mcp` exposing predefined, secure functions.

### 3. Usage Limits & Policy Server (Structural Gating)
- Photo uploads (`process-book-photo`): Max 3 photos/day and 10 photos/month per user.
- Recommendations (`recommend-books`): Max 5 requests/day per user.
- The Policy Server checks limits before invoking the agent. If exceeded, returns an A2UI Card notification immediately without invoking the LLM or consuming tokens.

### 4. Model Designations
- **Gemini 3.1 Pro:** Used in `process-book-photo` for high-accuracy OCR on book covers.
- **Gemini Flash (latest):** Used in `recommend-books` for fast, cost-effective recommendation generation.

### 5. Evaluation-Driven Development & BDD
- **MANDATORY:** Generate at least 3 JSON evaluation cases (eval cases) for each skill BEFORE writing their logic.
- Handle OCR failures (`process-book-photo`): blur -> return A2UI Card with `status: manual_input_required` and empty fields.
- Handle online search failure: save only recognized author/title to DB with description as `null`, return Card with a partial data warning.
- Handle empty libraries (`recommend-books`): fallback to Carousel with universal bestsellers.
- Handle quota limit failures.

### 6. Skill Distribution
- Distribute skill configurations and logic into separate folders: `.agent/skills/process-book-photo/SKILL.md` and `.agent/skills/recommend-books/SKILL.md`.

