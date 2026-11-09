import {api} from "../api.js";
import {esc, fmtDate, idChip, status, bindCommon, permissionError} from "../ui.js";
import {bindLinks} from "../router.js";

export async function render(view, state) {
  try {
    const data = await api(`/api/v1/dashboard?days=30&scope=${state.broad ? "all":"me"}`);
    const c=data.cards, maxZone=Math.max(1,...Object.values(data.lots_by_zone)), maxRun=Math.max(1,...Object.values(data.runs_by_status));
    view.innerHTML=`<div class="page-head"><div><p class="eyebrow">Niche Landing Page</p><h1>Home</h1><p>What needs attention across the governed CbCR workflow. Use Data lifecycle to open a lot or dataset.</p></div><div class="actions"><a href="/lifecycle" data-route class="button">Open data lifecycle</a></div></div>
      <section class="summary-grid">
        ${card(c.failed_runs,"Failed runs","/runs?status=failed","attention")}${card(c.active_runs,"Active runs","/runs?status=queued%2Crunning")}${card(c.awaiting_dq_run,"Awaiting DQ run","/lifecycle?awaiting=dq_run")}${card(c.awaiting_dq_gate,"Awaiting DQ gate","/lifecycle?awaiting=dq_gate")}${card(c.awaiting_publication,"Awaiting publication","/lifecycle?awaiting=publication")}${card(c.awaiting_evidence_approval,"Awaiting evidence approval","/lifecycle?awaiting=evidence")}${card(c.pending_case_decisions,"Pending case decisions","/cases","good")}
      </section>
      <div class="chart-grid"><section class="panel"><div class="panel-head"><h2>Datasets by stage</h2><span class="muted">Last ${data.period_days} days</span></div>${bars(data.lots_by_zone,maxZone)}</section><section class="panel"><div class="panel-head"><h2>Runs by state</h2><span class="muted">Current scope</span></div>${bars(data.runs_by_status,maxRun)}</section></div>
      <section class="panel"><div class="panel-head"><div><h2>Recent workflow activity</h2><p>Recent function runs—not access logs.</p></div><a href="/runs" data-route>View all runs</a></div>${data.recent_runs.length?`<div class="table-wrap"><table><thead><tr><th>Run</th><th>Purpose</th><th>Stage</th><th>Status</th><th>Requested</th><th></th></tr></thead><tbody>${data.recent_runs.map(run=>`<tr><td>${idChip(run.run_id,"run ID")}</td><td>${esc(run.purpose)}</td><td>${esc(run.input_zone||"—")}</td><td>${status(run.status)}</td><td>${fmtDate(run.requested_at||run.created_at)}</td><td><a href="/runs/${esc(run.run_id)}" data-route>Inspect</a></td></tr>`).join("")}</tbody></table></div>`:`<p class="empty-state">No runs in this period.</p>`}</section>`;
    bindCommon(view); bindLinks(view);
  } catch(error){view.innerHTML=permissionError(error,"view the dashboard");}
}
function card(value,label,href,kind=""){return `<article class="summary-card ${kind}"><strong>${value}</strong><span>${label}</span><a href="${href}" data-route>Review</a></article>`}
function bars(values,max){return `<div class="bar-list">${Object.entries(values).map(([label,value])=>`<div class="bar-row"><span>${esc(label.replaceAll("_"," "))}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.round(value/max*100)}%"></div></div><strong>${value}</strong></div>`).join("")}</div>`}
