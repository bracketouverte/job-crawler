import assert from "node:assert/strict";
import test from "node:test";
import { createHttpClient, HttpError } from "./http.js";

test("getJson returns parsed JSON", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ ok: true }), { status: 200 });

  try {
    const http = createHttpClient({ timeoutMs: 1000, retries: 0 });
    assert.deepEqual(await http.getJson("https://example.com"), { ok: true });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("getJson throws HttpError for non-transient status without retry", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("nope", { status: 404 });

  try {
    const http = createHttpClient({ timeoutMs: 1000, retries: 1 });
    await assert.rejects(() => http.getJson("https://example.com"), (error) => {
      assert.equal(error instanceof HttpError, true);
      assert.equal((error as HttpError).status, 404);
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
