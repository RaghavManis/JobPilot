# JobPilot — AI-Powered Universal Job Application Agent

## 1. What JobPilot Is
JobPilot is an AI-powered system designed to take a job application URL and intelligently navigate, understand, and fill the application form. It uses LLM reasoning, semantic DOM parsing, RAG personal knowledge retrieval, LangGraph workflow orchestration, and human-in-the-loop controls to automate application submissions safely and generic website-independently.

---

## 2. Architecture Overview
JobPilot maintains a strict separation of concerns:
- **LLM Layer**: Reasoning, field categorization, free-text synthesis, zero-hallucination confidence scoring.
- **RAG & Knowledge System (Phase 2)**: Canonical UserProfile management, document ingestion pipeline, chunking, embeddings provider abstraction, FAISS vector store, evidence retrieval, and EvidenceEvaluator rules.
- **LangGraph Agent Engine (Phase 3)**: Strongly-typed `ApplicationState`, state graph execution nodes, conditional edge routing, confidence partitioning, HITL interrupts, and hardware submission safety locks.
- **Universal Form Automation (Phase 4)**: Playwright execution layer for ARIA custom controls, dynamic/conditional field detection, post-fill DOM re-inspection, multi-page step navigation, and validation error detection.
- **React Frontend Dashboard (Phase 5)**: Interactive user dashboard featuring target URL input, live progress timeline, Human-in-the-Loop review modal, final submission review panel, and activity logs.
- **FastAPI & Async Database**: REST API, session management, SQLite persistence (PostgreSQL ready).

---

## 3. Project Structure
```
jobpilot/
├── .env.example              # Environment variables template
├── .env                      # Local development environment configuration
├── .gitignore                # Git ignore configuration
├── README.md                 # Project documentation and run guide
├── requirements.txt          # Python dependencies
├── backend/                  # FastAPI Application Engine
│   └── app/
│       ├── main.py           # Application entry point, lifespan, & static frontend serving
│       ├── agent/            # LangGraph Workflow Engine (State, Graph, Nodes, ConfidenceEngine)
│       ├── api/              # REST API routers (health, sessions, profile, knowledge, agent)
│       ├── browser/          # Playwright BrowserManager, DOM Inspector, Actions
│       ├── config/           # Pydantic Settings configuration
│       ├── core/             # Logging & custom exception classes
│       ├── database/         # Async SQLAlchemy models & session generator
│       ├── llm/              # LLMProvider interface, Gemini & Mock providers
│       ├── rag/              # RAG Engine: Loader, Chunker, Embeddings, VectorStore, Retriever, Evaluator
│       ├── schemas/          # Pydantic schemas (profile, form, session, agent, rag)
│       └── services/         # SessionService & KnowledgeService
├── frontend/                 # React TypeScript User Interface
│   ├── public/               # Static HTML & Bootstrap CSS assets
│   ├── src/
│   │   ├── App.tsx           # Main App dashboard
│   │   ├── main.tsx          # React DOM entry point
│   │   ├── api/client.ts     # REST API client connecting to FastAPI backend
│   │   └── components/       # UI Components (UrlInputCard, ProgressTimeline, HumanInteractionModal, FinalReviewPanel)
│   ├── package.json
│   └── vite.config.ts
├── docs/                     # Architecture documentation
├── knowledge_base/           # User documents directory (profiles, resumes, experience, projects, answers)
├── scripts/                  # Helper scripts (serve_mock.py)
└── tests/                    # Pytest test suite & local mock single-page & multi-page test forms
```

---

## 4. Setup Instructions

### Prerequisites
- Python 3.10+
- Virtual Environment (`venv`)

### Installation
1. Clone or navigate to the repository directory.
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Install Playwright Chromium browser binary:
   ```bash
   playwright install chromium
   ```

---

## 5. How to Run the Application & Frontend

### 1. Start the FastAPI Backend & Dashboard
```powershell
$env:PYTHONPATH="."
.\venv\Scripts\python -m uvicorn backend.app.main:app --reload --port 8000
```
Open `http://localhost:8000/` in your browser to open the **JobPilot Web Dashboard UI**.

### 2. Start the Local Mock Job Application Form (For Testing)
In a separate terminal window, start the mock application server:
```powershell
.\venv\Scripts\python scripts/serve_mock.py
```
This hosts test application forms at `http://localhost:8001/mock_form.html` and `http://localhost:8001/mock_multipage.html`.

---

## 6. How to Run Tests
Run the automated test suite using `pytest`:
```bash
$env:PYTHONPATH="."
.\venv\Scripts\pytest tests/ -v
```

---

## 7. Current Project Capabilities
- Universal job application URL input and live automation controller.
- Playwright browser execution layer supporting text, dropdowns, radios, checkboxes, file uploads, ARIA controls, and dynamic field revelation.
- Canonical candidate `UserProfile` management & document RAG ingestion pipeline (PDFs & Markdowns with FAISS vector store).
- Zero-hallucination `EvidenceEvaluator` enforcing evidence backing before suggesting answers.
- LangGraph `AgentWorkflowEngine` state graph machine with HITL interrupt breakpoints for login barriers, low-confidence questions, and final review.
- Hardware Submission Safety Lock requiring explicit user approval (`submission_approved == True`) before submitting.
- React TypeScript user dashboard displaying progress timelines, HITL review modals, final review breakdown, and live activity logs.
- Automated 21-test suite passed in 10.93 seconds.
