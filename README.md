# AI Diagnostic Agent

AI Diagnostic Agent 是一个面向分布式系统故障排查的 FastAPI 后端。系统接收人工故障描述或外部告警，调度多个诊断 Agent 收集证据、分析错误和慢 SQL，最后生成包含根因、置信度、证据、修复步骤和 Mermaid 链路图的结构化报告。

当前实现支持：

- 手动诊断：通过 API 或内置 Web UI 提交故障描述。
- 告警驱动诊断：通过通用告警接口创建后台诊断任务。
- 原生 webhook：接收 Prometheus Alertmanager、Zabbix、ElastAlert、XXL-Job payload。
- 多 LLM provider：DashScope、OpenAI、Claude。
- 两类数据源：本地 sample data 与外部 HTTP 数据源。
- Markdown 报告：按诊断 ID 导出可读报告。

## 目录

- [系统设计](#系统设计)
- [Agent 主流程](#agent-主流程)
- [环境要求](#环境要求)
- [安装使用](#安装使用)
- [配置说明](#配置说明)
- [API 使用](#api-使用)
- [Webhook 接入](#webhook-接入)
- [Docker Compose 集成环境](#docker-compose-集成环境)
- [样例数据场景](#样例数据场景)
- [故障与边界行为](#故障与边界行为)

## 系统设计

运行入口位于 `app/main.py`，应用启动时组装以下核心对象：

```text
FastAPI app
  ├─ API routes: app/api/routes.py
  ├─ Webhook routes: app/webhooks/*
  ├─ Static UI: app/static/*
  ├─ WorkflowEngine: app/workflow/engine.py
  ├─ MainAgent: app/agents/main_agent.py
  ├─ DataSource: app/datasources/*
  ├─ LLMClient: app/llm/providers/*
  └─ DiagnosisStore: app/storage/*
```

关键模块职责：

| 模块 | 职责 |
| --- | --- |
| `app/main.py` | 创建 FastAPI app，挂载 API、webhook 和 `/ui/` 静态控制台。 |
| `app/api/routes.py` | 提供健康检查、诊断创建、告警接入、状态查询、人工补充、报告导出接口。 |
| `app/workflow/engine.py` | 创建诊断状态、运行 Agent 流程、捕获 LLM/工作流异常、持久化结果。 |
| `app/agents/main_agent.py` | 编排 Planning、Error Analysis、Slow SQL、Root Cause 四类 Agent。 |
| `app/datasources/*` | 从 sample JSON 或 HTTP endpoint 收集日志、任务、告警、慢查询、指标、Trace 和代码片段。 |
| `app/llm/*` | 按 `LLM_PROVIDER` 构建 DashScope、OpenAI 或 Claude provider，并要求模型返回 strict JSON。 |
| `app/reports/generator.py` | 将诊断状态转换为 Markdown 报告。 |
| `app/webhooks/*` | 将不同告警系统 payload 规范化为统一诊断上下文，并执行 token 校验与去重。 |

数据流：

```text
用户 / 告警系统
  → FastAPI API 或 webhook
  → WorkflowEngine 创建 DiagnosisState
  → MainAgent 编排子 Agent
  → DataSource 收集证据
  → LLM provider 输出结构化分析
  → WorkflowEngine 保存状态
  → API / UI / Markdown 报告查询结果
```

## Agent 主流程

主流程由 `WorkflowEngine` 和 `MainAgent` 共同完成。

### 1. 创建诊断

触发来源包括：

- `POST /api/v1/diagnoses`：同步执行完整诊断。
- `POST /api/v1/alerts`：创建诊断后放入后台任务。
- `POST /api/v1/webhooks/*`：原生 webhook 转换为告警事件后放入后台任务。

创建时生成 `DiagnosisState`，初始状态为 `created`，包含：

- `diagnosis_id`
- `fault_description`
- `service_hint`
- `trigger_source`
- `trigger_context`
- `created_at`
- `updated_at`

### 2. 任务规划 Agent

`PlanningAgent` 首先根据故障描述输出诊断计划：

- `tasks`：有序诊断任务。
- `focus_services`：疑似受影响服务。
- `estimated_time`：预估排查时间。
- `missing_information`：当描述过于模糊时需要用户补充的问题。

如果规划阶段发现关键信息缺失，并且当前没有人工补充，诊断状态会变为 `need_user_input`。

### 3. 并行上游分析

规划通过后，`MainAgent` 并行执行两类分析：

- `ErrorAnalysisAgent`
  - 数据范围：ELK logs、XXL-Job records、Zabbix events。
  - 输出：错误模式、时间线、疑似故障点、缺失信息。

- `SlowSqlAgent`
  - 数据范围：SlowQuery records、Prometheus metrics。
  - 输出：慢查询、扫描行数、性能问题、优化建议、缺失信息。

如果这两个上游 Agent 提出缺失信息，系统会合并已采集证据并进入 `need_user_input`。

### 4. 根因分析 Agent

`RootCauseAgent` 在上游分析完成后执行，输入包括：

- 任务规划结果。
- 错误分析结果。
- 慢 SQL 分析结果。
- Trace spans。
- Git code snippets。
- 数据源错误。
- 人工补充信息。

输出包括：

- `root_cause`：精确根因。
- `confidence`：0 到 1 的置信度。
- `evidence`：证据列表。
- `fix_steps`：修复步骤。
- `mermaid`：时间线或调用链图。
- `missing_information`：低置信度时仍需补充的信息。

### 5. 状态收敛

根因分析完成后，系统根据 `LOW_CONFIDENCE_THRESHOLD` 判断最终状态：

- `completed`：置信度达到阈值。
- `need_user_input`：置信度低于阈值，需要继续补充故障窗口、影响服务、关键日志、最近变更或复现步骤。
- `failed`：LLM 配置错误、LLM 请求失败、LLM 返回格式错误或工作流异常。

用户可通过 `POST /api/v1/diagnoses/{diagnosis_id}/input` 提交补充信息，系统会继续运行同一个诊断流程。

## 环境要求

- Python 3.10+
- Docker 和 Docker Compose，可选，仅用于集成环境
- 至少一个 LLM provider API key

项目依赖在 `pyproject.toml` 中声明，主要包括：

- `fastapi`
- `uvicorn[standard]`
- `pydantic`
- `pydantic-settings`
- `httpx`
- `python-dotenv`
- `sqlalchemy[asyncio]`
- `asyncpg`

## 安装使用

### 方式一：本地运行

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

4. 编辑 `.env`，至少设置一个 provider。

DashScope 示例：

```env
LLM_PROVIDER=dashscope
DASHSCOPE_API_KEY=your-dashscope-key
DASHSCOPE_MODEL=qwen-plus
DATA_SOURCE_MODE=sample
```

OpenAI 示例：

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-key
OPENAI_MODEL=gpt-4.1-mini
DATA_SOURCE_MODE=sample
```

Claude 示例：

```env
LLM_PROVIDER=claude
CLAUDE_API_KEY=your-claude-key
CLAUDE_MODEL=claude-sonnet-4-5
DATA_SOURCE_MODE=sample
```

5. 启动服务。

```bash
uvicorn app.main:app --reload --port 8000
```

6. 打开控制台。

```text
http://127.0.0.1:8000/ui/
```

根路径 `/` 会重定向到 `/ui/`。

### 方式二：Docker Compose 集成环境

1. 复制配置。

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

2. 在 `.env` 中设置 LLM key。

3. 启动集成环境。

```bash
docker compose up -d --build
```

4. 访问服务。

```text
API: http://127.0.0.1:8010
UI:  http://127.0.0.1:8010/ui/
```

5. 查看日志。

```bash
docker compose logs -f diagnostic-api
```

6. 停止服务。

```bash
docker compose down
```

如需删除数据卷：

```bash
docker compose down -v
```

## 配置说明

### LLM 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `dashscope` | 可选 `dashscope`、`openai`、`claude`。 |
| `DASHSCOPE_API_KEY` | 空 | DashScope API key。 |
| `DASHSCOPE_MODEL` | `qwen-plus` | DashScope 模型名。 |
| `DASHSCOPE_BASE_URL` | DashScope compatible endpoint | DashScope OpenAI-compatible chat completions endpoint。 |
| `DASHSCOPE_TIMEOUT_SECONDS` | `60` | DashScope 请求超时。 |
| `OPENAI_API_KEY` | 空 | OpenAI API key。 |
| `OPENAI_MODEL` | `gpt-4.1-mini` | OpenAI 模型名。 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL。 |
| `OPENAI_TIMEOUT_SECONDS` | `60` | OpenAI 请求超时。 |
| `CLAUDE_API_KEY` | 空 | Claude API key。 |
| `CLAUDE_MODEL` | `claude-sonnet-4-5` | Claude 模型名。 |
| `CLAUDE_BASE_URL` | `https://api.anthropic.com/v1` | Claude base URL。 |
| `CLAUDE_API_VERSION` | `2023-06-01` | Anthropic API version。 |
| `CLAUDE_TIMEOUT_SECONDS` | `60` | Claude 请求超时。 |
| `CLAUDE_MAX_TOKENS` | `4096` | Claude 最大输出 token 数。 |

如果所选 provider 没有配置 API key，创建诊断时返回 `503`，例如：

```json
{
  "detail": "DASHSCOPE_API_KEY is not configured"
}
```

### 数据源配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATA_SOURCE_MODE` | `sample` | `sample` 使用本地 JSON 样例；`http` 使用外部 HTTP 数据源。 |
| `SAMPLE_DATA_DIR` | `sample_data` | 样例数据目录。 |
| `ELK_API_URL` | 空 | 日志数据 endpoint。 |
| `XXL_JOB_API_URL` | 空 | XXL-Job 数据 endpoint。 |
| `ZABBIX_API_URL` | 空 | Zabbix 事件 endpoint。 |
| `SLOW_QUERY_API_URL` | 空 | 慢查询 endpoint。 |
| `PROMETHEUS_API_URL` | 空 | 指标 endpoint。 |
| `TRACE_API_URL` | 空 | Trace endpoint。 |
| `GIT_CODE_API_URL` | 空 | 代码片段 endpoint。 |

`DATA_SOURCE_MODE=http` 时，每个 endpoint 会收到 query 参数：

- `fault_description`
- `service_hint`，可选

endpoint 可以直接返回 JSON array，也可以返回包含以下任一字段的 JSON object：

- `items`
- `data`
- `results`
- 与数据源名称一致的字段，例如 `elk`、`slow_query`、`trace`

### 工作流配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENT_TIMEOUT_SECONDS` | `120` | 单个 Agent 调用超时。 |
| `LOW_CONFIDENCE_THRESHOLD` | `0.8` | 根因置信度低于该阈值时进入 `need_user_input`。 |
| `RUNTIME_DIR` | `.runtime` | JSON 诊断状态持久化目录。 |
| `WEBHOOK_TOKEN` | 空 | webhook token；为空时跳过鉴权。 |
| `WEBHOOK_DEDUP_COOLDOWN_SECONDS` | `300` | webhook 去重冷却窗口，单位秒。 |

说明：仓库中已有 `PostgresDiagnosisStore` 和 `STORAGE_MODE` 配置，但当前 `app/main.py` 实际装配的是 `JsonDiagnosisStore`，因此运行时诊断状态默认保存到 `RUNTIME_DIR`。

## API 使用

### 健康检查

```bash
curl http://127.0.0.1:8000/health
```

返回包含当前 provider、LLM 是否配置、DashScope 是否配置、数据源模式。

### 创建手动诊断

```bash
curl -X POST http://127.0.0.1:8000/api/v1/diagnoses \
  -H "Content-Type: application/json" \
  -d '{"fault_description":"登录接口响应超时，用户反馈下单前认证失败，怀疑 user-service 数据库查询慢","service_hint":"user-service"}'
```

Windows PowerShell：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/diagnoses `
  -ContentType "application/json" `
  -Body '{"fault_description":"登录接口响应超时，用户反馈下单前认证失败，怀疑 user-service 数据库查询慢","service_hint":"user-service"}'
```

### 提交通用告警

```bash
curl -X POST http://127.0.0.1:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"source":"prometheus","title":"login api p95 latency high","severity":"critical","description":"登录接口 P95 延迟超过阈值","labels":{"service":"gateway-api"}}'
```

`POST /api/v1/alerts` 返回 `202 Accepted`。诊断会在后台运行，后续通过诊断 ID 查询。

### 查询诊断状态

```bash
curl http://127.0.0.1:8000/api/v1/diagnoses/{diagnosis_id}
```

可能状态：

- `created`
- `running`
- `need_user_input`
- `completed`
- `failed`

### 补充人工信息

当状态为 `need_user_input` 时调用：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/diagnoses/{diagnosis_id}/input \
  -H "Content-Type: application/json" \
  -d '{"content":"故障窗口是 2026-05-19 09:58 到 10:05，最近变更是 user_profile 查询新增排序。"}'
```

如果当前状态不是 `need_user_input`，接口返回 `409`。

### 获取报告

JSON 报告：

```bash
curl http://127.0.0.1:8000/api/v1/reports/{diagnosis_id}
```

Markdown 报告：

```bash
curl http://127.0.0.1:8000/api/v1/reports/{diagnosis_id}/markdown
```

报告接口只允许在 `completed`、`need_user_input` 或 `failed` 状态下读取；其他状态返回 `409`。

## Webhook 接入

所有 webhook 端点都挂载在：

```text
/api/v1/webhooks
```

共享行为：

- 设置 `WEBHOOK_TOKEN` 后，请求必须携带 `X-Webhook-Token`。
- 新告警成功创建诊断时返回 `202`。
- 冷却窗口内重复告警返回 `200`，`accepted=0`，`deduplicated>0`。
- 未配置当前 LLM provider key 时返回 `503`。

### Prometheus Alertmanager

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/prometheus \
  -H "Content-Type: application/json" \
  -d '{"status":"firing","alerts":[{"status":"firing","labels":{"alertname":"LoginLatencyHigh","severity":"critical","service":"gateway-api","instance":"gateway-1"},"annotations":{"summary":"login latency high","description":"P95 latency is above threshold"},"startsAt":"2026-05-20T10:00:00Z"}]}'
```

只处理 `status=firing` 的 alert。

### Zabbix

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/zabbix \
  -H "Content-Type: application/json" \
  -d '{"event_id":"10001","host":"gateway-api-1","trigger_name":"CPU load high","severity":"High","status":"PROBLEM","description":"CPU load is above threshold"}'
```

### ElastAlert

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/elastalert \
  -H "Content-Type: application/json" \
  -d '{"rule_name":"mysql_slow_query_webhook","alert_time":"2026-05-20T10:00:00Z","num_matches":1,"match_body":{"service":"user-service","query_time":3.2,"sql":"select * from user_profile where mobile=?"},"alert_info":{"severity":"high"}}'
```

### XXL-Job

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/xxl-job \
  -H "Content-Type: application/json" \
  -d '{"job_id":1,"job_group":1,"job_name":"sync_user_profile_cache","log_id":90001,"handle_code":500,"handle_msg":"database timeout","executor_address":"user-service"}'
```

XXL-Job 原生回调格式会返回 `{"code": 200}`，并且只在 `handleCode != 200` 时触发诊断。

## Docker Compose 集成环境

`docker-compose.yml` 会启动一套本地联调环境：

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| AI Diagnostic API | http://127.0.0.1:8010 | 诊断 API 与 Web UI。 |
| Datasource Mock | http://127.0.0.1:9000 | HTTP 数据源样例。 |
| Prometheus | http://127.0.0.1:9090 | 指标与示例告警。 |
| Alertmanager | http://127.0.0.1:9093 | Prometheus webhook 转发。 |
| Zabbix Web | http://127.0.0.1:8081 | Zabbix 控制台。 |
| XXL-Job Admin | http://127.0.0.1:8082/xxl-job-admin | XXL-Job 控制台。 |
| Elasticsearch | http://127.0.0.1:9202 | ElastAlert 查询后端。 |

Compose 中 `diagnostic-api` 会将 `DATA_SOURCE_MODE` 设置为 `http`，并连接 `datasource-mock` 的各个 endpoint。

## 样例数据场景

`sample_data/` 内置了一个登录链路超时场景：

- `gateway-api` 登录请求超时。
- `user-service` 出现数据库超时。
- `sync_user_profile_cache` XXL-Job 任务失败并重试。
- `user_profile` 查询扫描超过一百万行。
- Trace 串联 gateway、user-service 和慢 profile 查询。
- 代码片段展示查询语句和已有索引，用于推断缺少合适组合索引。

在 `DATA_SOURCE_MODE=sample` 下，本地诊断会使用这些 JSON 文件作为证据来源。

## 故障与边界行为

- 缺少当前 `LLM_PROVIDER` 对应 API key：创建诊断返回 `503`。
- LLM 请求失败：诊断状态变为 `failed`，错误记录在 `errors`。
- LLM 返回 JSON 不符合 schema：诊断状态变为 `failed`。
- HTTP 数据源未配置 required endpoint：流程继续执行，但 `collected_data.source_errors` 会记录数据源错误。
- webhook token 不匹配：返回 `401`。
- webhook 重复告警：冷却窗口内不重复创建诊断。
- 诊断置信度低：状态变为 `need_user_input`，用户补充后继续同一诊断。
