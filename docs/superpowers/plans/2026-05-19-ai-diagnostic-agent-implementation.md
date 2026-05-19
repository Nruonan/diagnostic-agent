# AI Diagnostic Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete FastAPI backend that runs a DashScope-powered distributed-system fault diagnosis workflow.

**Architecture:** The backend is a small layered Python service. FastAPI exposes diagnosis and report APIs, a workflow engine coordinates one main agent and four sub-agents, the DashScope client handles OpenAI-compatible chat completions, data sources support both sample files and configurable HTTP endpoints, and local JSON storage keeps diagnosis sessions inspectable.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, pydantic-settings, httpx, uvicorn, DashScope OpenAI-compatible Chat API.

---

## File Structure

- `app/main.py`: FastAPI app creation and router registration.
- `app/config.py`: environment-based settings and validation helpers.
- `app/api/routes.py`: health, diagnosis lifecycle, and report endpoints.
- `app/dashscope_client/client.py`: DashScope HTTP client, JSON parsing, and error types.
- `app/schemas/*.py`: Pydantic contracts for diagnoses, agents, data sources, and reports.
- `app/datasources/*.py`: sample data adapter, HTTP adapter, and adapter factory.
- `app/agents/*.py`: base agent, planning agent, error analysis agent, slow SQL agent, root cause agent, and main coordinator.
- `app/workflow/engine.py`: stateful end-to-end diagnosis workflow.
- `app/reports/generator.py`: JSON and Markdown report rendering.
- `app/storage/json_store.py`: local JSON-backed diagnosis persistence.
- `sample_data/*.json`: complete runnable data set.
- `.env.example`, `pyproject.toml`, `Dockerfile`, `README.md`: project operations files.

## Constraints

- Do not use Claude API or Claude dependencies.
- Do not generate automated test files.
- Do not automatically compile, run the app, or start a server.
- Keep the project runnable with only sample data plus a valid DashScope API key.
- Make missing DashScope configuration a clear runtime diagnosis error, not a startup failure.

---

### Task 1: Project Metadata And Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `Dockerfile`
- Create: `README.md`
- Create: `app/__init__.py`
- Create: `app/config.py`

- [ ] **Step 1: Create package metadata and dependencies**

Create `pyproject.toml` with package metadata and runtime dependencies: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `httpx`, and `python-dotenv`.

- [ ] **Step 2: Create environment and ignore files**

Create `.env.example` with DashScope, data source, storage, timeout, and confidence settings. Create `.gitignore` for Python cache, virtual environments, local `.env`, and generated runtime storage.

- [ ] **Step 3: Create settings model**

Create `app/config.py` with a `Settings` class exposing all environment variables from the design and helper methods `dashscope_configured()` and `sample_data_path()`.

- [ ] **Step 4: Create README and Dockerfile**

Document setup, configuration, API examples, manual verification steps, and rollback. Create a Dockerfile that installs the package and starts uvicorn.

### Task 2: Schemas

**Files:**
- Create: `app/schemas/__init__.py`
- Create: `app/schemas/common.py`
- Create: `app/schemas/data.py`
- Create: `app/schemas/agents.py`
- Create: `app/schemas/diagnosis.py`
- Create: `app/schemas/reports.py`

- [ ] **Step 1: Create common and data models**

Define `DataSourceError`, `LogRecord`, `JobRecord`, `SlowQueryRecord`, `TraceSpan`, `CodeSnippet`, and `CollectedData`.

- [ ] **Step 2: Create agent output models**

Define `TaskItem`, `PlanningOutput`, `ErrorItem`, `ErrorAnalysisOutput`, `SlowQueryFinding`, `SlowSqlAnalysisOutput`, and `RootCauseOutput`.

- [ ] **Step 3: Create diagnosis and report models**

Define request/response models, diagnosis status enum, session state, human input request, and report response types.

### Task 3: DashScope Client

**Files:**
- Create: `app/dashscope_client/__init__.py`
- Create: `app/dashscope_client/client.py`

- [ ] **Step 1: Implement errors and request contract**

Define `DashScopeConfigurationError`, `DashScopeRequestError`, and `DashScopeResponseError`.

- [ ] **Step 2: Implement JSON chat completion**

Implement `complete_json(system_prompt, user_payload, response_model)` using the OpenAI-compatible DashScope endpoint and Pydantic validation.

- [ ] **Step 3: Add response extraction safeguards**

Accept JSON in plain content or fenced code blocks, reject empty content, and surface validation errors with a raw response excerpt.

### Task 4: Data Sources

**Files:**
- Create: `app/datasources/__init__.py`
- Create: `app/datasources/base.py`
- Create: `app/datasources/sample.py`
- Create: `app/datasources/http.py`
- Create: `sample_data/logs.json`
- Create: `sample_data/xxl_jobs.json`
- Create: `sample_data/slow_queries.json`
- Create: `sample_data/traces.json`
- Create: `sample_data/code_snippets.json`

- [ ] **Step 1: Implement data source interface**

Define an async `DataSource` protocol with `collect(fault_description, service_hint=None) -> CollectedData`.

- [ ] **Step 2: Implement sample adapter**

Load all sample JSON files, validate them into schema models, and return `CollectedData`.

- [ ] **Step 3: Implement HTTP adapter**

Fetch configured URLs with query parameters, validate each response, record per-source failures, and continue with available data.

- [ ] **Step 4: Add complete sample data**

Create sample records that produce a coherent login timeout diagnosis involving logs, XXL-Job retries, a slow SQL query, traces, and a code snippet.

### Task 5: Agents

**Files:**
- Create: `app/agents/__init__.py`
- Create: `app/agents/base.py`
- Create: `app/agents/planning.py`
- Create: `app/agents/error_analysis.py`
- Create: `app/agents/slow_sql.py`
- Create: `app/agents/root_cause.py`
- Create: `app/agents/main_agent.py`

- [ ] **Step 1: Implement base agent**

Create a focused base class that stores a DashScope client, agent name, and timeout helper.

- [ ] **Step 2: Implement planning agent**

Build the planning prompt from `agent.md` behavior and return `PlanningOutput`.

- [ ] **Step 3: Implement error analysis agent**

Analyze log and job records, require timeline, suspects, and error list in JSON output.

- [ ] **Step 4: Implement slow SQL agent**

Analyze slow query records and require bottlenecks plus optimizations in JSON output.

- [ ] **Step 5: Implement root cause agent**

Synthesize previous outputs plus traces and code snippets, require confidence, evidence, fix steps, and Mermaid output.

- [ ] **Step 6: Implement main agent factory**

Wire all specialized agents for workflow use.

### Task 6: Workflow, Storage, Reports, And API

**Files:**
- Create: `app/workflow/__init__.py`
- Create: `app/workflow/engine.py`
- Create: `app/storage/__init__.py`
- Create: `app/storage/json_store.py`
- Create: `app/reports/__init__.py`
- Create: `app/reports/generator.py`
- Create: `app/api/__init__.py`
- Create: `app/api/routes.py`
- Create: `app/main.py`

- [ ] **Step 1: Implement JSON storage**

Persist each diagnosis session to `.runtime/diagnoses/{diagnosis_id}.json`.

- [ ] **Step 2: Implement report generator**

Render report JSON and Markdown from the final diagnosis state.

- [ ] **Step 3: Implement workflow engine**

Create diagnosis sessions, execute planning, collect data, run error and SQL agents concurrently, run root cause analysis, handle low confidence, and resume after human input.

- [ ] **Step 4: Implement API routes**

Expose health, create diagnosis, get diagnosis, submit human input, get report JSON, and get report Markdown endpoints.

- [ ] **Step 5: Implement app entry point**

Create FastAPI app, load settings, instantiate dependencies, and include the router.

### Task 7: Manual Verification Package

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add manual verification commands**

Document how to install, configure `DASHSCOPE_API_KEY`, start the service manually, create a diagnosis with curl, inspect report JSON, and inspect Markdown.

- [ ] **Step 2: Add no-key verification**

Document the expected response when `DASHSCOPE_API_KEY` is missing.

- [ ] **Step 3: Add rollback steps**

Document that deleting `D:\py\ai-diagnostic-agent` rolls back the generated project.

## Self-Review

- Spec coverage: The plan covers DashScope integration, FastAPI APIs, four agents, workflow, sample and HTTP data sources, reports, local storage, configuration, and rollback.
- Placeholder scan: The plan intentionally avoids deferred implementation language. HTTP adapter is required to perform real configurable requests and validation.
- Type consistency: Schema names are introduced before client, data source, agent, workflow, and API tasks that consume them.
- User constraints: The plan avoids automated test files and automatic compile/run steps.

