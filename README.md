# AI Diagnostic Agent

基于 DashScope 的分布式系统故障排查自动化后端。

项目实现 `D:\py\agent.md` 中描述的诊断工作流：主 Agent 负责任务协调，依次调度任务规划、错误分析、慢 SQL 分析和根因分析，最终返回包含证据与修复步骤的结构化报告。

系统支持三种触发方式：

- 手动诊断：用户提交故障描述后立即执行完整诊断。
- 通用告警：外部系统调用 `POST /api/v1/alerts`，系统创建诊断任务并后台运行工作流。
- 原生 webhook：Prometheus Alertmanager、Zabbix、ElastAlert、XXL-Job 直接推送各自格式的告警 payload。

## 环境要求

- Python 3.10+
- Docker 和 Docker Compose
- DashScope API key

## 配置

复制 `.env.example` 为 `.env`，并设置：

```env
DASHSCOPE_API_KEY=your-key
DASHSCOPE_MODEL=qwen-plus
DATA_SOURCE_MODE=sample
```

常用配置：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 空 | DashScope API key，创建诊断时必需 |
| `DASHSCOPE_MODEL` | `qwen-plus` | DashScope 模型 |
| `DATA_SOURCE_MODE` | `sample` | `sample` 使用本地样例数据，`http` 使用外部 HTTP 数据源 |
| `WEBHOOK_TOKEN` | 空 | webhook 鉴权 token；为空时跳过鉴权 |
| `WEBHOOK_DEDUP_COOLDOWN_SECONDS` | `300` | webhook 去重冷却窗口 |
| `RUNTIME_DIR` | `.runtime` | 诊断状态持久化目录 |

`DATA_SOURCE_MODE=http` 时会读取以下 HTTP 数据源：

- `ELK_API_URL`
- `XXL_JOB_API_URL`
- `SLOW_QUERY_API_URL`
- `TRACE_API_URL`
- `GIT_CODE_API_URL`

每个 HTTP endpoint 会收到 query 参数 `fault_description` 和可选 `service_hint`。endpoint 可以直接返回 JSON array，也可以返回包含 `items`、`data`、`results` 或数据源名称字段的 JSON object。

## API

- `GET /health`
- `POST /api/v1/diagnoses`
- `POST /api/v1/alerts`
- `POST /api/v1/webhooks/prometheus`
- `POST /api/v1/webhooks/zabbix`
- `POST /api/v1/webhooks/elastalert`
- `POST /api/v1/webhooks/xxl-job`
- `GET /api/v1/diagnoses/{diagnosis_id}`
- `POST /api/v1/diagnoses/{diagnosis_id}/input`
- `GET /api/v1/reports/{diagnosis_id}`
- `GET /api/v1/reports/{diagnosis_id}/markdown`

## 本地运行

安装依赖：

```bash
pip install -e .
```

启动服务：

```bash
uvicorn app.main:app --reload --port 8000
```

创建手动诊断：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/diagnoses ^
  -H "Content-Type: application/json" ^
  -d "{\"fault_description\":\"登录接口响应超时，用户反馈下单前认证失败\"}"
```

## Docker Compose 部署

当前 `docker-compose.yml` 会启动完整本地集成环境：

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| AI Diagnostic API | http://localhost:8010 | 排障 Agent API |
| Datasource Mock | http://localhost:9000 | HTTP 数据源样例 |
| Prometheus | http://localhost:9090 | 指标和示例告警 |
| Alertmanager | http://localhost:9093 | Prometheus webhook 转发 |
| Zabbix Web | http://localhost:8081 | Zabbix 控制台 |
| XXL-Job Admin | http://localhost:8082/xxl-job-admin | XXL-Job 控制台 |
| Elasticsearch | http://localhost:9200 | ElastAlert 查询后端 |

启动：

```bash
docker compose up -d --build
```

检查配置：

```bash
docker compose config --quiet
```

查看日志：

```bash
docker compose logs -f diagnostic-api
docker compose logs -f alertmanager
docker compose logs -f elastalert
```

停止：

```bash
docker compose down
```

清理数据卷：

```bash
docker compose down -v
```

## 告警驱动诊断

`POST /api/v1/alerts` 用于接收通用告警事件。接口会把告警内容转换为诊断上下文，创建诊断记录，然后返回 `202 Accepted`。后续任务规划、数据采集、错误分析、慢 SQL 分析和根因分析会在后台执行。

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

## Webhook 适配器

所有 webhook 端点共享以下行为：

- 默认无需鉴权；设置 `WEBHOOK_TOKEN` 后必须传入 `X-Webhook-Token`。
- 成功创建诊断返回 `202`，响应包含 `accepted`、`deduplicated`、`diagnosis_ids`。
- 重复告警在冷却窗口内返回 `200`，`accepted=0`，`deduplicated>0`。
- 缺少 `DASHSCOPE_API_KEY` 时返回 `503`，不会创建诊断。

Prometheus Alertmanager：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/prometheus ^
  -H "Content-Type: application/json" ^
  -d "{\"status\":\"firing\",\"alerts\":[{\"status\":\"firing\",\"labels\":{\"alertname\":\"LoginLatencyHigh\",\"severity\":\"critical\",\"service\":\"gateway-api\",\"instance\":\"gateway-1\"},\"annotations\":{\"summary\":\"login latency high\",\"description\":\"P95 latency is above threshold\"},\"startsAt\":\"2026-05-20T10:00:00Z\"}]}"
```

Zabbix：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/zabbix ^
  -H "Content-Type: application/json" ^
  -d "{\"event_id\":\"10001\",\"host\":\"gateway-api-1\",\"trigger_name\":\"CPU load high\",\"severity\":\"High\",\"status\":\"PROBLEM\",\"description\":\"CPU load is above threshold\"}"
```

ElastAlert：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/elastalert ^
  -H "Content-Type: application/json" ^
  -d "{\"rule_name\":\"mysql_slow_query_webhook\",\"alert_time\":\"2026-05-20T10:00:00Z\",\"num_matches\":1,\"match_body\":{\"service\":\"user-service\",\"query_time\":3.2,\"sql\":\"select * from user_profile where mobile=?\"},\"alert_info\":{\"severity\":\"high\"}}"
```

XXL-Job 自定义失败上报：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/xxl-job ^
  -H "Content-Type: application/json" ^
  -d "{\"job_id\":1,\"job_group\":1,\"job_name\":\"sync_user_profile_cache\",\"log_id\":90001,\"handle_code\":500,\"handle_msg\":\"database timeout\",\"executor_address\":\"user-service\"}"
```

XXL-Job 原生回调格式会返回 `{"code": 200}`，只在 `handleCode != 200` 时触发诊断。

## 诊断结果

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

## 样例数据场景

内置样例数据描述了一个完整的登录超时故障：

- `gateway-api` 的登录请求超时。
- `user-service` 报告数据库超时。
- `sync_user_profile_cache` 这个 XXL-Job 任务失败并重试。
- 一条 `user_profile` 查询扫描了超过一百万行。
- Trace span 串联了 gateway、user service 和慢 profile 查询。
- 代码片段展示了查询语句和已有索引，从而暴露缺少 `mobile/deleted/updated_at` 组合索引的问题。

## 缺少 Key 时的行为

如果缺少 `DASHSCOPE_API_KEY`，服务仍然可以启动。创建诊断时会返回明确的配置错误，而不是在 import 阶段崩溃。

预期响应：

```json
{
  "detail": "DASHSCOPE_API_KEY is not configured"
}
```

## 回滚

本项目独立位于 `D:\py\ai-diagnostic-agent`。如需回滚本次 webhook 和 compose 集成，恢复以下路径即可：

- `app/api/deps.py`
- `app/api/routes.py`
- `app/config.py`
- `app/main.py`
- `app/webhooks/`
- `docker-compose.yml`
- `docker/alertmanager/`
- `docker/elastalert/`
- `docker/prometheus/`
- `docker/xxl-job/`
- `README.md`
