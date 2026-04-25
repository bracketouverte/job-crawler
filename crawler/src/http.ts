import { HttpClient } from "./types.js";

export class HttpError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly body?: string
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export type HttpOptions = {
  timeoutMs: number;
  retries: number;
};

const transientStatuses = new Set([408, 425, 429, 500, 502, 503, 504]);

export function createHttpClient(options: HttpOptions): HttpClient {
  async function request(url: string, init: RequestInit = {}): Promise<Response> {
    let lastError: unknown;

    for (let attempt = 0; attempt <= options.retries; attempt += 1) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), options.timeoutMs);

      try {
        const response = await fetch(url, {
          ...init,
          signal: controller.signal,
          headers: {
            "User-Agent": "job-scrapper-crawler/1.0",
            ...init.headers
          }
        });

        if (!response.ok) {
          const body = await response.text().catch(() => "");
          const error = new HttpError(`HTTP ${response.status} for ${url}`, response.status, body);
          if (attempt < options.retries && transientStatuses.has(response.status)) {
            await delay(backoffMs(attempt));
            continue;
          }
          throw error;
        }

        return response;
      } catch (error) {
        lastError = error;
        if (error instanceof HttpError && !isTransientHttpError(error)) {
          throw error;
        }
        if (attempt >= options.retries) {
          throw normalizeError(error, url);
        }
        await delay(backoffMs(attempt));
      } finally {
        clearTimeout(timeout);
      }
    }

    throw normalizeError(lastError, url);
  }

  return {
    async getJson<T = unknown>(url: string, init?: RequestInit): Promise<T> {
      const response = await request(url, { ...init, method: "GET" });
      return response.json() as Promise<T>;
    },
    async postJson<T = unknown>(url: string, body: unknown, init?: RequestInit): Promise<T> {
      const response = await request(url, {
        ...init,
        method: "POST",
        body: JSON.stringify(body),
        headers: {
          "Content-Type": "application/json",
          ...init?.headers
        }
      });
      return response.json() as Promise<T>;
    },
    async getText(url: string, init?: RequestInit): Promise<string> {
      const response = await request(url, { ...init, method: "GET" });
      return response.text();
    }
  };
}

function isTransientHttpError(error: HttpError): boolean {
  return error.status !== undefined && transientStatuses.has(error.status);
}

function normalizeError(error: unknown, url: string): Error {
  if (error instanceof Error) {
    if (error.name === "AbortError") {
      return new Error(`Timeout while fetching ${url}`);
    }
    return error;
  }
  return new Error(`Unknown error while fetching ${url}`);
}

function backoffMs(attempt: number): number {
  return Math.min(5000, 250 * 2 ** attempt);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
