# AI Diagnostic Agent 的 Agent 设计

> 更新日期: 2026-05-20  
> 说明: 本文描述当前 Agent 主流程和后续优化方向；本项目不规划 RAG。

## 1. Agent 分层

当前系统采用一个协调器加四个专业 Agent：

```text
MainAgent
  ├─ PlanningAgent
  ├─ ErrorAnalysisAgent
  ├─ SlowSqlAgent
  └─ RootCauseAgent
```

`WorkflowEngine` 负责诊断生命周期、持久化和事件发布；`MainAgent` 负责 Agent 编排。

## 2. 各 Agent 职责

### PlanningAgent

目标：把故障描述转换为诊断计划。

输入：

- `fault_description`
- `service_hint`
- `human_inputs`

输出：

- `tasks`
- `estimated_time`
- `focus_services`
- `missing_information`

状态影响：

- 如果缺少关键上下文且没有人工补充，诊断进入 `need_user_input`。

### ErrorAnalysisAgent

目标：分析错误模式、时间线和嫌疑点。

输入：

- 故障描述
- ELK logs
- XXL-Job records
- Zabbix events

输出：

- `errors`
- `timeline`
- `suspects`
- `summary`
- `missing_information`

### SlowSqlAgent

目标：识别 SQL 性能问题。

输入：

- 故障描述
- SlowQuery records
- Prometheus metrics

输出：

- `slow_queries`
- `optimizations`
- `summary`
- `missing_information`

### RootCauseAgent

目标：综合上游证据输出最终根因。

输入：

- Planning 结果
- ErrorAnalysis 结果
- SlowSql 结果
- Trace spans
- Git code snippets
- 数据源错误
- 人工补充

输出：

- `root_cause`
- `confidence`
- `evidence`
- `fix_steps`
- `mermaid`
- `missing_information`

状态影响：

- `confidence >= LOW_CONFIDENCE_THRESHOLD`：`completed`
- `confidence < LOW_CONFIDENCE_THRESHOLD`：`need_user_input`

## 3. 主流程

```text
1. WorkflowEngine.create()
   ├─ 生成 diagnosis_id
   ├─ 保存 DiagnosisState
   ├─ 创建 DiagnosisSession
   └─ 发布 diagnosis_created

2. WorkflowEngine.run()
   ├─ 状态改为 running
   ├─ 发布 diagnosis_started
   └─ MainAgent.run()

3. MainAgent.run()
   ├─ PlanningAgent
   │  └─ stage_started / stage_completed / need_user_input
   ├─ collect_error_context + collect_sql_context
   ├─ ErrorAnalysisAgent 和 SlowSqlAgent 并行
   │  └─ stage_started / stage_completed / need_user_input
   ├─ collect_root_context
   └─ RootCauseAgent
      └─ stage_started / stage_completed / need_user_input

4. WorkflowEngine 收尾
   ├─ 保存最终 DiagnosisState
   ├─ 更新 session.status
   └─ 发布 diagnosis_finished
```

## 4. 事件与 UI 反馈

每个关键节点都会发布 `WorkflowEvent`：

- `diagnosis_created`
- `diagnosis_started`
- `stage_started`
- `stage_completed`
- `need_user_input`
- `diagnosis_finished`

事件保存到 store：

- JSON 模式：`.runtime/events/{diagnosis_id}.jsonl`
- PostgreSQL 模式：`workflow_events`

UI 通过 SSE 订阅：

```text
GET /api/v1/diagnoses/{diagnosis_id}/events
```

断线续传：

- 标准客户端：`Last-Event-ID` header
- Web UI：`last_event_id` query 参数

## 5. LLM 调用策略

系统通过 `ResilientLLMClient` 包装 provider：

```text
ResilientLLMClient
  ├─ DashScopeProvider
  ├─ OpenAIProvider
  └─ ClaudeProvider
```

策略：

- 每个 provider 最多重试 `LLM_RETRY_ATTEMPTS` 次。
- 重试采用指数退避。
- 当前 provider 失败后切换到下一个可用 provider。
- 每次调用记录 latency、token、success、retry、fallback。

Prometheus metrics 入口：

```text
GET /metrics
```

## 6. 当前已解决的问题

| 曾经短板 | 当前状态 |
| --- | --- |
| 无流式输出 | 已通过 SSE 实时输出 Agent 阶段进度。 |
| SSE 重启丢事件 | 已持久化 workflow events，支持重启后回放。 |
| 无历史会话 | 已增加 user/session 表和 UI 历史会话列表。 |
| 无 LLM metrics | 已暴露 `/metrics`。 |
| 无重试策略 | 已支持指数退避重试。 |
| 无 provider 降级 | 已支持多 provider fallback。 |
| 前端刷新缓存问题 | 已使用静态资源版本参数和 no-cache header。 |

## 7. 不做 RAG 的原因

当前项目的核心价值是线上故障诊断编排，而不是知识库问答。RAG 会引入额外复杂度：

- 向量库和 embedding 链路运维成本。
- 历史案例质量难以保证，错误案例可能污染诊断。
- 当前样例数据规模不足以证明 RAG 收益。
- 面试或演示时更容易被追问评估集、召回率、chunk 策略和权限隔离。

因此本项目不规划 RAG。更高 ROI 的方向是把现有诊断链路做可靠、可观测、可评测。

## 8. 推荐优化方向

### P0：生产可用性

1. API 鉴权与用户体系
   - 当前主 API 没有用户级鉴权。
   - 建议增加 API token 或登录态，把 session 归属到真实用户。

2. Webhook 去重持久化
   - 当前去重仍是内存服务，重启后丢失。
   - 建议增加 PostgreSQL 表保存 fingerprint 和过期时间。

3. Alembic migration
   - 当前 PostgreSQL 表通过 `metadata.create_all` 自动创建。
   - 建议引入 Alembic，保证 schema 变更可审计、可回滚。

4. 后台任务队列
   - 当前异步诊断依赖 FastAPI `BackgroundTasks`。
   - 建议迁移到 Arq/Celery/RQ，支持任务重启恢复、并发控制和失败重试。

### P1：AI 工程质量

5. 诊断级成本追踪
   - 将 LLM metrics 按 `diagnosis_id` 聚合。
   - UI 展示本次耗时、token、retry、fallback 和预估费用。

6. Agent 输出评测集
   - 固定一组故障样例和期望输出。
   - 每次 prompt 或模型切换后运行回归评估。

7. Agent 自检
   - RootCause 输出后增加轻量一致性检查。
   - 检查 evidence 是否支撑 root_cause，低一致性时降低 confidence 或进入 `need_user_input`。

8. Prompt 版本管理
   - 给每个 Agent prompt 标记版本。
   - 诊断结果记录 prompt version，方便回放和回归分析。

### P2：运维集成

9. 数据源连接治理
   - 为 HTTP 数据源补 token、超时、重试、熔断和错误率 metrics。

10. 更细粒度事件
   - 增加 datasource、LLM attempt、retry、fallback 事件。
   - UI 可以展示“当前卡在哪个 provider / 哪个数据源”。

11. 结构化审计日志
   - 记录触发来源、用户、使用的数据源、最终结论和报告访问。

12. 多实例部署准备
   - 事件广播从进程内 queue 迁移到 PostgreSQL listen/notify 或 Redis pub/sub。
   - 去重、任务队列、session 都需要跨实例一致。

## 9. 面试表达要点

- 这个项目不是简单调用 LLM，而是把故障排查拆成状态机、Agent 编排、数据采集、事件流和持久化。
- SSE 事件持久化解决了诊断过程可观测和刷新恢复问题。
- LLM provider 重试和降级体现了生产韧性。
- `/metrics` 让 AI 调用成本和稳定性可以被 Prometheus 采集。
- 不做 RAG 是有意取舍：当前更需要可靠的诊断链路和评测闭环，而不是增加向量库复杂度。
