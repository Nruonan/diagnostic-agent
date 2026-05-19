# AI Diagnostic Agent Design

## Scope

Build a complete, runnable backend project for a distributed-system fault diagnosis automation framework.

The implementation is based only on `D:\py\agent.md` and the confirmed user constraints:

- Use DashScope as the LLM provider.
- Do not use Claude API.
- Generate a fully usable project, not a project made mostly of placeholder interfaces.
- The project must run end to end with built-in sample data.
- Real enterprise data sources can be connected through configurable HTTP adapters.

## Goals

- Accept a user fault description and produce a root-cause diagnosis report.
- Implement a main agent that coordinates specialized sub-agents.
- Implement four sub-agents:
  - task planning agent
  - error analysis agent
  - slow SQL analysis agent
  - root cause analysis agent
- Implement the workflow from the source document:
  - initialize diagnosis
  - create a task plan
  - collect and analyze errors and slow SQL in parallel
  - synthesize a root cause
  - request human input if confidence is too low
  - produce a final report
- Provide FastAPI endpoints for diagnosis lifecycle and reports.
- Provide built-in sample data so the system is usable without ELK, XXL-Job, slow query platform, trace platform, or code repository APIs.

## Non-Goals

- Do not implement a frontend.
- Do not implement provider fallback beyond DashScope.
- Do not depend on undocumented internal company APIs.
- Do not fabricate a high-confidence root cause when available evidence is insufficient.

## Architecture

The project will be generated as an independent Python backend under:

```text
D:\py\ai-diagnostic-agent
```

Main layers:

- `app.api`: FastAPI routes for diagnosis and reports.
- `app.agents`: main agent and four specialized sub-agents.
- `app.dashscope_client`: DashScope HTTP client and structured JSON response handling.
- `app.workflow`: workflow engine, state transitions, and confidence handling.
- `app.datasources`: sample adapter and generic HTTP adapter.
- `app.reports`: JSON and Markdown report generation.
- `app.schemas`: request, response, agent, evidence, and report models.
- `app.storage`: local JSON-backed diagnosis storage.
- `sample_data`: runnable local data for logs, XXL-Job records, slow SQL, traces, and code snippets.

## Runtime Flow

1. User submits a fault description to `POST /api/v1/diagnoses`.
2. The main agent starts a diagnosis session.
3. The planning agent creates a structured task plan.
4. The workflow engine collects data through the configured data source.
5. Error analysis and slow SQL analysis run concurrently.
6. The root cause agent synthesizes all prior outputs and code or trace evidence.
7. If confidence is below the configured threshold, the diagnosis status becomes `need_user_input`.
8. User can add missing information through `POST /api/v1/diagnoses/{diagnosis_id}/input`.
9. The workflow resumes and produces a final report.
10. Reports are available as structured JSON and Markdown.

## API

- `GET /health`
  - Returns service health and basic runtime configuration status.
- `POST /api/v1/diagnoses`
  - Starts a diagnosis from a fault description.
- `GET /api/v1/diagnoses/{diagnosis_id}`
  - Returns diagnosis status, intermediate outputs, and report when available.
- `POST /api/v1/diagnoses/{diagnosis_id}/input`
  - Adds human input when the workflow needs clarification.
- `GET /api/v1/reports/{diagnosis_id}`
  - Returns final report JSON.
- `GET /api/v1/reports/{diagnosis_id}/markdown`
  - Returns final report as Markdown text.

## DashScope Integration

The project will call DashScope through a dedicated client.

Configuration:

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_MODEL`
- `DASHSCOPE_BASE_URL`
- `DASHSCOPE_TIMEOUT_SECONDS`

Agent behavior:

- Every agent builds a role-specific prompt.
- Every agent asks DashScope for structured JSON.
- Every agent validates the JSON against Pydantic models.
- Invalid JSON, timeout, network failure, or missing API key becomes a traceable diagnosis error.
- Missing API key does not prevent service startup, but diagnosis requests return a clear configuration error.

## Data Sources

Two data source modes are supported:

- `sample`
  - Reads local files from `sample_data`.
  - Default mode.
  - Guarantees the backend can run an end-to-end diagnosis without external systems.
- `http`
  - Uses configured HTTP endpoints for external systems.
  - Supports ELK-style logs, XXL-Job records, slow query records, traces, and code snippets.
  - If an endpoint fails, the error is recorded as evidence and the workflow either continues with available data or requests user input.

Configuration:

- `DATA_SOURCE_MODE=sample|http`
- `ELK_API_URL`
- `XXL_JOB_API_URL`
- `SLOW_QUERY_API_URL`
- `TRACE_API_URL`
- `GIT_CODE_API_URL`

## Project Structure

```text
ai-diagnostic-agent/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   ├── agents/
│   ├── workflow/
│   ├── datasources/
│   ├── dashscope_client/
│   ├── reports/
│   ├── schemas/
│   └── storage/
├── sample_data/
│   ├── logs.json
│   ├── xxl_jobs.json
│   ├── slow_queries.json
│   ├── traces.json
│   └── code_snippets.json
├── docs/
├── .env.example
├── Dockerfile
├── pyproject.toml
└── README.md
```

## Error Handling

- Agent timeout is configurable through `AGENT_TIMEOUT_SECONDS`.
- Low confidence is controlled by `LOW_CONFIDENCE_THRESHOLD`.
- Data source failures are recorded in the diagnosis state.
- Invalid LLM output is reported with agent name, raw response excerpt, and validation error.
- Final reports include evidence and confidence instead of only a conclusion.

## Acceptance Criteria

- The FastAPI service can start after dependency installation.
- With `DASHSCOPE_API_KEY` configured and default sample data mode, a user can complete an end-to-end diagnosis.
- Without `DASHSCOPE_API_KEY`, the service still starts and diagnosis requests return a clear configuration error.
- Each sub-agent contains real prompt construction, DashScope invocation, JSON parsing, schema validation, and error handling.
- The workflow engine implements planning, concurrent error and slow SQL analysis, root cause synthesis, and human clarification for low confidence.
- The sample data path is complete and usable.
- The HTTP data source adapter is functional and configurable, not an empty stub.
- Final reports contain root cause, confidence, evidence, fix steps, and Mermaid timeline or call-chain text.

## Rollback

The project is generated in an isolated directory:

```text
D:\py\ai-diagnostic-agent
```

Rollback is deleting that directory. No existing project is modified.

