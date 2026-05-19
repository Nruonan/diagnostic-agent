# AI Diagnostic Agent

基于 DashScope 的分布式系统故障排查自动化后端。

本项目实现 `D:\py\agent.md` 中描述的诊断工作流：主 Agent 负责任务协调，依次调度任务规划、错误分析、慢 SQL 分析和根因分析，最终返回包含证据与修复步骤的结构化报告。

系统支持两种触发方式：

- 手动诊断：用户提交故障描述后立即执行完整诊断。
- 告警驱动诊断：Prometheus、ELK、XXL-Job 或其他告警系统推送事件后，系统自动创建诊断任务并在后台运行 Agent 工作流。

## 环境要求

- Python 3.10+
- DashScope API key

## 配置

复制 `.env.example` 为 `.env`，并设置：

```env
DASHSCOPE_API_KEY=your-key
DASHSCOPE_MODEL=qwen-plus
DATA_SOURCE_MODE=sample
```

`DATA_SOURCE_MODE=sample` 表示使用项目内置的 `sample_data/` 样例数据。

`DATA_SOURCE_MODE=http` 表示使用下列配置的 HTTP 数据源：

- `ELK_API_URL`
- `XXL_JOB_API_URL`
- `SLOW_QUERY_API_URL`
- `TRACE_API_URL`
- `GIT_CODE_API_URL`

每个 HTTP endpoint 会收到以下 query 参数：

- `fault_description`
- `service_hint`，仅在请求中提供时传入

每个 endpoint 可以直接返回 JSON array，也可以返回包含以下任一数组字段的 JSON object：

- `items`
- `data`
- `results`
- 数据源名称，例如 `elk` 或 `trace`

所有记录进入工作流前都会进行 schema 校验。校验失败的记录不会被静默忽略，而是会作为 data source error 保存在诊断状态中。

## API

- `GET /health`
- `POST /api/v1/diagnoses`
- `POST /api/v1/alerts`
- `GET /api/v1/diagnoses/{diagnosis_id}`
- `POST /api/v1/diagnoses/{diagnosis_id}/input`
- `GET /api/v1/reports/{diagnosis_id}`
- `GET /api/v1/reports/{diagnosis_id}/markdown`

## 手动运行

安装依赖：

```bash
pip install -e .
```

手动启动服务：

```bash
uvicorn app.main:app --reload --port 8000
```

创建诊断：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/diagnoses ^
  -H "Content-Type: application/json" ^
  -d "{\"fault_description\":\"登录接口响应超时，用户反馈下单前认证失败\"}"
```

## 告警驱动诊断

`POST /api/v1/alerts` 用于接收外部告警事件。接口会把告警内容转换为诊断上下文，创建诊断记录，然后返回 `202 Accepted`。后续的任务规划、数据采集、错误分析、慢 SQL 分析和根因分析会在后台继续执行。

请求示例：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/alerts ^
  -H "Content-Type: application/json" ^
  -d "{\"source\":\"prometheus\",\"title\":\"login api p95 latency high\",\"severity\":\"critical\",\"description\":\"登录接口 P95 延迟超过阈值\",\"labels\":{\"service\":\"gateway-api\"}}"
```

主要字段：

- `source`：告警来源，例如 `prometheus`、`elk`、`xxl-job`。
- `title`：告警标题。
- `severity`：告警级别，支持 `critical`、`high`、`medium`、`low`、`info`。
- `service_hint`：可选，明确指定受影响服务。
- `description`：可选，告警描述。
- `triggered_at`：可选，告警触发时间。
- `labels` / `annotations` / `metadata`：可选，保存告警系统传入的上下文。

如果没有传入 `service_hint`，系统会尝试从 `labels.service`、`labels.service_name`、`labels.app`、`labels.application` 或 `labels.job` 中推断服务名。

返回结果中会包含 `diagnosis_id`，并记录：

- `trigger_source: "alert"`
- `trigger_context`：原始告警 payload

查询诊断进度：

```bash
curl http://127.0.0.1:8000/api/v1/diagnoses/{diagnosis_id}
```

获取报告：

```bash
curl http://127.0.0.1:8000/api/v1/reports/{diagnosis_id}
curl http://127.0.0.1:8000/api/v1/reports/{diagnosis_id}/markdown
```

如果诊断状态返回 `need_user_input`，按要求补充人工信息：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/diagnoses/{diagnosis_id}/input ^
  -H "Content-Type: application/json" ^
  -d "{\"content\":\"故障窗口是 2026-05-19 09:58 到 10:05，最近变更是 user_profile 查询新增排序。\"}"
```

## 样例数据场景

内置样例数据描述了一个完整的登录超时故障：

- `gateway-api` 的登录请求超时。
- `user-service` 报告数据库超时。
- `sync_user_profile_cache` 这个 XXL-Job 任务失败并重试。
- 一条 `user_profile` 查询扫描了超过一百万行。
- Trace span 串联了 gateway、user service 和慢 profile 查询。
- 代码片段展示了查询语句和已有索引，从而暴露缺少 `mobile/deleted/updated_at` 组合索引的问题。

## 诊断结果结构

一次成功诊断会包含：

- trigger source and context
- task plan
- collected data
- error analysis timeline
- slow SQL findings
- root cause
- confidence score
- evidence
- fix steps
- Mermaid timeline 或 call chain

## 缺少 Key 时的行为

如果缺少 `DASHSCOPE_API_KEY`，服务仍然可以启动。创建诊断时会返回明确的配置错误，而不是在 import 阶段崩溃。

未配置 key 时，创建诊断的预期响应：

```json
{
  "detail": "DASHSCOPE_API_KEY is not configured"
}
```

## 回滚

本项目独立位于 `D:\py\ai-diagnostic-agent`。如需回滚，删除该目录即可。
