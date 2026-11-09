export const esc = value => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
export const shortId = value => value ? `${String(value).slice(0, 8)}…` : "—";
export const fmtDate = value => value ? new Intl.DateTimeFormat(undefined,{dateStyle:"medium",timeStyle:"short"}).format(new Date(value)) : "—";
export const title = value => String(value || "—").replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());
export const status = value => `<span class="status ${esc(value)}">${esc(title(value))}</span>`;
export const idChip = (value, label="identifier") => value ? `<span class="id-chip" data-id-chip="${esc(value)}" title="${esc(value)}"><button type="button" class="id-chip-value" data-id-toggle aria-label="Expand ${esc(label)}">${esc(shortId(value))}</button><button type="button" class="id-chip-copy" data-id-copy aria-label="Copy ${esc(label)}" title="Copy ${esc(label)}">⧉</button></span>` : "—";
export const empty = (heading, body, action="") => `<div class="empty-state"><h2>${esc(heading)}</h2><p>${esc(body)}</p>${action}</div>`;
export const technical = content => `<details class="tech-details"><summary>Technical details</summary><div>${content}</div></details>`;
export const jsonBlock = value => `<pre class="code-block">${esc(JSON.stringify(value ?? {}, null, 2))}</pre>`;
export const help = text => `<span class="help" title="${esc(text)}" aria-label="${esc(text)}">i</span>`;

export function toast(message, kind="success") {
  const region = document.querySelector("#toast-region");
  const item = document.createElement("div"); item.className = `toast ${kind}`; item.textContent = message;
  region.append(item); setTimeout(() => item.remove(), 4500);
}

export function dialog({title: heading, body, submitLabel="Save", onSubmit, wide=false}) {
  const region = document.querySelector("#dialog-region");
  const opener = document.activeElement;
  const element = document.createElement("dialog"); if (wide) element.style.width = "min(920px,calc(100% - 28px))";
  element.innerHTML = `<form method="dialog"><div class="dialog-head"><div><p class="eyebrow">Guided action</p><h2>${esc(heading)}</h2></div><button type="submit" class="icon-button" value="cancel" formnovalidate aria-label="Close">×</button></div><div class="dialog-body">${body}</div><div class="dialog-actions"><button type="submit" class="button-secondary" value="cancel" formnovalidate>Cancel</button><button type="submit" class="button" value="submit">${esc(submitLabel)}</button></div></form>`;
  region.append(element); const form = element.querySelector("form");
  form.addEventListener("submit", async event => {
    const submitter = event.submitter?.value;
    if (submitter !== "submit") return;
    event.preventDefault();
    const button = event.submitter; button.disabled = true;
    try { await onSubmit(new FormData(form), element); element.close(); }
    catch (error) { toast(error.message || String(error), "error"); button.disabled = false; }
  });
  element.addEventListener("click", event => { if (event.target === element) element.close("cancel"); });
  element.addEventListener("close", () => { element.remove(); if (opener?.isConnected) opener.focus(); }, {once:true});
  element.showModal();
  requestAnimationFrame(() => element.querySelector("input:not([type=hidden]),select,textarea,button")?.focus());
  return element;
}

export function confirmAction(heading, body, onConfirm, confirmLabel="Confirm") {
  return dialog({title:heading, body:`<p>${esc(body)}</p>`,submitLabel:confirmLabel,onSubmit:onConfirm});
}

export function bindCommon(root=document) {
  root.querySelectorAll("[data-id-chip]").forEach(chip => {
    if (chip.dataset.bound) return;
    chip.dataset.bound = "1";
    const value = chip.dataset.idChip, toggle = chip.querySelector("[data-id-toggle]");
    toggle?.addEventListener("click", () => {
      chip.classList.toggle("expanded");
      toggle.textContent = chip.classList.contains("expanded") ? value : shortId(value);
      toggle.setAttribute("aria-expanded", String(chip.classList.contains("expanded")));
    });
    chip.querySelector("[data-id-copy]")?.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(value); toast("Identifier copied"); }
      catch { toast("Copy was blocked by the browser", "error"); }
    });
  });
}

export function permissionError(error, action="view this page") {
  if (error?.status === 403) return `<div class="page-error"><p class="eyebrow">Access controlled</p><h1>Permission required</h1><p>Your current role cannot ${esc(action)}. Ask an administrator if this access is required.</p></div>`;
  return `<div class="page-error"><p class="eyebrow">Unable to load</p><h1>Something went wrong</h1><p>${esc(error?.message || error)}</p></div>`;
}

export function formObject(formData) { return Object.fromEntries([...formData.entries()].filter(([,v]) => v !== "")); }
export function numeric(value, fallback=null) { return value === "" || value == null ? fallback : Number(value); }
