/* =====================================================================
   mock.js — behaviour for the static mockups.

   PART A  "shell"  : renders the masthead + sidebar from a persona.
                      This is the reference for "navigation generated
                      from effective permissions" (brief §5.1, §7.1, §9).
   PART B  "widgets": tiny generic behaviours (ID chips, accordions,
                      tabs, menus, dialogs, steppers). These are the
                      component contracts the real niche.js should adopt.
   PART C  "mock"   : persona/theme switcher. NOT part of the product.
   ===================================================================== */

/* ------------------------------------------------------------------ */
/* PART A — application shell                                          */
/* ------------------------------------------------------------------ */

// Business personas used by the mockups. In the product, `roles` is the
// effective role list returned for the AUTHENTICATED user; the persona
// label is derived from it (brief §4). Never from the "Acting as" box.
const PERSONAS = {
  analyst:  { name: "A. Sharma", persona: "Analyst",        roles: ["dq_analyst", "risk_analyst"] },
  reviewer: { name: "R. Mehta",  persona: "Case Reviewer",  roles: ["case_manager"] },
  auditor:  { name: "Auditor",   persona: "Auditor",        roles: ["auditor"] },
  admin:    { name: "demo",      persona: "Administrator",  roles: ["platform_admin", "dq_analyst", "risk_analyst", "case_manager"] },
};

// Primary navigation. `roles` = any of these internal roles may see it.
// Badge counts are illustrative (they come from the dashboard aggregate
// endpoint in the real implementation).
const NAV = [
  { section: "Workflow" },
  { id: "home",      n: "01", label: "Home",            href: "01-home.html",      roles: ["*"] },
  { id: "lifecycle", n: "02", label: "Data lifecycle",  href: "02-lifecycle.html", roles: ["*"] },
  { id: "runs",      n: "03", label: "Run history",     href: "04-runs.html",      roles: ["*"] },
  { id: "cases",     n: "04", label: "Case workbench",  href: "05-cases.html",     roles: ["case_manager", "risk_analyst", "platform_admin", "auditor"], badge: { case_manager: 1, platform_admin: 1 } },
  { id: "reports",   n: "05", label: "Reports",         href: "06-reports.html",   roles: ["*"] },
  { section: "Oversight", roles: ["auditor", "platform_admin"] },
  { id: "oversight", n: "06", label: "Lineage & audit", href: "07-oversight.html", roles: ["auditor", "platform_admin"] },
];

// Utility links shown at the bottom of the sidebar and in the profile menu.
const UTILITY = [
  { id: "reference", label: "Function reference",   href: "09-function-reference.html", roles: ["*"] },
  { id: "settings",  label: "Settings",             href: "08-settings.html",           roles: ["platform_admin"] },
  { id: "advanced",  label: "Advanced operations",  href: "#advanced",                  roles: ["platform_admin", "auditor"], note: "feature flag" },
  { id: "api",       label: "API documentation ↗",  href: "#swagger",                   roles: ["platform_admin"] },
];

function canSee(item, roles) {
  if (!item.roles) return true;
  return item.roles.includes("*") || item.roles.some(r => roles.includes(r));
}

function renderShell() {
  const page = document.body.dataset.page || "";
  const personaKey = currentPersona();
  const user = PERSONAS[personaKey];
  const roles = user.roles;

  // Masthead ---------------------------------------------------------
  const head = document.getElementById("masthead");
  if (head) head.innerHTML = `
    <a class="brand" href="01-home.html" aria-label="CbCR workbench home"><span class="brand-mark" aria-hidden="true">N</span><span><strong>CBCR WORKBENCH</strong><small>OPERATIONS CONSOLE</small></span></a>
    <form class="global-search" role="search" onsubmit="return false"><input id="globalSearch" placeholder="Find by ID or reference (lot, dataset, run, case set…)" aria-label="Find by identifier"></form>
    <div class="right">
      <div class="profile-menu">
        <button class="status-dot" data-menu="statusPanel" aria-haspopup="true" aria-expanded="false" title="System status">PG · cbcr</button>
        <div class="menu status-panel" id="statusPanel" hidden>
          <div class="menu-head"><strong>System status</strong>All services nominal · checked 16:04</div>
          <dl class="kv" style="padding:4px 14px 8px">
            <dt>Backend</dt><dd>postgresql</dd>
            <dt>Database</dt><dd>cbcr</dd>
            <dt>Application user</dt><dd>cbcr_app</dd>
            <dt>Async workers</dt><dd>2 active · queue depth 1</dd>
            <dt>Migrations</dt><dd>0009 (current)</dd>
          </dl>
          ${roles.includes("platform_admin") ? `<div class="menu-sep"></div><a href="08-settings.html#system">Open system status in Settings</a>` : ""}
        </div>
      </div>
      <div class="profile-menu">
        <button data-menu="profilePanel" aria-haspopup="true" aria-expanded="false"><span class="avatar">${user.name.slice(0, 1).toUpperCase()}</span><span class="who">${user.name}<small>${user.persona.toUpperCase()}</small></span> ▾</button>
        <div class="menu" id="profilePanel" hidden>
          <div class="menu-head"><strong>${user.name}</strong>${user.persona} · roles: ${roles.join(", ")}</div>
          ${UTILITY.filter(u => canSee(u, roles)).map(u => `<a href="${u.href}">${u.label}${u.note ? ` <span class="muted">(${u.note})</span>` : ""}</a>`).join("")}
          <div class="menu-sep"></div>
          <a href="#signout">Sign out</a>
        </div>
      </div>
    </div>`;

  // Sidebar ----------------------------------------------------------
  const side = document.getElementById("sidebar");
  if (side) side.innerHTML = `
    <nav id="navigation" aria-label="Primary">${NAV.filter(i => canSee(i, roles)).map(i => i.section
      ? `<div class="nav-section">${i.section}</div>`
      : `<a href="${i.href}" class="${i.id === page ? "active" : ""}" ${i.id === page ? 'aria-current="page"' : ""}><span>${i.n}</span>${i.label}${badgeFor(i, roles)}</a>`).join("")}
    </nav>
    <div class="sidebar-utility">
      <div class="nav-section">Utilities</div>
      ${UTILITY.filter(u => canSee(u, roles)).map(u => `<a href="${u.href}" class="${u.id === page ? "active" : ""}">${u.label}</a>`).join("")}
    </div>`;
}

function badgeFor(item, roles) {
  if (!item.badge) return "";
  const n = roles.map(r => item.badge[r] || 0).reduce((a, b) => Math.max(a, b), 0);
  return n ? `<span class="nav-badge" title="${n} item(s) need your decision">${n}</span>` : "";
}

/* ------------------------------------------------------------------ */
/* PART B — generic widget behaviours                                   */
/* ------------------------------------------------------------------ */

function toast(message, error = false) {
  let node = document.getElementById("toast");
  if (!node) { node = document.createElement("div"); node.id = "toast"; node.setAttribute("role", "status"); document.body.appendChild(node); }
  node.textContent = message; node.className = error ? "show error" : "show";
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { node.className = ""; }, 3200);
}

// <button class="id-chip" data-id="FULL" title="FULL"><span class="kind">run</span><span class="short">294835a6…</span><span class="full">FULL</span><span class="copy">COPY</span></button>
// The markup can also be generated from a helper: idChip("run", fullId)
function idChip(kind, full) {
  const short = `${String(full).slice(0, 8)}…`;
  return `<button type="button" class="id-chip" data-id="${full}" title="${full}" aria-label="${kind} ${full} — click to expand">${kind ? `<span class="kind">${kind}</span>` : ""}<span class="short">${short}</span><span class="full">${full}</span><span class="copy" role="button" aria-label="Copy ${kind} identifier">COPY</span></button>`;
}

function activateTab(group, name) {
  group = group || document.querySelector(".workspace-tabs, .tabs");
  group.querySelectorAll("[data-tab]").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  const scope = group.closest("[data-tabgroup]") || document;
  scope.querySelectorAll(".workspace-tab, .report-tab").forEach(p => p.classList.toggle("active", p.id === `tab-${name}`));
  if (name && history.replaceState) history.replaceState(null, "", `#${name}`); // route-able tab state
}

function activateWizardStep(name) {
  document.querySelectorAll(".vstep").forEach(s => s.classList.toggle("current", s.dataset.step === name));
  document.querySelectorAll(".step[data-step]").forEach(s => s.classList.toggle("viewing", s.dataset.step === name)); // viewed ≠ pipeline's current step
  document.querySelectorAll(".wizard-step").forEach(p => p.classList.toggle("active", p.id === `step-${name}`));
  if (!document.getElementById(`step-${name}`)) {
    // No wizard panel (e.g. Oversight): treat the stepper as an index into the timeline below it.
    const steps = [...document.querySelectorAll(".step[data-step]")]; const i = steps.findIndex(s => s.dataset.step === name);
    const item = document.querySelectorAll(".timeline .tl-item")[i];
    if (item) { const body = item.querySelector(".tl-body"); if (body) body.hidden = false; item.scrollIntoView({ behavior: "smooth", block: "center" }); }
    return;
  }
  if (history.replaceState) history.replaceState(null, "", `#${name}`);
}

function closeMenus(except) {
  document.querySelectorAll(".menu").forEach(m => { if (m !== except) m.hidden = true; });
  document.querySelectorAll("[data-menu]").forEach(b => b.setAttribute("aria-expanded", b.nextElementSibling && !b.nextElementSibling.hidden ? "true" : "false"));
}

document.addEventListener("click", event => {
  const t = event.target;

  // ID chip: expand / copy
  const chip = t.closest(".id-chip");
  if (chip) {
    if (t.closest(".copy")) {
      const value = chip.dataset.id;
      (navigator.clipboard ? navigator.clipboard.writeText(value) : Promise.resolve()).then(() => toast(`Copied ${value}`));
    } else chip.classList.toggle("open");
    event.preventDefault(); return;
  }

  // Dropdown menus
  const menuBtn = t.closest("[data-menu]");
  if (menuBtn) {
    const menu = document.getElementById(menuBtn.dataset.menu);
    closeMenus(menu); menu.hidden = !menu.hidden; menuBtn.setAttribute("aria-expanded", String(!menu.hidden));
    event.stopPropagation(); return;
  }
  if (!t.closest(".menu")) closeMenus();

  // Generic toggle: <button data-toggle="#id"> or data-toggle="next"
  const tog = t.closest("[data-toggle]");
  if (tog) {
    const sel = tog.dataset.toggle;
    const target = sel === "next" ? tog.closest("tr,.run-card,.tl-item,.candidate,.panel").querySelector(".row-detail,.body,.tl-body,[data-body]") : document.querySelector(sel);
    if (target) { target.hidden = !target.hidden; tog.setAttribute("aria-expanded", String(!target.hidden)); const row = tog.closest("tr.summary"); if (row) row.classList.toggle("open", !target.hidden); }
    return;
  }

  // Accordion rows: click anywhere on tr.summary (except links/buttons/chips)
  const row = t.closest("tr.summary");
  if (row && !t.closest("a,button,input,select,textarea")) {
    const detail = row.nextElementSibling;
    if (detail && detail.classList.contains("row-detail")) { detail.hidden = !detail.hidden; row.classList.toggle("open", !detail.hidden); }
    return;
  }
  const cardTop = t.closest(".run-card .top, .tl-item .tl-head");
  if (cardTop && !t.closest("a,button,input,select,textarea")) {
    const body = cardTop.parentElement.querySelector(".body, .tl-body"); if (body) body.hidden = !body.hidden; return;
  }

  // Tabs
  const tab = t.closest("[data-tab]");
  if (tab) { activateTab(tab.closest(".workspace-tabs, .tabs"), tab.dataset.tab); closeMenus(); return; }

  // Vertical stepper (case workbench) and horizontal clickable steps
  const vstep = t.closest(".vstep[data-step], .step.clickable[data-step]");
  if (vstep) { activateWizardStep(vstep.dataset.step); return; }
  const go = t.closest("[data-go-step]");
  if (go) { activateWizardStep(go.dataset.goStep); window.scrollTo({ top: 0, behavior: "smooth" }); return; }

  // Dialogs
  const dlg = t.closest("[data-dialog]");
  if (dlg) { const d = document.getElementById(dlg.dataset.dialog); if (d) d.showModal(); return; }

  // Segmented controls
  const seg = t.closest(".segmented button");
  if (seg) { seg.parentElement.querySelectorAll("button").forEach(b => b.classList.toggle("active", b === seg)); return; }

  // Lot group collapse
  const lotToggle = t.closest(".lot-toggle");
  if (lotToggle) { lotToggle.closest(".lot-group").classList.toggle("collapsed"); return; }

  // Settings sub navigation
  const sub = t.closest(".sub-nav a[data-section]");
  if (sub) { event.preventDefault(); document.querySelectorAll(".sub-nav a").forEach(a => a.classList.toggle("active", a === sub)); document.querySelectorAll(".settings-section").forEach(s => s.classList.toggle("active", s.id === sub.dataset.section)); return; }

  // Simulated actions
  const simulated = t.closest("[data-toast]");
  if (simulated) { event.preventDefault(); toast(simulated.dataset.toast); closeMenus(); const d = simulated.closest("dialog"); if (d) d.close(); return; }
});

// Radio stacks: highlight the chosen option
document.addEventListener("change", event => {
  const radio = event.target.closest(".radio-stack input[type=radio]");
  if (!radio) return;
  radio.closest(".radio-stack").querySelectorAll("label").forEach(l => l.classList.toggle("selected", l.contains(radio)));
});

// Function picker: purpose lock. Cards carry data-purpose; selecting one purpose
// disables the other purposes immediately (brief §7.5 Run functions).
document.addEventListener("change", event => {
  const box = event.target.closest(".function-card header input[type=checkbox]");
  if (!box) return;
  const card = box.closest(".function-card"); card.classList.toggle("selected", box.checked);
  const selected = [...document.querySelectorAll(".function-card.selected")];
  const purposes = new Set(selected.map(c => c.dataset.purpose));
  const lock = purposes.size === 1 ? [...purposes][0] : null;
  document.querySelectorAll(".function-card").forEach(c => {
    const incompatible = lock && c.dataset.purpose !== lock;
    c.classList.toggle("incompatible", !!incompatible);
    const input = c.querySelector("header input"); if (input) input.disabled = !!incompatible;
    const reason = c.querySelector(".reason"); if (reason) reason.hidden = !incompatible;
  });
  const summary = document.getElementById("functionSummary");
  if (summary) summary.textContent = `${selected.length} selected · purpose: ${lock ? lock.replaceAll("_", " ") : "—"}`;
  const exec = document.getElementById("execSummary"); if (exec) exec.hidden = selected.length === 0;
  const list = document.getElementById("execFunctions"); if (list) list.innerHTML = selected.map(c => `<li>${c.querySelector("h3").textContent}</li>`).join("") || "<li>—</li>";
});

/* ------------------------------------------------------------------ */
/* PART C — mock-only controls (persona + theme)                        */
/* ------------------------------------------------------------------ */

function storage(key, value) {
  try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (_) { return null; }
}
function currentPersona() { return storage("mock.persona") || document.body.dataset.defaultPersona || "analyst"; }

function renderMockBar() {
  const bar = document.createElement("div");
  bar.className = "mock-bar";
  bar.innerHTML = `<b>MOCKUP</b>
    <label>Persona <select id="mockPersona">${Object.entries(PERSONAS).map(([k, p]) => `<option value="${k}">${p.persona} (${p.name})</option>`).join("")}</select></label>
    <label>Theme <select id="mockTheme"><option value="wip">Default (WIP, current)</option><option value="polished">Polished (Niche)</option></select></label>
    <a href="00-index.html">Index</a>`;
  document.body.appendChild(bar);
  const persona = bar.querySelector("#mockPersona"); persona.value = currentPersona();
  persona.onchange = () => { storage("mock.persona", persona.value); renderShell(); applyPersonaScopes(); toast(`Viewing as ${PERSONAS[persona.value].persona}`); };
  const theme = bar.querySelector("#mockTheme"); theme.value = storage("mock.theme") || "wip";
  theme.onchange = () => { storage("mock.theme", theme.value); applyTheme(); };
}
function applyTheme() { document.body.classList.toggle("wip", (storage("mock.theme") || "wip") === "wip"); }
// Elements that only certain roles should see inside a page: data-roles="auditor platform_admin"
function applyPersonaScopes() {
  const roles = PERSONAS[currentPersona()].roles;
  document.querySelectorAll("[data-roles]").forEach(el => { el.hidden = !el.dataset.roles.split(/\s+/).some(r => roles.includes(r)); });
  document.querySelectorAll("[data-persona-name]").forEach(el => { el.textContent = PERSONAS[currentPersona()].name; });
}

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(); renderShell(); renderMockBar(); applyPersonaScopes();
  // Restore hash-routed tab / step (deep-linkable state, brief §8.1)
  const hash = location.hash.replace("#", "");
  if (hash && document.getElementById(`tab-${hash}`)) { const g = document.querySelector(".workspace-tabs, .tabs"); if (g) activateTab(g, hash); }
  if (hash && document.getElementById(`step-${hash}`)) activateWizardStep(hash);
  const dlg = hash && document.getElementById(hash); if (dlg && dlg.tagName === "DIALOG") dlg.showModal(); // e.g. 02-lifecycle.html#intake → intakeDialog
  if (hash === "intake") { const d = document.getElementById("intakeDialog"); if (d) d.showModal(); }
  document.querySelectorAll("[data-ids]").forEach(el => { el.innerHTML = idChip(el.dataset.kind || "", el.dataset.ids); });
});
