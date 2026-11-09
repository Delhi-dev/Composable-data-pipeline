import {api} from "./api.js";
import {esc} from "./ui.js";
import {bindLinks, navigate} from "./router.js";

const primary = [
  ["/", "01", "Home", "home"], ["/lifecycle", "02", "Data lifecycle", "lifecycle"],
  ["/runs", "03", "Run history", "runs"], ["/cases", "04", "Case workbench", "cases"],
  ["/reports", "05", "Reports", "reports"],
];

let menuListenersBound = false;

export function renderShell(state, active) {
  const canOversight = state.me.roles.some(role => ["auditor","platform_admin"].includes(role));
  const canSettings = state.me.roles.includes("platform_admin");
  const healthOk = state.health.status === "ok";
  const database = state.health.database || {};
  const actor = localStorage.getItem("cbcr_actor") || state.me.user_id;
  const impersonation = state.health.ui_impersonation && state.impersonationUsers?.length
    ? `<label class="persona-switch">Viewing as<select data-actor-switch>${state.impersonationUsers.map(user => `<option value="${esc(user.user_id)}" ${user.user_id===actor?'selected':''}>${esc(user.display_name)} · ${esc((user.roles||[]).join(', '))}</option>`).join('')}</select></label>` : "";
  document.querySelector("#masthead").innerHTML = `<a class="brand" href="/" data-route><span class="brand-mark">N</span><span><span class="brand-title">CbCR Control Plane</span><span class="brand-sub">Governed data workflow</span></span></a><form class="global-search" data-global-lookup role="search"><input name="value" aria-label="Find by identifier or reference" placeholder="Find by ID or reference…"><output data-lookup-error aria-live="polite"></output></form><span class="mast-spacer"></span><details class="system-menu"><summary class="system-status ${healthOk?'ok':'down'}" aria-label="System status: ${healthOk?'OK':'degraded'}" aria-expanded="false"><span class="status-dot" aria-hidden="true"></span>System ${healthOk?'OK':'degraded'}</summary><div class="system-pop"><strong>Runtime status</strong><dl><dt>Backend</dt><dd>${esc(state.health.persistence_backend||'unknown')}</dd><dt>Database</dt><dd>${esc(database.database||database.current_database||'connected')}</dd><dt>API version</dt><dd>${esc(state.health.version||'—')}</dd><dt>Workers</dt><dd>${esc(state.health.worker_status||'available')}</dd></dl><a href="/docs">API documentation</a></div></details><details class="profile-menu"><summary aria-expanded="false">${esc(state.me.display_name || state.me.user_id)} · ${esc(state.me.persona)} ▾</summary><div class="profile-pop"><strong>${esc(state.me.display_name || state.me.user_id)}</strong><br><small>${esc(state.me.roles.join(", "))}</small>${impersonation}<a href="/reference" data-route>Function reference</a>${canSettings?'<a href="/settings" data-route>Settings</a>':''}<a href="/advanced">Advanced interface</a><a href="/docs">API documentation</a></div></details>`;
  const links = [...primary, ...(canOversight ? [["/oversight","06","Oversight","oversight"]] : [])];
  document.querySelector("#sidebar").innerHTML = `<nav class="primary-nav"><span class="nav-label">Workflow</span>${links.map(([href,num,label,key])=>`<a href="${href}" data-route class="nav-link ${active===key?'active':''}"><span class="nav-num">${num}</span>${label}</a>`).join("")}</nav><nav class="utility-nav"><span class="nav-label">Utilities</span><a href="/reference" data-route class="nav-link ${active==='reference'?'active':''}"><span class="nav-num">ƒ</span>Function reference</a>${canSettings?`<a href="/settings" data-route class="nav-link ${active==='settings'?'active':''}"><span class="nav-num">⚙</span>Settings</a>`:""}</nav>`;
  bindLinks(document.querySelector("#masthead")); bindLinks(document.querySelector("#sidebar"));
  bindMenus();
  document.querySelector("[data-actor-switch]")?.addEventListener("change", event => {
    localStorage.setItem("cbcr_actor", event.target.value);
    location.assign("/");
  });
}

function bindMenus() {
  document.querySelectorAll(".profile-menu,.system-menu").forEach(menu => {
    const summary = menu.querySelector("summary");
    summary?.setAttribute("aria-expanded", String(menu.open));
    menu.addEventListener("toggle", () => summary?.setAttribute("aria-expanded", String(menu.open)));
    menu.querySelectorAll("a").forEach(link => link.addEventListener("click", () => { menu.open = false; }));
  });
  if (menuListenersBound) return;
  menuListenersBound = true;
  document.addEventListener("click", event => document.querySelectorAll("details.profile-menu[open],details.system-menu[open]").forEach(menu => { if (!menu.contains(event.target)) menu.open = false; }));
  document.addEventListener("keydown", event => { if (event.key === "Escape") document.querySelectorAll("details.profile-menu[open],details.system-menu[open]").forEach(menu => { menu.open = false; }); });
}

export function bindGlobalLookup() {
  document.addEventListener("submit", async event => {
    const form = event.target.closest("[data-global-lookup]"); if (!form) return;
    event.preventDefault(); const value = new FormData(form).get("value")?.trim(); if (!value) return;
    try { const result = await api(`/api/v1/lookup?value=${encodeURIComponent(value)}`); navigate(result.route); }
    catch (error) { const output=form.querySelector("[data-lookup-error]"); if(output) output.textContent=error.status===404?"Use a complete ID or external lot reference":error.message; }
  });
}
