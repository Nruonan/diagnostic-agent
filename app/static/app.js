const state = {
  diagnosis: null,
  busy: false,
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
  needInputList: document.querySelector("#needInputList"),
  fixList: document.querySelector("#fixList"),
  evidenceList: document.querySelector("#evidenceList"),
  dataSourceCounts: document.querySelector("#dataSourceCounts"),
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
  nodes.llmStatus.textContent = `LLM ${data.llm_provider || "--"} ${data.llm_configured ? "已配置" : "未配置"}`;
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
  nodes.confidenceValue.textContent = root ? Number(root.confidence).toFixed(2) : "--";
  nodes.evidenceValue.textContent = root?.evidence?.length ?? "--";
  nodes.fixValue.textContent = root?.fix_steps?.length ?? "--";
  nodes.rootCause.textContent = root?.root_cause || "暂无结果";
  nodes.rootCause.className = root?.root_cause ? "" : "empty";

  renderList(nodes.needInputList, diagnosis.need_user_input || []);
  renderList(nodes.evidenceList, root?.evidence || []);
  renderList(nodes.fixList, root?.fix_steps || []);
  renderSourceCounts(diagnosis.collected_data);
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
    setMessage("诊断运行中", "is-warn");
    const payload = {
      fault_description: nodes.faultDescription.value.trim(),
      service_hint: nodes.serviceHint.value.trim() || null,
    };
    const data = await request("/api/v1/diagnoses", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderDiagnosis(data.diagnosis);
    setMessage("诊断已返回", "is-ok");
  } catch (error) {
    setMessage(`诊断失败：${error.message}`, "is-danger");
  } finally {
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

nodes.diagnosisForm.addEventListener("submit", createDiagnosis);
nodes.lookupForm.addEventListener("submit", lookupDiagnosis);
nodes.humanInputForm.addEventListener("submit", submitHumanInput);
nodes.loadMarkdown.addEventListener("click", loadMarkdownReport);

loadHealth();
