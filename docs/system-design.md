# AI Diagnostic Agent 系统设计

> 版本: 0.1.0  
> 更新日期: 2026-05-20  
> 范围: 当前代码实现，不包含 RAG 规划

## 1. 设计目标

AI Diagnostic Agent 的目标是把一次线上故障排查拆成可观测、可恢复、可追溯的自动化流程：

- 接收人工故障描述或监控告警。
- 调度多个专业 Agent 分别完成规划、错误分析、慢 SQL 分析和根因综合。
- 将诊断状态、会话和 SSE 事件持久化，支持页面刷新、断线重连和服务重启后的回放。
- 对 LLM 调用做重试、降级和 Prometheus metrics 埋点。
- 在证据不足或置信度低时进入人机协作状态。

非目标：

- 不建设 RAG 或向量检索链路。
- 不在当前阶段做多租户计费系统。
- 不替代现有 APM/日志/监控系统，只做聚合诊断编排。

## 2. 总体架构

```text
User / Alert Source
  │
  ├─ Web UI: /ui/
  ├─ REST API: /api/v1/*
  └─ Webhook API: /api/v1/webhooks/*
      │
      ▼
FastAPI Application
  ├─ Settings
  ├─ WorkflowEngine
  ├─ WorkflowEventBus
  ├─ MainAgent
  │   ├─ PlanningAgent
  │   ├─ ErrorAnalysisAgent
  │   ├─ SlowSqlAgent
  │   └─ RootCauseAgent
  ├─ ResilientLLMClient
  │   ├─ DashScopeProvider
  │   ├─ OpenAIProvider
  │   └─ ClaudeProvider
  ├─ DataSource
  │   ├─ SampleDataSource
  │   └─ HttpDataSource
  └─ DiagnosisStore
      ├─ JsonDiagnosisStore
      └─ PostgresDiagnosisStore
```

## 3. 核心模块

| 模块 | 文件 | 责任 |
| --- | --- | --- |
| 应用入口 | `app/main.py` | 装配 settings、LLM、data source、store、event bus、workflow engine。 |
| API 路由 | `app/api/routes.py` | 诊断、session、SSE、报告、metrics、健康检查。 |
| 工作流引擎 | `app/workflow/engine.py` | 创建诊断、创建 session、运行 Agent、保存状态、发布事件。 |
| 事件总线 | `app/events.py` | 保存事件、订阅事件、按 `Last-Event-ID`/`last_event_id` 回放。 |
| Agent 编排 | `app/agents/main_agent.py` | 控制 Agent 执行顺序、并行分析和状态收敛。 |
| LLM 韧性层 | `app/llm/resilient.py` | provider 顺序、重试、指数退避、降级、metrics。 |
| LLM metrics | `app/llm/metrics.py` | 记录调用、失败、延迟、token、retry、fallback。 |
| 存储 | `app/storage/*` | JSON/PostgreSQL 两种实现。 |
| Web UI | `app/static/*` | 创建诊断、历史会话、SSE 实时进度、报告查看。 |
| Webhook | `app/webhooks/*` | Prometheus、Zabbix、ElastAlert、XXL-Job payload 标准化。 |

## 4. 数据模型

### 4.1 DiagnosisState

`DiagnosisState` 是工作流主状态，包含：

- `diagnosis_id`
- `status`
- `fault_description`
- `service_hint`
- `trigger_source`
- `trigger_context`
- `human_inputs`
- `planning`
- `error_analysis`
- `slow_sql_analysis`
- `root_cause`
- `collected_data`
- `errors`

### 4.2 Session/User

当前实现提供最小用户模型：

- 默认用户：`anonymous`
- 当前约定：`session_id == diagnosis_id`
- session 用于 UI 历史列表、诊断恢复和后续用户体系扩展。

PostgreSQL 表：

- `users`
- `diagnosis_sessions`

### 4.3 WorkflowEvent

`WorkflowEvent` 用于 SSE 和回放：

- `event_id`
- `diagnosis_id`
- `event`
- `message`
- `stage`
- `status`
- `payload`
- `created_at`

PostgreSQL 表：`workflow_events`。  
索引重点：`diagnosis_id + event_id`，用于断线续传。

## 5. 诊断生命周期

```mermaid
stateDiagram-v2
    [*] --> CREATED: create diagnosis
    CREATED --> RUNNING: run workflow
    RUNNING --> NEED_USER_INPUT: missing info / low confidence
    RUNNING --> COMPLETED: confidence >= threshold
    RUNNING --> FAILED: LLM or workflow error
    NEED_USER_INPUT --> RUNNING: human input
    COMPLETED --> [*]
    FAILED --> [*]
```

## 6. Agent 主流程

```text
WorkflowEngine.create()
  ├─ create DiagnosisState
  ├─ store.save(state)
  ├─ store.create_session(session_id=diagnosis_id)
  └─ event_bus.publish(diagnosis_created)

WorkflowEngine.run()
  ├─ set status=running
  ├─ event_bus.publish(diagnosis_started)
  ├─ MainAgent.run()
  │   ├─ PlanningAgent
  │   ├─ collect error/sql context
  │   ├─ ErrorAnalysisAgent + SlowSqlAgent in parallel
  │   ├─ collect root context
  │   └─ RootCauseAgent
  ├─ store.save(final_state)
  └─ event_bus.publish(diagnosis_finished)
```

### 状态收敛规则

- Planning 阶段缺少关键信息且没有人工补充：`need_user_input`
- Error/Slow SQL 阶段提出缺失信息：`need_user_input`
- RootCause 置信度低于 `LOW_CONFIDENCE_THRESHOLD`：`need_user_input`
- RootCause 置信度达标：`completed`
- LLM 配置、请求、响应或工作流异常：`failed`

## 7. SSE 持久化设计

### 7.1 发布

所有关键阶段通过 `WorkflowEventBus.publish()` 发布事件。  
如果 event bus 装配了 store，事件会先写入持久化存储，再广播给在线订阅者。

### 7.2 订阅与回放

客户端订阅：

```text
GET /api/v1/diagnoses/{diagnosis_id}/events
```

回放策略：

- 标准 SSE 客户端可使用 `Last-Event-ID` header。
- Web UI 使用 `last_event_id` query 参数，因为浏览器 `EventSource` 不能手动设置 header。
- 服务端只返回 `event_id > last_event_id` 的事件。

### 7.3 UI 恢复

Web UI 启动时：

1. 请求 `/api/v1/sessions?limit=20`。
2. 渲染历史会话。
3. 从 `localStorage.activeDiagnosisId` 恢复上次诊断。
4. 通过 SSE 回放事件并继续订阅。

## 8. LLM 韧性与可观测性

### 8.1 Provider 顺序

`Settings.ordered_llm_providers()` 生成 provider 顺序：

1. `LLM_PROVIDER`
2. `LLM_FALLBACK_PROVIDERS`
3. 如果未显式配置 fallback，则补齐 DashScope、OpenAI、Claude

### 8.2 重试与降级

每个 provider 内部：

- 最大尝试次数：`LLM_RETRY_ATTEMPTS + 1`
- 失败类型：`LLMRequestError`、`LLMResponseError`
- 退避：`LLM_RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1)`

provider 失败后，`ResilientLLMClient` 会尝试下一个 provider，并记录 fallback metric。

### 8.3 Metrics

`GET /metrics` 输出 Prometheus 文本格式：

- `llm_calls_total`
- `llm_failures_total`
- `llm_latency_ms_total`
- `llm_latency_ms_count`
- `llm_input_tokens_total`
- `llm_output_tokens_total`
- `llm_retries_total`
- `llm_fallbacks_total`

## 9. 存储设计

### 9.1 JSON Store

用于本地开发和轻量运行：

```text
.runtime/
  ├─ diagnoses/*.json
  ├─ sessions/*.json
  ├─ events/*.jsonl
  └─ users.json
```

### 9.2 PostgreSQL Store

用于 Docker Compose 和更接近生产的运行方式：

```text
diagnoses
users
diagnosis_sessions
workflow_events
```

当前使用 `metadata.create_all` 自动建表。生产化建议迁移到 Alembic。

## 10. API 边界

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查。 |
| `POST` | `/api/v1/diagnoses` | 同步诊断。 |
| `POST` | `/api/v1/diagnoses/async` | 异步诊断。 |
| `GET` | `/api/v1/diagnoses/{id}` | 查询诊断状态。 |
| `GET` | `/api/v1/diagnoses/{id}/events` | SSE 进度与回放。 |
| `POST` | `/api/v1/diagnoses/{id}/input` | 人工补充。 |
| `GET` | `/api/v1/sessions` | 历史 session 列表。 |
| `GET` | `/api/v1/sessions/{id}` | session 详情。 |
| `GET` | `/api/v1/reports/{id}` | JSON 报告。 |
| `GET` | `/api/v1/reports/{id}/markdown` | Markdown 报告。 |
| `GET` | `/metrics` | LLM metrics。 |

## 11. 部署拓扑

Docker Compose 启动：

- `diagnostic-api`
- `postgres`
- `datasource-mock`
- `prometheus`
- `alertmanager`
- `zabbix-server`
- `zabbix-web`
- `xxl-job-admin`
- `elasticsearch`
- `elastalert`

Compose 默认将 `diagnostic-api` 设置为：

- `DATA_SOURCE_MODE=http`
- `STORAGE_MODE=postgres`
- `DATABASE_URL=postgresql+asyncpg://diagnostic:diagnostic@postgres:5432/diagnostic_agent`

## 12. 当前风险与优化点

不做 RAG 后，优先级更高的优化是：

1. **API 鉴权**：诊断、session、report API 当前没有用户级鉴权。
2. **Webhook 去重持久化**：当前去重服务仍是进程内存，不适合多实例。
3. **Schema migration**：用 Alembic 管理 PostgreSQL 表结构。
4. **后台任务队列**：FastAPI `BackgroundTasks` 不适合长任务重启恢复。
5. **并发限流**：限制同时运行诊断和 LLM 调用数量。
6. **诊断级成本聚合**：把 LLM metrics 汇总到 diagnosis/session。
7. **评测基准**：建立固定故障样例，评估 prompt 和 Agent 输出稳定性。
8. **数据源连接治理**：为 HTTP 数据源补鉴权、超时、重试、熔断和错误率 metrics。
9. **结构化审计日志**：记录谁触发了什么诊断、使用了哪些外部数据源、输出了哪些结论。
