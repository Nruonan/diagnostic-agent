# Webhook 适配层实现计划

## Context

项目是一个 AI 排障 Agent，已有通用 `POST /api/v1/alerts` 端点。现在需要为各监控系统提供原生格式的 webhook 接收端点，让 Prometheus、Zabbix、ElastAlert、XXL-Job 能直接推送告警触发自动排障。

MySQL 慢查询走 Filebeat → ES → ElastAlert → webhook 链路，复用 ElastAlert 适配器，不需要独立端点。

## 实现范围

4 个 webhook 适配器 + 共享基础设施（认证、去重）

## 文件结构

```
app/
├── api/
│   ├── deps.py              # 新建：提取共享依赖 (get_engine, get_settings_from_app)
│   └── routes.py            # 修改：从 deps.py 导入依赖
├── config.py                # 修改：新增 WEBHOOK_TOKEN, WEBHOOK_DEDUP_COOLDOWN_SECONDS
├── main.py                  # 修改：注册 webhook_router, 初始化 DeduplicationService
└── webhooks/
    ├── __init__.py           # 新建：组合所有子路由为 webhook_router
    ├── _auth.py              # 新建：X-Webhook-Token 认证依赖
    ├── _dedup.py             # 新建：基于内存 TTL 的去重服务
    ├── _shared.py            # 新建：共享响应模型 (WebhookAcceptedResponse)
    ├── zabbix.py             # 新建：Zabbix Media Type webhook
    ├── prometheus.py         # 新建：Prometheus Alertmanager webhook
    ├── elastalert.py         # 新建：ElastAlert2 http_post webhook
    └── xxl_job.py            # 新建：XXL-Job 回调 + 失败上报
```

## 实现步骤

### 1. 提取共享依赖 → `app/api/deps.py`

从 `app/api/routes.py` 提取 `get_engine()` 和 `get_settings_from_app()` 到独立文件，避免循环导入。

### 2. 扩展配置 → `app/config.py`

```python
webhook_token: str = Field(default="", alias="WEBHOOK_TOKEN")
webhook_dedup_cooldown_seconds: float = Field(default=300.0, gt=0, alias="WEBHOOK_DEDUP_COOLDOWN_SECONDS")
```

### 3. 去重服务 → `app/webhooks/_dedup.py`

- 基于 `asyncio.Lock` + `dict[str, float]` 的内存 TTL 缓存
- `fingerprint(source, key_fields)` → SHA256 哈希
- `is_duplicate(fp)` → bool，命中则跳过
- 惰性清理过期条目

### 4. 认证依赖 → `app/webhooks/_auth.py`

- 读取 `X-Webhook-Token` header
- 与 `settings.webhook_token` 比对
- token 为空时跳过认证（开发模式）

### 5. 共享模型 → `app/webhooks/_shared.py`

```python
class WebhookAcceptedResponse(BaseModel):
    accepted: int
    deduplicated: int
    diagnosis_ids: list[str]
```

### 6. Zabbix 适配器 → `app/webhooks/zabbix.py`

- 路由：`POST /zabbix`
- Payload：event_id, host, trigger_name, severity(6级映射到5级), status, description, tags, items
- RESOLVED 状态返回 200 不触发排障
- 去重 key：`(event_id, host, trigger_name)`

### 7. Prometheus 适配器 → `app/webhooks/prometheus.py`

- 路由：`POST /prometheus`
- Payload：Alertmanager 原生格式（camelCase alias）
- 只处理 `status == "firing"` 的告警
- 批量处理：每条 firing alert 独立创建诊断
- 去重 key：`(alertname, instance/pod)`
- 返回 `WebhookAcceptedResponse`

### 8. ElastAlert 适配器 → `app/webhooks/elastalert.py`

- 路由：`POST /elastalert`
- Payload：rule_name, match_body, alert_time, num_matches, alert_info
- 支持 MySQL 慢查询场景（通过 rule_name 识别）
- 去重 key：`(rule_name, match_body 关键字段哈希)`

### 9. XXL-Job 适配器 → `app/webhooks/xxl_job.py`

- 路由：`POST /xxl-job`
- 两种模式：
  - **回调模式**：接收 XXL-Job 原生回调格式，返回 `{"code": 200}` 响应体
  - **上报模式**：接收自定义失败上报 payload（更丰富的上下文）
- 只在 `handle_code != 200` 时触发排障
- 去重 key：`(job_id, job_group, log_id)`

### 10. 组合路由 → `app/webhooks/__init__.py`

```python
webhook_router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])
# include 4 个子路由
```

### 11. 注册到应用 → `app/main.py`

- 创建 `DeduplicationService` 实例挂到 `app.state.dedup_service`
- `app.include_router(webhook_router)`

## 关键设计决策

| 维度 | 决策 |
|------|------|
| 认证 | X-Webhook-Token header，可选启用 |
| 去重 | 内存 TTL 缓存，5分钟冷却窗口 |
| 批量 | Prometheus 逐条创建诊断，返回批量响应 |
| XXL-Job 响应 | 回调模式返回 `{"code": 200}`，上报模式返回标准 202 |
| MySQL 慢查询 | 不建独立端点，走 ElastAlert 通道 |
| RESOLVED 告警 | 忽略，不触发排障 |

## 各监控系统配置示例

### Prometheus Alertmanager
```yaml
receivers:
  - name: 'ai-diagnostic'
    webhook_configs:
      - url: 'http://agent:8000/api/v1/webhooks/prometheus'
        http_config:
          headers:
            X-Webhook-Token: 'your-token'
```

### Zabbix Media Type
```javascript
// Zabbix Media Type webhook script
var req = new HttpRequest();
req.addHeader('Content-Type: application/json');
req.addHeader('X-Webhook-Token: your-token');
var resp = req.post('http://agent:8000/api/v1/webhooks/zabbix', JSON.stringify({
    event_id: '{EVENT.ID}',
    host: '{HOST.NAME}',
    trigger_name: '{TRIGGER.NAME}',
    severity: '{TRIGGER.SEVERITY}',
    status: '{TRIGGER.STATUS}',
    description: '{TRIGGER.DESCRIPTION}'
}));
```

### ElastAlert2 (含 MySQL 慢查询规则)
```yaml
alert:
  - post
http_post_url: "http://agent:8000/api/v1/webhooks/elastalert"
http_post_headers:
  X-Webhook-Token: "your-token"
```

### XXL-Job
在任务配置中设置失败回调 URL：`http://agent:8000/api/v1/webhooks/xxl-job`

## 验证方式

1. 启动服务：`uvicorn app.main:app --port 8000`
2. 用 curl 模拟各系统推送：
   - `curl -X POST http://localhost:8000/api/v1/webhooks/prometheus -H "Content-Type: application/json" -d '{"status":"firing","alerts":[...]}'`
3. 验证返回 202 + diagnosis_id
4. 验证去重：相同 payload 5分钟内再次发送，应返回 200 + duplicate 提示
5. 验证认证：设置 WEBHOOK_TOKEN 后，无 token 请求应返回 401
6. `GET /api/v1/diagnoses/{id}` 确认诊断流程正常启动

## 关键文件

- `app/api/routes.py` — 现有路由，需提取依赖
- `app/schemas/alerts.py` — AlertEventCreate 模型，webhook 适配器的目标格式
- `app/config.py` — 新增配置项
- `app/main.py` — 注册新路由
- `app/workflow/engine.py` — create() + run() 方法，webhook 调用入口
