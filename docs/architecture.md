# JobPilot Architecture Documentation - Phase 1

## Overview
JobPilot is an AI-powered universal job application automation agent. Phase 1 establishes the core modular foundation, configuration, Pydantic schemas, database models, LLM provider abstraction, Playwright browser manager, DOM inspection engine, synthetic `data-jp-id` attribute injection, and execution action layer.

## Component Responsibilities

1. **FastAPI Application (`backend/app/main.py`)**:
   - Web application entry point, lifecycle management (`lifespan`), CORS, exception handlers, and routing.

2. **Configuration (`backend/app/config/settings.py`)**:
   - Environment-variable backed settings via `pydantic-settings`. Supports `.env` loading for secrets and parameters.

3. **Database Layer (`backend/app/database/`)**:
   - Async SQLAlchemy ORM connected to SQLite (`jobpilot.db`) using `aiosqlite`. Portable to PostgreSQL in future phases.

4. **LLM Provider Abstraction (`backend/app/llm/`)**:
   - `LLMProvider` interface defining `generate` and `generate_structured`.
   - `GeminiLLMProvider`: Production Google Gemini API implementation using `google-genai` SDK.
   - `MockLLMProvider`: Deterministic offline implementation for unit tests and local execution.

5. **Browser Automation Layer (`backend/app/browser/`)**:
   - `BrowserManager`: Manages Playwright browser runtime, launching isolated `BrowserContext` and `Page` objects per session.
   - `DOMInspector`: Injects synthetic `data-jp-id="field_xxx"` attributes safely into interactive DOM elements and returns compact `FormPage` / `FormField` representations.
   - `BrowserActions`: Executes low-level page interactions (`fill_text`, `click`, `select_option`, `check`, `upload_file`) by targeting synthetic `data-jp-id` selectors.

6. **Session Service (`backend/app/services/session_service.py`)**:
   - Coordinates session state between database models (`ApplicationSessionModel`), Playwright contexts, and structured event logs (`AgentEventModel`).

7. **Local Mock Form (`tests/mock_form.html`)**:
   - Standardized local HTML application form used for reproducible testing of form detection, field mapping, action execution, and navigation.
