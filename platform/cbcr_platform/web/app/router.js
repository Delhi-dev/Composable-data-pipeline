const routes = [
  [/^\/$/, "home"], [/^\/lifecycle\/?$/, "lifecycle"],
  [/^\/datasets\/([^/]+)\/v(\d+)\/([^/]+)\/?$/, "workspace"],
  [/^\/runs(?:\/([^/]+))?\/?$/, "runs"],
  [/^\/cases(?:\/([^/]+)\/v(\d+)\/([^/]+))?\/?$/, "cases"],
  [/^\/reports(?:\/([^/]+)\/([^/]+))?\/?$/, "reports"],
  [/^\/oversight(?:\/([^/]+))?\/?$/, "oversight"],
  [/^\/reference\/?$/, "reference"], [/^\/settings(?:\/([^/]+))?\/?$/, "settings"],
];

export function match(path=location.pathname) {
  for (const [pattern, name] of routes) { const found = path.match(pattern); if (found) return {name, parts:found.slice(1)}; }
  return {name:"notFound", parts:[]};
}
export function navigate(path) { history.pushState({}, "", path); window.dispatchEvent(new PopStateEvent("popstate")); }
export function bindLinks(root=document) { root.querySelectorAll("a[data-route]").forEach(link => link.addEventListener("click", event => { if (!event.metaKey && !event.ctrlKey) { event.preventDefault(); navigate(link.getAttribute("href")); } })); }
