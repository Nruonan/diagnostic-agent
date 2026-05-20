# AI Diagnostic Agent

AI Diagnostic Agent 是一个面向分布式系统故障排查的 FastAPI 应用。系统接收人工故障描述、通用告警或原生 webhook，调度多个诊断 Agent 收集证据、分析错误和慢 SQL，最后输出根因、置信度、证据、修复步骤和 Markdown 报告。

当前项目不规划 RAG 功能。后续优化重点放在生产可靠性、权限隔离、可观测性、评测闭环和数据源治理上。

## 当前能力

- Web UI：提交诊断、查看实时进度、恢复历史会话、查看报告。
- REST API：同步诊断、异步诊断、状态查询、人工补充、报告导出。
- 持久化 SSE：诊断事件写入存储，服务重启后可通过 `Last-Event-ID` 或 `last_event_id` 回放。
- 会话持久化：默认匿名用户 `anonymous`，`session_id == diagnosis_id`，支持历史会话列表。
- 多 Agent 工作流：Planning、Error Analysis、Slow SQL、Root Cause。
- 多 LLM provider：DashScope、OpenAI、Claude，支持重试、指数退避和 provider 降级。
- LLM metrics：暴露 `/metrics`，包含调用次数、失败数、延迟、token、retry、fallback。
- 数据源：本地 sample JSON 或 HTTP 数据源。
- Webhook：Prometheus Alertmanager、Zabbix、ElastAlert、XXL-Job。
- 存储：JSON 文件或 PostgreSQL；Docker Compose 默认使用 PostgreSQL。

## 目录

- [系统结构](#系统结构)
- [Agent 主流程](#agent-主流程)
- [环境要求](#环境要求)
- [安装使用](#安装使用)
- [配置说明](#配置说明)
- [API 使用](#api-使用)
- [Webhook 接入](#webhook-接入)
- [Docker Compose 集成环境](#docker-compose-集成环境)
- [优化方向](#优化方向)

## 系统结构

运行入口位于 `app/main.py`。应用启动时组装配置、LLM client、数据源、存储、事件总线和工作流引擎。

```text
FastAPI app
  ├─ API routes: app/api/routes.py
  ├─ Webhook routes: app/webhooks/*
  ├─ Static UI: app/static/*
  ├─ WorkflowEngine: app/workflow/engine.py
  ├─ WorkflowEventBus: app/events.py
  ├─ MainAgent: app/agents/main_agent.py
  ├─ DataSource: app/datasources/*
  ├─ LLMClient: app/llm/*
  ├─ DiagnosisStore: app/storage/*
  └─ ReportGenerator: app/reports/generator.py
```

关键模块职责：

| 模块 | 职责 |
| --- | --- |
| `app/main.py` | 创建 FastAPI app，挂载 API、webhook、`/ui/`，初始化 store 和 event bus。 |
| `app/api/routes.py` | 健康检查、诊断、session、SSE、报告、metrics API。 |
| `app/workflow/engine.py` | 创建诊断状态、创建 session、运行 Agent、保存状态、发布事件。 |
| `app/events.py` | SSE 事件模型、订阅、回放、持久化写入。 |
| `app/agents/main_agent.py` | 编排 Planning、Error Analysis、Slow SQL、Root Cause。 |
| `app/datasources/*` | 从 sample JSON 或 HTTP endpoint 收集日志、任务、告警、慢查询、指标、Trace 和代码片段。 |
| `app/llm/*` | 构建多 provider LLM client，处理重试、降级、metrics、strict JSON 输出。 |
| `app/storage/*` | JSON/PostgreSQL 两种存储实现，保存 diagnosis、session、user、workflow events。 |
| `app/webhooks/*` | 将不同告警系统 payload 规范化为统一告警，并执行 token 校验与去重。 |

## Agent 主流程

### 1. 创建诊断与会话

触发入口：

- `POST /api/v1/diagnoses`：同步执行完整诊断。
- `POST /api/v1/diagnoses/async`：创建诊断后后台执行。
- `POST /api/v1/alerts`：通用告警入口。
- `POST /api/v1/webhooks/*`：原生 webhook 入口。

创建时生成 `DiagnosisState`，初始状态为 `created`。系统同时创建一条 `DiagnosisSession`，默认归属 `anonymous` 用户，并发布 `diagnosis_created` SSE 事件。

### 2. 工作流执行

`WorkflowEngine.run()` 将诊断状态置为 `running`，发布 `diagnosis_started`，然后交给 `MainAgent`。

执行顺序：

1. `PlanningAgent`：根据故障描述生成任务规划、关注服务和缺失信息。
2. `ErrorAnalysisAgent` 与 `SlowSqlAgent`：并行分析错误日志、任务记录、Zabbix 事件、慢查询和指标。
3. `RootCauseAgent`：综合上游结果、Trace、代码片段、人工补充，输出根因和修复步骤。
4. `WorkflowEngine`：保存最终状态并发布 `diagnosis_finished`。

每个阶段会发布 `stage_started`、`stage_completed` 或 `need_user_input` 事件。Web UI 通过 SSE 实时展示进度。

### 3. 状态收敛

可能状态：

- `created`：诊断已创建。
- `running`：工作流运行中。
- `completed`：置信度达到 `LOW_CONFIDENCE_THRESHOLD`。
- `need_user_input`：规划、上游分析或根因阶段发现关键信息不足。
- `failed`：LLM 配置错误、请求失败、返回格式错误或工作流异常。

用户可通过 `POST /api/v1/diagnoses/{diagnosis_id}/input` 补充信息，系统会在同一个诊断上继续执行。

## 环境要求

- Python 3.10+
- Docker 和 Docker Compose，可选，用于集成环境
- 至少一个 LLM provider API key

主要依赖在 `pyproject.toml` 中声明：

- `fastapi`
- `uvicorn[standard]`
- `pydantic`
- `pydantic-settings`
- `httpx`
- `sqlalchemy[asyncio]`
- `asyncpg`

## 安装使用

### 本地运行

1. 创建虚拟环境。

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS / Linux：

```bash
source .venv/bin/activate
```

2. 安装项目。

```bash
pip install -e .
```

3. 准备配置。

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

4. 编辑 `.env`，至少设置一个 LLM key。

```env
LLM_PROVIDER=dashscope
DASHSCOPE_API_KEY=your-dashscope-key
DATA_SOURCE_MODE=sample
STORAGE_MODE=json
```

5. 启动服务。

```bash
uvicorn app.main:app --reload --port 8000
```

6. 打开控制台。

```text
http://127.0.0.1:8000/ui/
```

### Docker Compose 集成环境

1. 复制配置并设置 LLM key。

```bash
cp .env.example .env
```

2. 启动服务。

```bash
docker compose up -d --build
```

3. 访问服务。

```text
API: http://127.0.0.1:8010
UI:  http://127.0.0.1:8010/ui/
```

4. 查看日志。

```bash
docker compose logs -f diagnostic-api
```

5. 停止服务。

```bash
docker compose down
```

如需删除 PostgreSQL 和其他数据卷：

```bash
docker compose down -v
```

## 配置说明

### LLM 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `dashscope` | 主 provider，可选 `dashscope`、`openai`、`claude`。 |
| `LLM_FALLBACK_PROVIDERS` | 空 | 逗号分隔的备用 provider；为空时按 DashScope、OpenAI、Claude 自动补齐顺序。 |
| `LLM_RETRY_ATTEMPTS` | `2` | 每个 provider 失败后的重试次数。 |
| `LLM_RETRY_BACKOFF_SECONDS` | `0.5` | 指数退避初始间隔。 |
| `DASHSCOPE_API_KEY` | 空 | DashScope API key。 |
| `DASHSCOPE_MODEL` | `qwen-plus` | DashScope 模型名。 |
| `OPENAI_API_KEY` | 空 | OpenAI API key。 |
| `OPENAI_MODEL` | `gpt-4.1-mini` | OpenAI 模型名。 |
| `CLAUDE_API_KEY` | 空 | Claude API key。 |
| `CLAUDE_MODEL` | `claude-sonnet-4-5` | Claude 模型名。 |

只要至少一个 provider 配置了 key，系统就可以启动诊断；首选 provider 不可用时会尝试备用 provider。

### 存储配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `STORAGE_MODE` | `json` | `json` 或 `postgres`。Docker Compose 默认覆盖为 `postgres`。 |
| `RUNTIME_DIR` | `.runtime` | JSON 存储目录。 |
| `DATABASE_URL` | PostgreSQL URL | `STORAGE_MODE=postgres` 时必填。 |

PostgreSQL 模式会自动创建：

- `diagnoses`
- `users`
- `diagnosis_sessions`
- `workflow_events`

### 数据源配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATA_SOURCE_MODE` | `sample` | `sample` 使用本地 JSON；`http` 使用外部 HTTP endpoint。 |
| `SAMPLE_DATA_DIR` | `sample_data` | 样例数据目录。 |
| `ELK_API_URL` | 空 | 日志数据 endpoint。 |
| `XXL_JOB_API_URL` | 空 | XXL-Job 数据 endpoint。 |
| `ZABBIX_API_URL` | 空 | Zabbix 事件 endpoint。 |
| `SLOW_QUERY_API_URL` | 空 | 慢查询 endpoint。 |
| `PROMETHEUS_API_URL` | 空 | 指标 endpoint。 |
| `TRACE_API_URL` | 空 | Trace endpoint。 |
| `GIT_CODE_API_URL` | 空 | 代码片段 endpoint。 |

### 工作流配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENT_TIMEOUT_SECONDS` | `120` | 单个 Agent 调用超时。 |
| `LOW_CONFIDENCE_THRESHOLD` | `0.8` | 根因置信度低于该阈值时进入 `need_user_input`。 |
| `WEBHOOK_TOKEN` | 空 | webhook token；为空时跳过鉴权。 |
| `WEBHOOK_DEDUP_COOLDOWN_SECONDS` | `300` | webhook 去重冷却窗口，单位秒。 |

## API 使用

### 健康检查

```bash
curl http://127.0.0.1:8000/health
```

### 创建异步诊断

```bash
curl -X POST http://127.0.0.1:8000/api/v1/diagnoses/async \
  -H "Content-Type: application/json" \
  -d '{"fault_description":"登录接口响应超时，怀疑 user-service 数据库查询慢","service_hint":"user-service"}'
```

### SSE 实时进度

```bash
curl -N http://127.0.0.1:8000/api/v1/diagnoses/{diagnosis_id}/events
```

断线续传：

```bash
curl -N "http://127.0.0.1:8000/api/v1/diagnoses/{diagnosis_id}/events?last_event_id=3"
```

浏览器 `EventSource` 不能手动设置请求头，所以前端使用 `last_event_id` query 参数。服务端仍兼容标准 `Last-Event-ID` header。

### 查询历史会话

```bash
curl http://127.0.0.1:8000/api/v1/sessions?limit=20
curl http://127.0.0.1:8000/api/v1/sessions/{session_id}
```

### 查询诊断状态

```bash
curl http://127.0.0.1:8000/api/v1/diagnoses/{diagnosis_id}
```

### 补充人工信息

```bash
curl -X POST http://127.0.0.1:8000/api/v1/diagnoses/{diagnosis_id}/input \
  -H "Content-Type: application/json" \
  -d '{"content":"故障窗口是 2026-05-20 10:00 到 10:05，最近有 user_profile 查询变更。"}'
```

### 获取报告

```bash
curl http://127.0.0.1:8000/api/v1/reports/{diagnosis_id}
curl http://127.0.0.1:8000/api/v1/reports/{diagnosis_id}/markdown
```

### LLM metrics

```bash
curl http://127.0.0.1:8000/metrics
```

## Webhook 接入

Webhook 端点挂载在：

```text
/api/v1/webhooks
```

共享行为：

- 设置 `WEBHOOK_TOKEN` 后，请求必须携带 `X-Webhook-Token`。
- 新告警成功创建诊断时返回 `202`。
- 冷却窗口内重复告警返回 `200`，`accepted=0`，`deduplicated>0`。
- 未配置任何 LLM provider key 时返回 `503`。

支持端点：

- `POST /api/v1/webhooks/prometheus`
- `POST /api/v1/webhooks/zabbix`
- `POST /api/v1/webhooks/elastalert`
- `POST /api/v1/webhooks/xxl-job`

## Docker Compose 集成环境

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| AI Diagnostic API | http://127.0.0.1:8010 | API 与 Web UI。 |
| Datasource Mock | http://127.0.0.1:9000 | HTTP 数据源样例。 |
| Prometheus | http://127.0.0.1:9090 | 指标与示例告警。 |
| Alertmanager | http://127.0.0.1:9093 | Prometheus webhook 转发。 |
| Zabbix Web | http://127.0.0.1:8081 | Zabbix 控制台。 |
| XXL-Job Admin | http://127.0.0.1:8082/xxl-job-admin | XXL-Job 控制台。 |
| Elasticsearch | http://127.0.0.1:9202 | ElastAlert 查询后端。 |
| PostgreSQL | compose 内部网络 | 诊断、session、用户、SSE 事件持久化。 |

Compose 中 `diagnostic-api` 默认：

- `DATA_SOURCE_MODE=http`
- `STORAGE_MODE=postgres`
- `DATABASE_URL=postgresql+asyncpg://diagnostic:diagnostic@postgres:5432/diagnostic_agent`

## 优化方向

当前不做 RAG。更适合这个项目的后续优化如下：

1. 主 API 鉴权与用户体系：把当前匿名用户升级为真实用户、API token 或 session cookie。
2. Webhook 去重持久化：将 `DeduplicationService` 从内存迁移到 PostgreSQL，支持服务重启和多实例。
3. Alembic 迁移：替代 `metadata.create_all`，让表结构变更可审计、可回滚。
4. 并发限流：限制同时运行的诊断数，保护 LLM quota 和数据源。
5. 诊断成本追踪：按 diagnosis 汇总 token、latency、retry、fallback 和预估费用。
6. 评测集与回归评估：用固定故障样例验证 Agent 输出质量，避免 prompt 改动引入回归。
7. 后台任务队列：从 FastAPI `BackgroundTasks` 迁移到 Celery/RQ/Arq，支持重启恢复和任务状态管理。
8. 数据源鉴权与超时分级：为 HTTP 数据源增加 token、超时、重试、熔断和每源错误率监控。
9. 更细粒度 SSE 事件：增加 datasource、LLM attempt、retry/fallback 事件，便于 UI 展示诊断链路。
