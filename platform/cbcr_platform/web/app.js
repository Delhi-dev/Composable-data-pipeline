const state = { functions: [], catalogue: [], sources: [], profiles: [], datasets: [], selected: new Map() };
const $ = (q) => document.querySelector(q);
const actor = () => $("#actor").value;
const api = async (url, options = {}) => {
  const response = await fetch(url, { ...options, headers: { "content-type": "application/json", "x-cbcr-user": actor(), ...(options.headers || {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `${response.status} ${response.statusText}`);
  return response.status === 204 ? null : response.json();
};
const toast = (message, error = false) => { const el = $("#toast"); el.textContent = message; el.className = error ? "show error" : "show"; setTimeout(() => el.className = "", 3500); };
const title = (value) => value.replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());

function switchView(id) {
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("active", b.dataset.view === id));
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === id));
  if (id === "runs") loadRuns();
  if (id === "sources") loadAccess();
  if (id === "lifecycle") loadDatasets();
}
document.querySelectorAll("nav button").forEach(b => b.onclick = () => switchView(b.dataset.view));

function renderFunctions() {
  const purpose = $("#purpose").value;
  const functions = state.functions.filter(fn => fn.purpose === purpose);
  $("#functionPicker").innerHTML = functions.map(fn => `
    <article class="function ${state.selected.has(fn.code) ? "selected" : ""}" data-code="${fn.code}">
      <label><input type="checkbox" ${state.selected.has(fn.code) ? "checked" : ""}><span class="stage">Stage ${fn.stage}</span><strong>${fn.name}</strong></label>
      <p>${fn.description}</p>
      <div class="parameters">${Object.entries(fn.parameter_schema).map(([key, spec]) => `<label>${title(key)}<input data-param="${key}" type="${spec.type === "boolean" ? "checkbox" : "text"}" ${spec.type === "boolean" && spec.default ? "checked" : `value='${Array.isArray(spec.default) ? spec.default.join(",") : spec.default ?? ""}'`}></label>`).join("")}</div>
    </article>`).join("") || `<p class="empty">No active functions match this purpose.</p>`;
  document.querySelectorAll(".function").forEach(card => {
    const checkbox = card.querySelector('input[type="checkbox"]');
    checkbox.onchange = () => { checkbox.checked ? state.selected.set(card.dataset.code, {}) : state.selected.delete(card.dataset.code); renderFunctions(); updateSummary(); };
  });
}
function updateSummary() { $("#selectionSummary").textContent = state.selected.size ? `${state.selected.size} independent function${state.selected.size > 1 ? "s" : ""} selected` : "No functions selected"; }
$("#purpose").onchange = () => { state.selected.clear(); renderFunctions(); updateSummary(); };

async function submitRun() {
  const selectedCards = [...document.querySelectorAll(".function.selected")];
  if (!selectedCards.length) return toast("Select at least one function.", true);
  const parameters = {};
  for (const card of selectedCards) {
    const fn = state.functions.find(item => item.code === card.dataset.code);
    parameters[fn.code] = {};
    card.querySelectorAll("[data-param]").forEach(input => {
      const spec = fn.parameter_schema[input.dataset.param]; let value = input.type === "checkbox" ? input.checked : input.value;
      if (spec.type === "number") value = Number(value); if (spec.type === "integer") value = parseInt(value, 10);
      if (spec.type === "array") value = value.split(",").map(x => x.trim()).filter(Boolean);
      parameters[fn.code][input.dataset.param] = value;
    });
  }
  const ids = $("#reportIds").value.split(",").map(x => x.trim()).filter(Boolean);
  try {
    const result = await api("/api/v1/runs", { method: "POST", body: JSON.stringify({ source_id: $("#source").value, report_ids: ids.length ? ids : null, functions: selectedCards.map(c => c.dataset.code), parameters, purpose: $("#purpose").value }) });
    toast(`Run ${result.run_id.slice(0, 8)} queued.`); switchView("runs");
  } catch (error) { toast(error.message, true); }
}
$("#submitRun").onclick = submitRun;

async function loadRuns() {
  try {
    const runs = await api("/api/v1/runs");
    $("#runList").innerHTML = runs.map(run => `<button class="run-card" data-id="${run.run_id}"><span class="status ${run.status}">${title(run.status)}</span><strong>${run.run_id.slice(0, 8)}</strong><small>${run.source_id} · ${title(run.purpose)}</small><time>${new Date(run.created_at).toLocaleString()}</time></button>`).join("") || `<p class="empty">No runs yet.</p>`;
    document.querySelectorAll(".run-card").forEach(card => card.onclick = () => loadRun(card.dataset.id));
  } catch (error) { toast(error.message, true); }
}
async function loadRun(id) {
  try {
    const [run, findings] = await Promise.all([api(`/api/v1/runs/${id}`), api(`/api/v1/runs/${id}/findings`)]);
    $("#runDetail").innerHTML = `<div class="detail"><div class="section-head"><div><p class="step">Pinned execution</p><h2>${id}</h2></div><span class="status ${run.status}">${title(run.status)}</span></div><div class="children">${run.function_runs.map(fn => `<article><span>Stage ${fn.stage}</span><strong>${title(fn.function_code)}</strong><span class="status ${fn.status}">${title(fn.status)}</span><pre>${JSON.stringify(fn.summary || fn.error || {}, null, 2)}</pre></article>`).join("")}</div><h3>Findings (${findings.length})</h3>${findings.map(f => `<div class="finding ${f.severity}"><strong>${f.code}</strong><span>${f.function_code} · ${f.report_id || "run"}</span><p>${f.message}</p><code>${JSON.stringify(f.evidence)}</code></div>`).join("") || `<p class="empty">No findings.</p>`}</div>`;
    if (["queued", "running"].includes(run.status)) setTimeout(() => loadRun(id), 500);
  } catch (error) { toast(error.message, true); }
}
$("#refreshRuns").onclick = loadRuns;

async function waitForRun(runId) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const run = await api(`/api/v1/runs/${runId}`);
    if (run.status.startsWith("completed")) return run;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error("Run did not complete within the demonstration timeout.");
}
function nextZone(dataset) {
  const profile = state.profiles.find(item => item.profile_id === dataset.pipeline_profile_id);
  if (!profile) return null;
  return profile.route[profile.route.indexOf(dataset.zone) + 1] || null;
}
async function loadDatasets() {
  try {
    const [datasets, risk, batches] = await Promise.all([api("/api/v1/datasets"), api("/api/v1/risk-results"), api("/api/v1/selection-batches")]);
    state.datasets = datasets;
    $("#datasetFlow").innerHTML = datasets.map((dataset, index) => `<article class="dataset-card zone-${dataset.zone}">
      <span class="zone-label">${title(dataset.zone)}</span><strong>${dataset.dataset_id.slice(0, 11)}</strong>
      <small>v${dataset.version} · ${dataset.report_count} report(s)</small><code>${dataset.pipeline_profile_id}</code>
      <div class="dataset-actions">${dataset.zone === "canonical" ? `<button data-dataset-action="dq" data-index="${index}">Run DQ and publish</button>` : ""}${["dq_passed", "enriched"].includes(dataset.zone) && nextZone(dataset) ? `<button data-dataset-action="promote" data-index="${index}">Publish ${title(nextZone(dataset))}</button>` : ""}${dataset.zone === "risk_ready" ? `<button data-dataset-action="risk" data-index="${index}">Run risk APIs</button><button data-dataset-action="select" data-index="${index}">Generate candidates</button>` : ""}</div>
    </article>`).join("") || `<p class="empty">No governed datasets yet. Ingest a lot to begin.</p>`;
    document.querySelectorAll("[data-dataset-action]").forEach(button => button.onclick = () => datasetAction(button));
    $("#riskResultList").innerHTML = risk.slice(-8).map(row => `<article><strong>${title(row.rule_code)}</strong><code>${row.report_id || "dataset output"}</code><span class="status active">persisted</span></article>`).join("") || `<p class="empty">No risk results yet.</p>`;
    const candidateSets = await Promise.all(batches.map(batch => api(`/api/v1/selection-batches/${batch.selection_batch_id}/candidates`)));
    const candidates = candidateSets.flat();
    $("#candidateList").innerHTML = candidates.map(candidate => `<article><strong>${candidate.entity_name || candidate.report_id}</strong><code>${candidate.reason_code}</code><span class="status ${candidate.decision === "pending" ? "queued" : "completed"}">${candidate.decision}</span>${candidate.decision === "pending" ? `<button data-candidate="${candidate.candidate_id}">Select</button>` : ""}</article>`).join("") || `<p class="empty">No selection candidates yet.</p>`;
    document.querySelectorAll("[data-candidate]").forEach(button => button.onclick = async () => { try { await api(`/api/v1/selection-candidates/${button.dataset.candidate}/decision`, { method: "PUT", body: JSON.stringify({ decision: "selected", rationale: "Selected in lifecycle PoC review" }) }); toast("Candidate decision persisted."); loadDatasets(); } catch (error) { toast(error.message, true); } });
  } catch (error) { toast(error.message, true); }
}
async function datasetAction(button) {
  const dataset = state.datasets[Number(button.dataset.index)]; const action = button.dataset.datasetAction;
  try {
    button.disabled = true;
    if (action === "dq") {
      const queued = await api("/api/v1/dataset-runs", { method: "POST", body: JSON.stringify({ dataset_id: dataset.dataset_id, dataset_version: dataset.version, input_zone: dataset.zone, functions: ["check_completeness", "check_rpt_share_threshold"], parameters: {}, purpose: "data_quality" }) });
      await waitForRun(queued.run_id);
      const evaluation = await api(`/api/v1/datasets/${dataset.dataset_id}/versions/${dataset.version}/evaluate-promotion`, { method: "POST", body: JSON.stringify({ run_id: queued.run_id, blocking_severities: ["error"] }) });
      await api(`/api/v1/datasets/${dataset.dataset_id}/versions/${dataset.version}/promote`, { method: "POST", body: JSON.stringify({ target_zone: "dq_passed", evaluation_id: evaluation.evaluation_id, reason: "UI PoC DQ publication" }) });
    } else if (action === "promote") {
      const target = nextZone(dataset); const enrichments = target === "enriched" ? [{ report_id: "RPT-2025-001", entity_id: "ENT-IN-01", attribute_name: "domestic_registry_status", value: "active", source_ref: "demo-domestic-registry", confidence: 0.99 }] : [];
      await api(`/api/v1/datasets/${dataset.dataset_id}/versions/${dataset.version}/promote`, { method: "POST", body: JSON.stringify({ target_zone: target, enrichment_values: enrichments, reason: "UI PoC governed publication" }) });
    } else {
      const functions = action === "risk" ? ["analyze_etr_outlier", "score_risk_components"] : ["generate_case_candidates"];
      const purpose = action === "risk" ? "risk_assessment" : "case_review";
      const queued = await api("/api/v1/dataset-runs", { method: "POST", body: JSON.stringify({ dataset_id: dataset.dataset_id, dataset_version: dataset.version, input_zone: "risk_ready", functions, parameters: {}, purpose }) });
      await waitForRun(queued.run_id);
    }
    toast("Lifecycle action completed and persisted."); await loadDatasets();
  } catch (error) { toast(error.message, true); } finally { button.disabled = false; }
}
$("#ingestLot").onclick = async () => { try { await api("/api/v1/lots", { method: "POST", body: JSON.stringify({ source_id: $("#lifecycleSource").value, pipeline_profile_id: $("#pipelineProfile").value, metadata: { demonstration: true } }) }); toast("Landing and canonical datasets created."); loadDatasets(); } catch (error) { toast(error.message, true); } };
$("#refreshDatasets").onclick = loadDatasets;

function renderCatalogue() {
  const groups = Object.groupBy(state.catalogue, fn => fn.stage);
  $("#catalogueList").innerHTML = Object.entries(groups).map(([stage, rows]) => `<section><h3>Stage ${stage}</h3>${rows.map(fn => `<article><div><strong>${fn.name}</strong><code>${fn.code} · v${fn.version} · ${fn.lifecycle}</code></div><span>${title(fn.purpose)}</span><p>${fn.description}</p><div class="lifecycle-actions">${fn.lifecycle === "draft" ? `<button data-action="activate" data-code="${fn.code}" data-version="${fn.version}">Activate</button><button data-action="delete" data-code="${fn.code}" data-version="${fn.version}">Delete draft</button>` : fn.lifecycle === "active" ? `<button data-action="retire" data-code="${fn.code}" data-version="${fn.version}">Retire</button>` : ""}</div></article>`).join("")}</section>`).join("");
  document.querySelectorAll("[data-action]").forEach(button => button.onclick = () => changeLifecycle(button));
}
async function reloadCatalogue() {
  [state.functions, state.catalogue] = await Promise.all([api("/api/v1/functions"), api("/api/v1/functions?lifecycle=")]);
  renderFunctions(); renderCatalogue();
}
async function changeLifecycle(button) {
  const { action, code, version } = button.dataset;
  const method = action === "delete" ? "DELETE" : "POST";
  const suffix = action === "delete" ? "" : `/${action}`;
  try { await api(`/api/v1/functions/${code}/versions/${version}${suffix}`, { method }); await reloadCatalogue(); toast(`Function ${action} complete.`); }
  catch (error) { toast(error.message, true); }
}
$("#functionForm").onsubmit = async event => {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form));
  try { data.parameter_schema = JSON.parse(data.parameter_schema); await api("/api/v1/functions", { method: "POST", body: JSON.stringify(data) });
    await reloadCatalogue(); toast("Function draft saved."); form.reset();
  } catch (error) { toast(error.message, true); }
};
async function loadAccess() {
  $("#sourceList").innerHTML = state.sources.map(source => `<article><span class="status active">${source.adapter_type}</span><strong>${source.name}</strong><code>${source.endpoint_link}</code><small>Secret ref: ${source.secret_ref || "none (fixture)"}</small></article>`).join("");
  try {
    const [users, roles] = await Promise.all([api("/api/v1/users"), api("/api/v1/roles")]);
    $("#userList").innerHTML = users.map(user => `<article><strong>${user.display_name}</strong><code>${user.user_id}</code><div class="chips">${user.roles.map(role => `<span>${role}</span>`).join("")}</div></article>`).join("");
    $("#rolePicker").innerHTML = roles.map(role => `<label><input type="checkbox" value="${role.role_id}">${role.name}</label>`).join("");
  } catch (error) { $("#userList").innerHTML = `<p class="empty">${error.message}</p>`; }
}
$("#sourceForm").onsubmit = async event => {
  event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget));
  if (!data.secret_ref) data.secret_ref = null;
  try { await api(`/api/v1/sources/${data.source_id}`, { method: "PUT", body: JSON.stringify(data) });
    state.sources = await api("/api/v1/sources"); toast("Source configuration saved."); loadAccess();
  } catch (error) { toast(error.message, true); }
};
$("#userForm").onsubmit = async event => {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form));
  const role_ids = [...form.querySelectorAll('#rolePicker input:checked')].map(input => input.value);
  try {
    await api("/api/v1/users", { method: "POST", body: JSON.stringify({ user_id: data.user_id, display_name: data.display_name }) });
    await api(`/api/v1/users/${data.user_id}/roles`, { method: "PUT", body: JSON.stringify({ role_ids }) });
    toast("User and role assignments saved."); form.reset(); loadAccess();
  } catch (error) { toast(error.message, true); }
};

async function init() {
  try {
    const [health, sources, functions, catalogue, profiles] = await Promise.all([api("/api/v1/health"), api("/api/v1/sources"), api("/api/v1/functions"), api("/api/v1/functions?lifecycle="), api("/api/v1/pipeline-profiles")]);
    state.sources = sources; state.functions = functions; state.catalogue = catalogue; state.profiles = profiles;
    $("#health").textContent = `System ${health.status} · fixture and PostgreSQL adapters active`;
    $("#source").innerHTML = sources.map(s => `<option value="${s.source_id}">${s.name}</option>`).join("");
    $("#lifecycleSource").innerHTML = sources.map(s => `<option value="${s.source_id}">${s.name}</option>`).join("");
    $("#pipelineProfile").innerHTML = profiles.map(p => `<option value="${p.profile_id}">${p.name}</option>`).join("");
    $("#handlerPicker").innerHTML = [...new Set(functions.map(fn => fn.handler))].sort().map(handler => `<option>${handler}</option>`).join("");
    renderFunctions(); renderCatalogue(); updateSummary();
  } catch (error) { $("#health").textContent = error.message; $("#health").classList.add("bad"); }
}
$("#actor").onchange = () => { if ($("#sources").classList.contains("active")) loadAccess(); };
init();
