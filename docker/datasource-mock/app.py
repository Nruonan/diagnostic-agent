import os
import re
from base64 import b64decode
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
import pymysql
from fastapi import FastAPI, Query


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value >= minimum else default


app = FastAPI(title="Diagnostic Datasource Bridge", version="0.2.0")

ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200").rstrip("/")
XXL_JOB_MYSQL_HOST = os.getenv("XXL_JOB_MYSQL_HOST", "xxl-job-mysql")
XXL_JOB_MYSQL_PORT = _env_int("XXL_JOB_MYSQL_PORT", 3306)
XXL_JOB_MYSQL_DATABASE = os.getenv("XXL_JOB_MYSQL_DATABASE", "xxl_job")
XXL_JOB_MYSQL_USER = os.getenv("XXL_JOB_MYSQL_USER", "xxl_job")
XXL_JOB_MYSQL_PASSWORD = os.getenv("XXL_JOB_MYSQL_PASSWORD", "xxl_job")
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPOSITORIES = os.getenv("GITHUB_REPOSITORIES", "")
GITHUB_REF = os.getenv("GITHUB_REF", "")
GITHUB_CODE_MAX_RESULTS = _env_int("GITHUB_CODE_MAX_RESULTS", 5)
GITHUB_CODE_CONTEXT_LINES = _env_int("GITHUB_CODE_CONTEXT_LINES", 8)
GITHUB_CODE_MAX_FILE_BYTES = _env_int("GITHUB_CODE_MAX_FILE_BYTES", 200000)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "live-bridge",
        "elasticsearch_url": ELASTICSEARCH_URL,
        "xxl_job_mysql_host": XXL_JOB_MYSQL_HOST,
        "github_repositories": _github_repositories(),
    }


@app.get("/elk")
async def elk(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    hits = await _search_elasticsearch("app-logs-*,logs-*,mysql-slow-query-*", service_hint)
    return {"items": [_hit_to_log(hit) for hit in hits]}


@app.get("/slow-query")
async def slow_query(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    hits = await _search_elasticsearch("mysql-slow-query-*", service_hint)
    return {"items": [_hit_to_slow_query(hit) for hit in hits if _hit_to_slow_query(hit)]}


@app.get("/xxl-job")
async def xxl_job(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {"items": _fetch_xxl_job_failures(service_hint)}


@app.get("/zabbix")
async def zabbix(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {"items": []}


@app.get("/trace")
async def trace(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    hits = await _search_elasticsearch("traces-*,apm-*-transaction*,apm-*-span*", service_hint)
    return {"items": [_hit_to_trace(hit) for hit in hits if _hit_to_trace(hit)]}


@app.get("/git-code")
async def git_code(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {"items": await _search_github_code(fault_description, service_hint)}


@app.get("/prometheus")
async def prometheus(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {"items": []}


async def _search_elasticsearch(index: str, service_hint: str | None, size: int = 25) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"match_all": {}}
    if service_hint:
        query = {
            "multi_match": {
                "query": service_hint,
                "fields": ["service^3", "service_name^3", "app", "host", "message", "trace_id"],
                "lenient": True,
            }
        }

    body = {
        "size": size,
        "query": query,
        "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
    }
    url = f"{ELASTICSEARCH_URL}/{index}/_search"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, params={"ignore_unavailable": "true"}, json=body)
        response.raise_for_status()
        payload = response.json()
    return payload.get("hits", {}).get("hits", [])


def _source(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source")
    return source if isinstance(source, dict) else {}


def _timestamp(value: Any = None) -> str:
    if value:
        return str(value)
    return datetime.now(timezone.utc).isoformat()


def _hit_to_log(hit: dict[str, Any]) -> dict[str, Any]:
    source = _source(hit)
    query_time = _float_value(source.get("query_time"))
    sql = source.get("sql") or source.get("query")
    message = source.get("message")
    if not message and sql:
        message = f"Slow query detected: {sql}"
    return {
        "timestamp": _timestamp(source.get("@timestamp") or source.get("timestamp")),
        "service": str(source.get("service") or source.get("service_name") or source.get("app") or "elasticsearch"),
        "level": str(source.get("level") or ("WARN" if query_time else "INFO")),
        "message": str(message or f"Elasticsearch document {hit.get('_id', '')} matched diagnostic query"),
        "trace_id": source.get("trace_id"),
        "error_type": source.get("error_type") or ("SlowQuery" if query_time else None),
        "stack_trace": source.get("stack_trace"),
    }


def _hit_to_slow_query(hit: dict[str, Any]) -> dict[str, Any] | None:
    source = _source(hit)
    sql = source.get("sql") or source.get("query")
    query_time = _float_value(source.get("query_time"))
    exec_time_ms = _int_value(source.get("exec_time_ms"))
    if not sql and not query_time and not exec_time_ms:
        return None
    return {
        "timestamp": _timestamp(source.get("@timestamp") or source.get("timestamp")),
        "service": str(source.get("service") or source.get("service_name") or "mysql"),
        "database": str(source.get("database") or source.get("db") or "mysql"),
        "query": str(sql or "unknown"),
        "exec_time_ms": exec_time_ms or int((query_time or 0) * 1000),
        "rows_examined": _int_value(source.get("rows_examined")) or 0,
        "lock_time_ms": _int_value(source.get("lock_time_ms")) or 0,
        "trace_id": source.get("trace_id"),
    }


def _hit_to_trace(hit: dict[str, Any]) -> dict[str, Any] | None:
    source = _source(hit)
    trace_id = source.get("trace_id") or source.get("trace.id")
    span_id = source.get("span_id") or source.get("span.id") or hit.get("_id")
    if not trace_id or not span_id:
        return None
    return {
        "trace_id": str(trace_id),
        "span_id": str(span_id),
        "parent_span_id": source.get("parent_span_id") or source.get("parent.id"),
        "service": str(source.get("service") or source.get("service.name") or "unknown"),
        "operation": str(source.get("operation") or source.get("transaction.name") or source.get("name") or "unknown"),
        "start_time": _timestamp(source.get("@timestamp") or source.get("start_time")),
        "duration_ms": _int_value(source.get("duration_ms") or source.get("event.duration")) or 0,
        "status": str(source.get("status") or source.get("event.outcome") or "unknown"),
    }


def _fetch_xxl_job_failures(service_hint: str | None) -> list[dict[str, Any]]:
    sql = """
        SELECT
            l.job_id,
            l.job_group,
            l.executor_address,
            l.executor_handler,
            l.trigger_time,
            l.handle_time,
            l.handle_code,
            l.handle_msg,
            i.job_desc
        FROM xxl_job_log l
        LEFT JOIN xxl_job_info i ON i.id = l.job_id
        WHERE l.handle_code <> 200
        ORDER BY COALESCE(l.handle_time, l.trigger_time) DESC
        LIMIT 25
    """
    connection = pymysql.connect(
        host=XXL_JOB_MYSQL_HOST,
        port=XXL_JOB_MYSQL_PORT,
        user=XXL_JOB_MYSQL_USER,
        password=XXL_JOB_MYSQL_PASSWORD,
        database=XXL_JOB_MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
    finally:
        connection.close()

    items = [_xxl_row_to_job(row) for row in rows]
    if service_hint:
        normalized = service_hint.strip().lower()
        filtered = [
            item
            for item in items
            if normalized in item["job_name"].lower()
            or normalized in item["message"].lower()
            or normalized in str(item.get("trace_id") or "").lower()
        ]
        return filtered or items
    return items


def _xxl_row_to_job(row: dict[str, Any]) -> dict[str, Any]:
    timestamp = row.get("handle_time") or row.get("trigger_time")
    job_name = row.get("job_desc") or row.get("executor_handler") or f"xxl-job-{row.get('job_id')}"
    return {
        "timestamp": _timestamp(timestamp.isoformat() if hasattr(timestamp, "isoformat") else timestamp),
        "job_name": str(job_name),
        "status": "FAILED",
        "duration_ms": 0,
        "message": str(row.get("handle_msg") or f"XXL-Job failed with handle_code={row.get('handle_code')}"),
        "trace_id": f"xxl-job-{row.get('job_id')}-{row.get('job_group')}",
    }


async def _search_github_code(fault_description: str, service_hint: str | None) -> list[dict[str, Any]]:
    repositories = _github_repositories()
    terms = _code_search_terms(fault_description, service_hint)
    if not repositories or not terms:
        return []

    headers = _github_headers()
    snippets: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        for repository in repositories:
            search_items = await _github_search_repository(client, repository, terms)
            if not search_items:
                search_items = await _github_tree_candidates(client, repository, terms, service_hint)
            for item in search_items:
                path = str(item.get("path") or "")
                repo_name = _github_item_repository(item) or repository
                identity = (repo_name, path)
                if not path or identity in seen:
                    continue
                seen.add(identity)
                content = await _github_file_content(client, repo_name, path)
                if not content:
                    continue
                snippets.append(_code_snippet(repo_name, path, content, terms, service_hint))
                if len(snippets) >= GITHUB_CODE_MAX_RESULTS:
                    return snippets
    return snippets


async def _github_search_repository(
    client: httpx.AsyncClient,
    repository: str,
    terms: list[str],
) -> list[dict[str, Any]]:
    query = f"{' '.join(terms[:5])} repo:{repository}"
    try:
        response = await client.get(
            f"{GITHUB_API_URL}/search/code",
            params={"q": query, "per_page": min(max(GITHUB_CODE_MAX_RESULTS * 2, 1), 20)},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    items = payload.get("items", [])
    return items if isinstance(items, list) else []


async def _github_file_content(client: httpx.AsyncClient, repository: str, path: str) -> str | None:
    encoded_path = quote(path, safe="/")
    payload = await _github_content_payload(client, repository, encoded_path, GITHUB_REF)
    if payload is None and GITHUB_REF:
        payload = await _github_content_payload(client, repository, encoded_path, None)
    if payload is None:
        return None

    if payload.get("type") != "file":
        return None
    file_size = _int_value(payload.get("size"))
    if file_size and file_size > GITHUB_CODE_MAX_FILE_BYTES:
        return None
    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        return None
    try:
        return b64decode(payload["content"]).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return None


async def _github_content_payload(
    client: httpx.AsyncClient,
    repository: str,
    encoded_path: str,
    ref: str | None,
) -> dict[str, Any] | None:
    params = {"ref": ref} if ref else None
    try:
        response = await client.get(f"{GITHUB_API_URL}/repos/{repository}/contents/{encoded_path}", params=params)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


async def _github_tree_candidates(
    client: httpx.AsyncClient,
    repository: str,
    terms: list[str],
    service_hint: str | None,
) -> list[dict[str, Any]]:
    tree = await _github_repository_tree(client, repository, GITHUB_REF)
    if not tree and GITHUB_REF:
        default_ref = await _github_default_branch(client, repository)
        tree = await _github_repository_tree(client, repository, default_ref)
    candidates = [
        item
        for item in tree
        if item.get("type") == "blob" and _is_supported_code_path(str(item.get("path") or ""))
    ]
    candidates.sort(key=lambda item: _path_score(str(item.get("path") or ""), terms, service_hint), reverse=True)
    return [{"path": item.get("path"), "repository": {"full_name": repository}} for item in candidates[:25]]


async def _github_repository_tree(
    client: httpx.AsyncClient,
    repository: str,
    ref: str | None,
) -> list[dict[str, Any]]:
    if not ref:
        return []
    try:
        response = await client.get(
            f"{GITHUB_API_URL}/repos/{repository}/git/trees/{quote(ref, safe='')}",
            params={"recursive": "1"},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    if payload.get("truncated"):
        return []
    tree = payload.get("tree", [])
    return tree if isinstance(tree, list) else []


async def _github_default_branch(client: httpx.AsyncClient, repository: str) -> str | None:
    try:
        response = await client.get(f"{GITHUB_API_URL}/repos/{repository}")
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    default_branch = payload.get("default_branch")
    return default_branch if isinstance(default_branch, str) else None


def _code_snippet(
    repository: str,
    path: str,
    content: str,
    terms: list[str],
    service_hint: str | None,
) -> dict[str, Any]:
    lines = content.splitlines()
    match_line = _first_matching_line(lines, terms)
    start_line = max(match_line - GITHUB_CODE_CONTEXT_LINES, 1)
    end_line = min(match_line + GITHUB_CODE_CONTEXT_LINES, len(lines))
    snippet_lines = lines[start_line - 1 : end_line]
    return {
        "repository": repository,
        "file_path": path,
        "service": service_hint or repository.rsplit("/", 1)[-1],
        "start_line": start_line,
        "end_line": end_line,
        "language": _language_from_path(path),
        "content": "\n".join(snippet_lines),
    }


def _first_matching_line(lines: list[str], terms: list[str]) -> int:
    normalized_terms = [term.lower() for term in terms]
    for index, line in enumerate(lines, start=1):
        normalized_line = line.lower()
        if any(term in normalized_line for term in normalized_terms):
            return index
    return 1


def _is_supported_code_path(path: str) -> bool:
    normalized = path.lower()
    if any(part in normalized for part in _CODE_PATH_EXCLUDES):
        return False
    return normalized.endswith(_CODE_FILE_EXTENSIONS)


def _path_score(path: str, terms: list[str], service_hint: str | None) -> int:
    normalized = path.lower()
    score = 0
    for term in terms:
        if term in normalized:
            score += 3
    if service_hint and service_hint.lower() in normalized:
        score += 5
    if normalized.startswith(("app/", "src/", "internal/", "pkg/")):
        score += 2
    return score


def _code_search_terms(fault_description: str, service_hint: str | None) -> list[str]:
    raw_text = " ".join(value for value in (service_hint, fault_description) if value)
    candidates = re.findall(
        r"[A-Za-z_][A-Za-z0-9_.-]{2,}|[0-9]+[A-Za-z_][A-Za-z0-9_.-]*",
        raw_text,
    )
    terms: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip("._-").lower()
        if normalized and normalized not in terms and normalized not in _CODE_SEARCH_STOPWORDS:
            terms.append(normalized)
    for keyword, replacements in _CODE_SEARCH_TRANSLATIONS.items():
        if keyword in raw_text:
            for replacement in replacements:
                if replacement not in terms:
                    terms.append(replacement)
    return terms[:8]


def _github_repositories() -> list[str]:
    repositories: list[str] = []
    for value in GITHUB_REPOSITORIES.split(","):
        normalized = _normalize_github_repository(value)
        if normalized and normalized not in repositories:
            repositories.append(normalized)
    return repositories


def _normalize_github_repository(value: str) -> str | None:
    normalized = value.strip().removesuffix(".git").strip("/")
    normalized = normalized.removeprefix("https://github.com/").removeprefix("http://github.com/")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", normalized):
        return normalized
    return None


def _github_item_repository(item: dict[str, Any]) -> str | None:
    repository = item.get("repository")
    if isinstance(repository, dict) and isinstance(repository.get("full_name"), str):
        return repository["full_name"]
    return None


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-diagnostic-agent-datasource",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _language_from_path(path: str) -> str:
    extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {
        "go": "go",
        "java": "java",
        "js": "javascript",
        "jsx": "javascript",
        "kt": "kotlin",
        "md": "markdown",
        "php": "php",
        "py": "python",
        "rb": "ruby",
        "rs": "rust",
        "sql": "sql",
        "ts": "typescript",
        "tsx": "typescript",
        "yaml": "yaml",
        "yml": "yaml",
    }.get(extension, extension or "text")


_CODE_SEARCH_STOPWORDS = {
    "and",
    "api",
    "are",
    "for",
    "http",
    "https",
    "service",
    "the",
    "with",
}

_CODE_SEARCH_TRANSLATIONS = {
    "登录": ["login", "auth"],
    "认证": ["auth", "authentication"],
    "鉴权": ["auth", "authorization"],
    "下单": ["order", "checkout"],
    "支付": ["payment", "pay"],
    "超时": ["timeout"],
    "错误": ["error"],
    "异常": ["exception"],
    "数据库": ["database", "db"],
    "慢查询": ["slow", "query"],
    "查询": ["query"],
    "缓存": ["cache"],
}

_CODE_FILE_EXTENSIONS = (
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sql",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
)

_CODE_PATH_EXCLUDES = (
    ".git/",
    ".venv/",
    "__pycache__/",
    "dist/",
    "node_modules/",
    "uv.lock",
)


def _int_value(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
