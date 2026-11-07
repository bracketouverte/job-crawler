/** Error from a non-2xx response; `message` is the server's `detail` when present. */
export class ApiError extends Error {
  /**
   * @param {number} status
   * @param {string} message
   */
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * @param {typeof fetch} [fetchImpl]
 * @param {string} [base]
 */
export function createApi(fetchImpl = fetch, base = "/api") {
  /**
   * @param {string} method
   * @param {string} path
   * @param {{ params?: Record<string, string | number | undefined | null>, body?: unknown }} [options]
   */
  async function request(method, path, options = {}) {
    let url = `${base}${path}`;
    if (options.params) {
      const search = new URLSearchParams();
      for (const [k, v] of Object.entries(options.params)) {
        if (v !== undefined && v !== null) search.set(k, String(v));
      }
      const query = search.toString();
      if (query) url += `?${query}`;
    }
    /** @type {RequestInit} */
    const init = { method };
    if (options.body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(options.body);
    }
    const response = await fetchImpl(url, init);
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        const data = await response.json();
        if (typeof data?.detail === "string") message = data.detail;
      } catch {
        // Non-JSON error body: keep the generic message.
      }
      throw new ApiError(response.status, message);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  return {
    get: (path, options) => request("GET", path, options),
    post: (path, body, options = {}) => request("POST", path, { ...options, body }),
    put: (path, body) => request("PUT", path, { body }),
    delete: (path) => request("DELETE", path),
  };
}

export const api = createApi();
