# AI Diagnostic Agent

DashScope-powered backend for distributed-system fault diagnosis automation.

The project implements the workflow described in `D:\py\agent.md`: a main agent coordinates task planning, error analysis, slow SQL analysis, and root cause analysis, then returns a structured report with evidence and fix steps.

## Requirements

- Python 3.10+
- A DashScope API key

## Configuration

Copy `.env.example` to `.env` and set:

```env
DASHSCOPE_API_KEY=your-key
DASHSCOPE_MODEL=qwen-plus
DATA_SOURCE_MODE=sample
```

`DATA_SOURCE_MODE=sample` uses the included data under `sample_data/`.

`DATA_SOURCE_MODE=http` uses the configured URLs:

- `ELK_API_URL`
- `XXL_JOB_API_URL`
- `SLOW_QUERY_API_URL`
- `TRACE_API_URL`
- `GIT_CODE_API_URL`

Each HTTP endpoint receives query parameters:

- `fault_description`
- `service_hint` when provided

Each endpoint may return a JSON array directly, or an object with one of these array fields:

- `items`
- `data`
- `results`
- the source name, such as `elk` or `trace`

Records are validated before they enter the workflow. Invalid records are preserved as data source errors in the diagnosis state.

## API

- `GET /health`
- `POST /api/v1/diagnoses`
- `GET /api/v1/diagnoses/{diagnosis_id}`
- `POST /api/v1/diagnoses/{diagnosis_id}/input`
- `GET /api/v1/reports/{diagnosis_id}`
- `GET /api/v1/reports/{diagnosis_id}/markdown`

## Manual Run

Install dependencies:

```bash
pip install -e .
```

Start the service manually:

```bash
uvicorn app.main:app --reload --port 8000
```

Create a diagnosis:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/diagnoses ^
  -H "Content-Type: application/json" ^
  -d "{\"fault_description\":\"登录接口响应超时，用户反馈下单前认证失败\"}"
```

Fetch a report:

```bash
curl http://127.0.0.1:8000/api/v1/reports/{diagnosis_id}
curl http://127.0.0.1:8000/api/v1/reports/{diagnosis_id}/markdown
```

If a diagnosis returns `need_user_input`, add the requested information:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/diagnoses/{diagnosis_id}/input ^
  -H "Content-Type: application/json" ^
  -d "{\"content\":\"故障窗口是 2026-05-19 09:58 到 10:05，最近变更是 user_profile 查询新增排序。\"}"
```

## Sample Data Scenario

The built-in sample data describes this coherent incident:

- `gateway-api` login requests time out.
- `user-service` reports database timeout.
- `sync_user_profile_cache` XXL-Job fails and retries.
- A `user_profile` query scans more than one million rows.
- Trace spans connect gateway, user service, and the slow profile query.
- Code snippets show the query and existing indexes, making the missing `mobile/deleted/updated_at` index visible.

## Expected Diagnosis Shape

A successful diagnosis contains:

- task plan
- collected data
- error analysis timeline
- slow SQL findings
- root cause
- confidence score
- evidence
- fix steps
- Mermaid timeline or call chain

## Missing Key Behavior

If `DASHSCOPE_API_KEY` is missing, the service still starts. Diagnosis creation returns a clear configuration error instead of failing at import time.

Expected create-diagnosis response without a key:

```json
{
  "detail": "DASHSCOPE_API_KEY is not configured"
}
```

## Rollback

This project is isolated under `D:\py\ai-diagnostic-agent`. Delete that directory to roll back the generated project.
