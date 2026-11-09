export class ApiError extends Error {
  constructor(status, message, body) { super(message); this.status = status; this.body = body; }
}

const actor = () => window.CBCR_ACTOR || localStorage.getItem("cbcr_actor") || "demo";

export async function api(path, options = {}) {
  const headers = {Accept: "application/json", "X-CBCR-User": actor(), ...(options.headers || {})};
  if (options.body && typeof options.body !== "string") {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, {...options, headers});
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = body?.detail || body?.message || `${response.status} ${response.statusText}`;
    throw new ApiError(response.status, typeof detail === "string" ? detail : JSON.stringify(detail), body);
  }
  return body;
}

export function query(values = {}) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, value);
  });
  const text = params.toString();
  return text ? `?${text}` : "";
}

export async function download(path, filename) {
  const response = await fetch(path, {headers: {"X-CBCR-User": actor()}});
  if (!response.ok) throw new ApiError(response.status, await response.text());
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob); link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
