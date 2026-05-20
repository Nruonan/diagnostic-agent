const state = {
  diagnosis: null,
  busy: false,
  eventSource: null,
};

const nodes = {
  healthText: document.querySelector("#healthText"),
  llmStatus: document.querySelector("#llmStatus"),
  sourceStatus: document.querySelector("#sourceStatus"),
  diagnosisForm: document.querySelector("#diagnosisForm"),
  lookupForm: document.querySelector("#lookupForm"),
  humanInputForm: document.querySelector("#humanInputForm"),
  faultDescription: document.querySelector("#faultDescription"),
  serviceHint: document.querySelector("#serviceHint"),
  diagnosisId: document.querySelector("#diagnosisId"),
  humanInput: document.querySelector("#humanInput"),
  loadMarkdown: document.querySelector("#loadMarkdown"),
  statusValue: document.querySelector("#statusValue"),
  confidenceValue: document.querySelector("#confidenceValue"),
  evidenceValue: document.querySelector("#evidenceValue"),
  fixValue: document.querySelector("#fixValue"),
  activeId: document.querySelector("#activeId"),
  rootCause: document.querySelector("#rootCause"),
  streamStatus: document.querySelector("#streamStatus"),
  eventList: document.querySelector("#eventList"),
  planningMeta: document.querySelector("#planningMeta"),
  planningTasks: document.querySelector("#planningTasks"),
  focusServices: document.querySelector("#focusServices"),
  errorSummary: document.querySelector("#errorSummary"),
  errorItems: document.querySelector("#errorItems"),
  timelineList: document.querySelector("#timelineList"),
  suspectList: document.querySelector("#suspectList"),
  slowSummary: document.querySelector("#slowSummary"),
  slowQueryItems: document.querySelector("#slowQueryItems"),
  sqlOptimizationList: document.querySelector("#sqlOptimizationList"),
  needInputList: document.querySelector("#needInputList"),
  fixList: document.querySelector("#fixList"),
  evidenceList: document.querySelector("#evidenceList"),
  dataSourceCounts: document.querySelector("#dataSourceCounts"),
  collectedDetails: document.querySelector("#collectedDetails"),
  reportBox: document.querySelector("#reportBox"),
};

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof body === "string" ? body : body.detail || JSON.stringify(body);
    throw new Error(message);
  }
  return body;
}

function setBusy(value) {
  state.busy = value;
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = value;
  });
}

function setMessage(text, tone = "") {
  nodes.healthText.textContent = text;
  nodes.healthText.className = tone;
}

function renderHealth(data) {
  nodes.healthText.textContent = "API 在线";
  nodes.healthText.className = "is-ok";
  const configured = data.configured_llm_providers?.length ? data.configured_llm_providers.join(",") : "none";
  nodes.llmStatus.textContent = `LLM ${data.llm_provider || "--"} ${data.llm_configured ? "已配置" : "未配置"} · ${configured}`;
  nodes.llmStatus.className = data.llm_configured ? "is-ok" : "is-danger";
  nodes.sourceStatus.textContent = `DataSource ${data.data_source_mode || "--"}`;
}

function renderDiagnosis(diagnosis) {
  state.diagnosis = diagnosis;
  nodes.diagnosisId.value = diagnosis.diagnosis_id;
  nodes.activeId.textContent = diagnosis.diagnosis_id;
  nodes.statusValue.textContent = diagnosis.status || "--";
  nodes.statusValue.className = statusClass(diagnosis.status);

  const root = diagnosis.root_cause;
  nodes.confidenceValue.textContent = diagnosis.planning?.tasks?.length ?? "--";
  nodes.evidenceValue.textContent = diagnosis.error_analysis?.errors?.length ?? "--";
  nodes.fixValue.textContent = diagnosis.slow_sql_analysis?.slow_queries?.length ?? "--";
  nodes.rootCause.textContent = root
    ? `${root.root_cause}\n\n置信度：${Number(root.confidence).toFixed(2)}`
    : "暂无最终根因，当前已展示上游 Agent 分析结果";
  nodes.rootCause.className = root?.root_cause ? "" : "empty";

  renderPlanning(diagnosis.planning);
  renderErrorAnalysis(diagnosis.error_analysis);
  renderSlowSqlAnalysis(diagnosis.slow_sql_analysis);
  renderList(nodes.needInputList, collectMissingInformation(diagnosis));
  renderList(nodes.evidenceList, root?.evidence || []);
  renderList(nodes.fixList, root?.fix_steps || []);
  renderSourceCounts(diagnosis.collected_data);
  renderCollectedDetails(diagnosis.collected_data);
  nodes.reportBox.textContent = JSON.stringify(diagnosis, null, 2);
}

function statusClass(status) {
  if (status === "completed") return "is-ok";
  if (status === "failed") return "is-danger";
  if (status === "need_user_input") return "is-warn";
  return "";
}

function renderList(target, items) {
  target.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    target.appendChild(li);
  }
}

function renderPlanning(planning) {
  nodes.planningMeta.textContent = planning?.estimated_time ? `预计 ${planning.estimated_time}` : "--";
  nodes.planningTasks.innerHTML = "";
  for (const task of planning?.tasks || []) {
    nodes.planningTasks.appendChild(
      card([
        metaLine(`任务 ${task.id}`, `优先级 ${task.priority}`),
        titleLine(task.name),
        textLine(task.reason),
        pillLine("数据源", task.sources),
        pillLine("依赖", task.dependencies),
      ]),
    );
  }
  renderChips(nodes.focusServices, planning?.focus_services || []);
}

function renderErrorAnalysis(errorAnalysis) {
  renderSummary(nodes.errorSummary, errorAnalysis?.summary);
  nodes.errorItems.innerHTML = "";
  for (const error of errorAnalysis?.errors || []) {
    nodes.errorItems.appendChild(
      card([
        metaLine(error.timestamp, error.service),
        titleLine(error.error_type),
        textLine(error.message),
        optionalLine("Trace", error.trace_id),
        bulletBlock("证据", error.evidence),
      ]),
    );
  }
  renderList(nodes.timelineList, errorAnalysis?.timeline || []);
  renderList(nodes.suspectList, errorAnalysis?.suspects || []);
}

function renderSlowSqlAnalysis(slowSqlAnalysis) {
  renderSummary(nodes.slowSummary, slowSqlAnalysis?.summary);
  nodes.slowQueryItems.innerHTML = "";
  for (const finding of slowSqlAnalysis?.slow_queries || []) {
    nodes.slowQueryItems.appendChild(
      card([
        metaLine(finding.service, `${finding.exec_time_ms}ms / rows ${finding.rows_examined}`),
        codeLine(finding.query),
        optionalLine("Trace", finding.trace_id),
        bulletBlock("问题", finding.issues),
        bulletBlock("优化", finding.optimizations),
      ]),
    );
  }
  renderList(nodes.sqlOptimizationList, slowSqlAnalysis?.optimizations || []);
}

function renderSummary(target, value) {
  target.textContent = value || "暂无结果";
  target.className = value ? "summary-text" : "summary-text empty";
}

function renderChips(target, items) {
  target.innerHTML = "";
  for (const item of items) {
    const chip = document.createElement("span");
    chip.textContent = item;
    target.appendChild(chip);
  }
}

function renderSourceCounts(data) {
  const counts = {
    logs: data?.logs?.length || 0,
    jobs: data?.jobs?.length || 0,
    zabbix: data?.zabbix_events?.length || 0,
    slow: data?.slow_queries?.length || 0,
    metrics: data?.metrics?.length || 0,
    traces: data?.traces?.length || 0,
    code: data?.code_snippets?.length || 0,
    errors: data?.source_errors?.length || 0,
  };
  nodes.dataSourceCounts.innerHTML = "";
  for (const [label, value] of Object.entries(counts)) {
    const item = document.createElement("span");
    item.innerHTML = `<em>${label}</em><strong>${value}</strong>`;
    nodes.dataSourceCounts.appendChild(item);
  }
}

function renderCollectedDetails(data) {
  nodes.collectedDetails.innerHTML = "";
  const groups = [
    ["日志", data?.logs, (item) => `${item.timestamp} · ${item.service} · ${item.level}\n${item.message}`],
    ["XXL-Job", data?.jobs, (item) => `${item.timestamp} · ${item.job_name} · ${item.status}\n${item.message}`],
    ["Zabbix", data?.zabbix_events, (item) => `${item.timestamp} · ${item.service || "--"} · ${item.severity || "--"}\n${item.message}`],
    ["慢 SQL", data?.slow_queries, (item) => `${item.timestamp} · ${item.service} · ${item.exec_time_ms}ms\n${item.query}`],
    ["Prometheus", data?.metrics, (item) => `${item.timestamp || "--"} · ${item.metric} = ${item.value}`],
    ["Trace", data?.traces, (item) => `${item.trace_id} · ${item.service}.${item.operation} · ${item.duration_ms}ms`],
    ["代码片段", data?.code_snippets, (item) => `${item.repository}:${item.file_path}:${item.start_line}-${item.end_line}`],
    ["数据源错误", data?.source_errors, (item) => `${item.source}: ${item.message}`],
  ];

  for (const [label, items, formatter] of groups) {
    const details = document.createElement("details");
    details.className = "detail-group";
    details.open = Boolean(items?.length);
    const summary = document.createElement("summary");
    summary.textContent = `${label} (${items?.length || 0})`;
    details.appendChild(summary);
    if (items?.length) {
      const list = document.createElement("ul");
      list.className = "data-list";
      for (const item of items) {
        const li = document.createElement("li");
        li.textContent = formatter(item);
        list.appendChild(li);
      }
      details.appendChild(list);
    }
    nodes.collectedDetails.appendChild(details);
  }
}

function collectMissingInformation(diagnosis) {
  return uniqueStrings([
    ...(diagnosis.need_user_input || []),
    ...(diagnosis.planning?.missing_information || []),
    ...(diagnosis.error_analysis?.missing_information || []),
    ...(diagnosis.slow_sql_analysis?.missing_information || []),
    ...(diagnosis.root_cause?.missing_information || []),
  ]);
}

function uniqueStrings(items) {
  return [...new Set(items.filter(Boolean))];
}

function card(children) {
  const element = document.createElement("article");
  element.className = "info-card";
  for (const child of children) {
    if (child) element.appendChild(child);
  }
  return element;
}

function metaLine(left, right) {
  const element = document.createElement("div");
  element.className = "card-meta";
  element.innerHTML = `<span>${escapeHtml(left || "--")}</span><span>${escapeHtml(right || "--")}</span>`;
  return element;
}

function titleLine(value) {
  const element = document.createElement("h3");
  element.textContent = value || "--";
  return element;
}

function textLine(value) {
  if (!value) return null;
  const element = document.createElement("p");
  element.textContent = value;
  return element;
}

function optionalLine(label, value) {
  if (!value) return null;
  const element = document.createElement("p");
  element.className = "key-value";
  element.textContent = `${label}: ${value}`;
  return element;
}

function codeLine(value) {
  const element = document.createElement("code");
  element.textContent = value || "--";
  return element;
}

function pillLine(label, items) {
  if (!items?.length) return null;
  const element = document.createElement("div");
  element.className = "pill-row";
  const labelElement = document.createElement("strong");
  labelElement.textContent = label;
  element.appendChild(labelElement);
  for (const item of items) {
    const pill = document.createElement("span");
    pill.textContent = item;
    element.appendChild(pill);
  }
  return element;
}

function bulletBlock(label, items) {
  if (!items?.length) return null;
  const wrapper = document.createElement("div");
  wrapper.className = "bullet-block";
  const title = document.createElement("strong");
  title.textContent = label;
  const list = document.createElement("ul");
  list.className = "data-list";
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  }
  wrapper.append(title, list);
  return wrapper;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadHealth() {
  try {
    renderHealth(await request("/health"));
  } catch (error) {
    setMessage(`API 异常：${error.message}`, "is-danger");
  }
}

async function createDiagnosis(event) {
  event.preventDefault();
  setBusy(true);
  try {
    clearWorkflowEvents();
    setStreamStatus("连接中", "is-warn");
    setMessage("诊断任务创建中", "is-warn");
    const payload = {
      fault_description: nodes.faultDescription.value.trim(),
      service_hint: nodes.serviceHint.value.trim() || null,
    };
    const data = await request("/api/v1/diagnoses/async", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderDiagnosis(data.diagnosis);
    setMessage("诊断运行中", "is-warn");
    connectWorkflowEvents(data.diagnosis.diagnosis_id);
  } catch (error) {
    setMessage(`诊断失败：${error.message}`, "is-danger");
    setBusy(false);
  }
}

async function lookupDiagnosis(event) {
  event.preventDefault();
  const id = nodes.diagnosisId.value.trim();
  if (!id) return;
  setBusy(true);
  try {
    const data = await request(`/api/v1/diagnoses/${encodeURIComponent(id)}`);
    renderDiagnosis(data.diagnosis);
    setMessage("诊断已载入", "is-ok");
  } catch (error) {
    setMessage(`查询失败：${error.message}`, "is-danger");
  } finally {
    setBusy(false);
  }
}

async function submitHumanInput(event) {
  event.preventDefault();
  const id = nodes.diagnosisId.value.trim();
  const content = nodes.humanInput.value.trim();
  if (!id || !content) return;
  setBusy(true);
  try {
    setMessage("补充信息处理中", "is-warn");
    const data = await request(`/api/v1/diagnoses/${encodeURIComponent(id)}/input`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    nodes.humanInput.value = "";
    renderDiagnosis(data.diagnosis);
    setMessage("补充信息已处理", "is-ok");
  } catch (error) {
    setMessage(`提交失败：${error.message}`, "is-danger");
  } finally {
    setBusy(false);
  }
}

async function loadMarkdownReport() {
  const id = nodes.diagnosisId.value.trim();
  if (!id) return;
  setBusy(true);
  try {
    const text = await request(`/api/v1/reports/${encodeURIComponent(id)}/markdown`, {
      headers: { Accept: "text/plain" },
    });
    nodes.reportBox.textContent = text;
    setMessage("Markdown 报告已载入", "is-ok");
  } catch (error) {
    setMessage(`报告加载失败：${error.message}`, "is-danger");
  } finally {
    setBusy(false);
  }
}

function connectWorkflowEvents(diagnosisId) {
  closeWorkflowEvents();
  const source = new EventSource(`/api/v1/diagnoses/${encodeURIComponent(diagnosisId)}/events`);
  state.eventSource = source;
  setStreamStatus("已连接", "is-ok");

  for (const eventName of workflowEventNames()) {
    source.addEventListener(eventName, (message) => handleWorkflowEvent(message));
  }

  source.onerror = () => {
    setStreamStatus("连接重试中", "is-warn");
  };
}

function closeWorkflowEvents() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function workflowEventNames() {
  return [
    "diagnosis_created",
    "diagnosis_started",
    "stage_started",
    "stage_completed",
    "need_user_input",
    "diagnosis_completed",
    "diagnosis_finished",
  ];
}

async function handleWorkflowEvent(message) {
  const event = JSON.parse(message.data);
  appendWorkflowEvent(event);
  applyWorkflowEvent(event);

  if (event.event === "diagnosis_finished") {
    closeWorkflowEvents();
    setStreamStatus("已结束", terminalTone(event.status));
    setBusy(false);
    try {
      const data = await request(`/api/v1/diagnoses/${encodeURIComponent(event.diagnosis_id)}`);
      renderDiagnosis(data.diagnosis);
      setMessage(`诊断状态：${data.diagnosis.status}`, terminalTone(data.diagnosis.status));
    } catch (error) {
      setMessage(`最终状态加载失败：${error.message}`, "is-danger");
    }
  }
}

function applyWorkflowEvent(event) {
  if (!state.diagnosis || state.diagnosis.diagnosis_id !== event.diagnosis_id) return;
  if (event.status) state.diagnosis.status = event.status;
  const payload = event.payload || {};
  if (payload.planning) state.diagnosis.planning = payload.planning;
  if (payload.error_analysis) state.diagnosis.error_analysis = payload.error_analysis;
  if (payload.slow_sql_analysis) state.diagnosis.slow_sql_analysis = payload.slow_sql_analysis;
  if (payload.root_cause) state.diagnosis.root_cause = payload.root_cause;
  if (payload.need_user_input) state.diagnosis.need_user_input = payload.need_user_input;
  renderDiagnosis(state.diagnosis);
}

function appendWorkflowEvent(event) {
  const item = document.createElement("li");
  item.className = terminalTone(event.status);
  const time = new Date(event.created_at).toLocaleTimeString();
  item.innerHTML = `<strong>${escapeHtml(time)}</strong><span>${escapeHtml(event.stage || "workflow")}</span><em>${escapeHtml(event.message)}</em>`;
  nodes.eventList.prepend(item);
  while (nodes.eventList.children.length > 80) {
    nodes.eventList.lastChild.remove();
  }
}

function clearWorkflowEvents() {
  nodes.eventList.innerHTML = "";
}

function setStreamStatus(text, tone = "") {
  nodes.streamStatus.textContent = text;
  nodes.streamStatus.className = tone;
}

function terminalTone(status) {
  if (status === "completed") return "is-ok";
  if (status === "failed") return "is-danger";
  if (status === "need_user_input") return "is-warn";
  return "";
}

nodes.diagnosisForm.addEventListener("submit", createDiagnosis);
nodes.lookupForm.addEventListener("submit", lookupDiagnosis);
nodes.humanInputForm.addEventListener("submit", submitHumanInput);
nodes.loadMarkdown.addEventListener("click", loadMarkdownReport);

loadHealth();
